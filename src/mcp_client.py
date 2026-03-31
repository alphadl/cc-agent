"""MCP (Model Context Protocol) client — connects to external MCP servers and exposes their tools.

MCP allows cc-agent to use tools provided by external servers (e.g., filesystem, database,
web search, custom APIs). The protocol uses JSON-RPC over stdio or HTTP+SSE transports.

This implementation is self-contained (no external `mcp` package required) and supports:
  - stdio transport (local subprocess with stdin/stdout JSON-RPC)
  - HTTP+SSE transport (remote MCP servers)
  - Tool discovery, invocation, and schema conversion
  - Configuration via ~/.cc-agent/mcp_servers.json or per-project .mcp.json

Usage:
  # Config file (~/.cc-agent/mcp_servers.json or .mcp.json):
  {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-filesystem", "/path/to/dir"],
        "env": {}
      },
      "web-search": {
        "url": "http://localhost:3001/sse",
        "headers": {"Authorization": "Bearer token"}
      }
    }
  }
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ── JSON-RPC helpers ────────────────────────────────────────────────────


def _jsonrpc_request(method: str, params: dict | None = None, request_id: int = 1) -> str:
    """Build a JSON-RPC 2.0 request string."""
    msg = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def _parse_jsonrpc_response(data: str) -> dict:
    """Parse a JSON-RPC 2.0 response."""
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        return {"error": {"message": f"Invalid JSON-RPC response: {e}", "code": -32700}}


# ── MCP Server Configuration ────────────────────────────────────────────


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str
    # For stdio transport
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    # For HTTP+SSE transport
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def transport(self) -> str:
        return "sse" if self.url else "stdio"

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "MCPServerConfig":
        return cls(
            name=name,
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            cwd=data.get("cwd"),
            url=data.get("url"),
            headers=data.get("headers", {}),
        )


def load_mcp_config(cwd: str | None = None) -> Dict[str, MCPServerConfig]:
    """Load MCP server configuration from config files.

    Search order:
      1. <project>/.mcp.json
      2. ~/.cc-agent/mcp_servers.json
    """
    servers = {}

    # Project-level config
    search = Path(cwd) if cwd else Path.cwd()
    for parent in [search] + list(search.parents)[:5]:
        proj = parent / ".mcp.json"
        if proj.exists():
            try:
                data = json.loads(proj.read_text(encoding="utf-8"))
                for name, server_data in data.get("mcpServers", {}).items():
                    servers[name] = MCPServerConfig.from_dict(name, server_data)
            except Exception:
                pass
            break
        if (parent / ".git").exists():
            break

    # User-level config
    user_config = Path.home() / ".cc-agent" / "mcp_servers.json"
    if user_config.exists():
        try:
            data = json.loads(user_config.read_text(encoding="utf-8"))
            for name, server_data in data.get("mcpServers", {}).items():
                servers[name] = MCPServerConfig.from_dict(name, server_data)
        except Exception:
            pass

    return servers


# ── MCP Stdio Transport ─────────────────────────────────────────────────


class StdioTransport:
    """JSON-RPC over stdin/stdout with a subprocess."""

    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._buffer = ""

    def connect(self) -> None:
        """Start the MCP server subprocess."""
        if self._process and self._process.poll() is None:
            return

        env = os.environ.copy()
        env.update(self._config.env)

        try:
            self._process = subprocess.Popen(
                [self._config.command] + self._config.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=self._config.cwd,
                text=False,  # binary mode for reliable line splitting
            )
        except FileNotFoundError:
            raise RuntimeError(f"MCP server command not found: {self._config.command}")
        except Exception as e:
            raise RuntimeError(f"Failed to start MCP server '{self._config.name}': {e}")

    def send_and_receive(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        with self._lock:
            self._request_id += 1
            req_id = self._request_id

            request = _jsonrpc_request(method, params, req_id)
            if self._process is None or self._process.poll() is not None:
                self.connect()

            assert self._process is not None
            assert self._process.stdin is not None
            assert self._process.stdout is not None

            # Send request
            self._process.stdin.write((request + "\n").encode("utf-8"))
            self._process.stdin.flush()

            # Read response(s) until we get our request_id or timeout
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    line = self._process.stdout.readline()
                    if not line:
                        break
                    line = line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    resp = _parse_jsonrpc_response(line)
                    if resp.get("id") == req_id:
                        return resp
                    # Ignore notifications or responses for other requests
                except Exception:
                    break

            return {"error": {"message": f"MCP request timed out after {timeout}s", "code": -32603}}

    def close(self) -> None:
        if self._process and self._process.poll() is None:
            try:
                self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None


# ── MCP SSE/HTTP Transport ──────────────────────────────────────────────


class SSETransport:
    """JSON-RPC over HTTP+SSE for remote MCP servers."""

    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._base_url = config.url
        self._headers = config.headers
        self._request_id = 0
        self._session_id: Optional[str] = None

    def connect(self) -> None:
        """Initialize connection to SSE endpoint and get session ID."""
        try:
            import urllib.request
            req = urllib.request.Request(
                self._base_url,
                headers={"Accept": "text/event-stream", **self._headers},
                method="GET",
            )
            # Just verify connectivity — don't block on SSE stream
            with urllib.request.urlopen(req, timeout=10) as resp:
                self._session_id = resp.headers.get("Mcp-Session-Id")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to MCP SSE server '{self._config.name}': {e}")

    def send_and_receive(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        """Send JSON-RPC via HTTP POST and return response."""
        self._request_id += 1
        req_id = self._request_id
        request = _jsonrpc_request(method, params, req_id)

        try:
            import urllib.request
            headers = {
                "Content-Type": "application/json",
                **self._headers,
            }
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id

            req = urllib.request.Request(
                self._base_url,
                data=request.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8")
                return _parse_jsonrpc_response(data)
        except Exception as e:
            return {"error": {"message": f"MCP HTTP request failed: {e}", "code": -32603}}

    def close(self) -> None:
        self._session_id = None


# ── MCP Client ──────────────────────────────────────────────────────────


@dataclass
class MCPTool:
    """A tool exposed by an MCP server."""
    name: str
    description: str
    input_schema: dict
    server_name: str

    def to_anthropic_schema(self) -> dict:
        """Convert to Anthropic tool schema format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class MCPClient:
    """Client for a single MCP server — handles connection, tool discovery, and invocation."""

    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._transport: Optional[StdioTransport | SSETransport] = None
        self._tools: List[MCPTool] = []
        self._connected = False
        self._server_info: dict = {}
        self._capabilities: dict = {}

    def connect(self) -> None:
        """Connect to the MCP server and initialize."""
        if self._connected:
            return

        if self._config.transport == "stdio":
            self._transport = StdioTransport(self._config)
        else:
            self._transport = SSETransport(self._config)

        self._transport.connect()

        # Initialize per MCP protocol
        resp = self._transport.send_and_receive("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "cc-agent", "version": "1.0.0"},
        })

        if "error" in resp:
            raise RuntimeError(f"MCP initialize failed for '{self._config.name}': {resp['error']}")

        self._server_info = resp.get("result", {}).get("serverInfo", {})
        self._capabilities = resp.get("result", {}).get("capabilities", {})

        # Send initialized notification
        # (JSON-RPC notification = no id, no response expected)
        if hasattr(self._transport, '_process') and self._transport._process:
            try:
                self._transport.send_and_receive("notifications/initialized", timeout=2)
            except Exception:
                pass

        # Discover tools
        self._tools = self._list_tools()
        self._connected = True

    def _list_tools(self) -> List[MCPTool]:
        """List available tools from the MCP server."""
        resp = self._transport.send_and_receive("tools/list", {})
        if "error" in resp:
            return []

        tools = []
        for tool_data in resp.get("result", {}).get("tools", []):
            tools.append(MCPTool(
                name=f"mcp__{self._config.name}__{tool_data.get('name', 'unknown')}",
                description=tool_data.get("description", ""),
                input_schema=tool_data.get("inputSchema", {"type": "object", "properties": {}}),
                server_name=self._config.name,
            ))
        return tools

    @property
    def tools(self) -> List[MCPTool]:
        return self._tools

    @property
    def server_name(self) -> str:
        return self._config.name

    @property
    def server_info(self) -> dict:
        return self._server_info

    def call_tool(self, tool_name: str, arguments: dict, timeout: float = 120) -> dict:
        """Call a tool on the MCP server.

        tool_name should be the full mcp-prefixed name (e.g. "mcp__filesystem__read_file").
        The original name is extracted and sent to the server.
        """
        # Strip the mcp__ prefix to get the original tool name
        prefix = f"mcp__{self._config.name}__"
        if tool_name.startswith(prefix):
            original_name = tool_name[len(prefix):]
        else:
            original_name = tool_name

        resp = self._transport.send_and_receive("tools/call", {
            "name": original_name,
            "arguments": arguments,
        }, timeout=timeout)

        if "error" in resp:
            return {
                "content": f"MCP tool error: {resp['error'].get('message', 'unknown error')}",
                "isError": True,
            }

        result = resp.get("result", {})
        # MCP tool results have a "content" list of text/image blocks
        content_parts = []
        for block in result.get("content", []):
            if isinstance(block, dict):
                if block.get("type") == "text":
                    content_parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    content_parts.append("[image]")
                else:
                    content_parts.append(str(block))
            else:
                content_parts.append(str(block))

        return {
            "content": "\n".join(content_parts),
            "isError": result.get("isError", False),
        }

    def close(self) -> None:
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
        self._connected = False


# ── MCP Manager — manages all configured MCP servers ───────────────────


class MCPManager:
    """Manages connections to multiple MCP servers and aggregates their tools."""

    def __init__(self, cwd: str | None = None):
        self._clients: Dict[str, MCPClient] = {}
        self._config = load_mcp_config(cwd)
        self._connected = False
        self._errors: List[str] = []

    @property
    def server_configs(self) -> Dict[str, MCPServerConfig]:
        return self._config

    @property
    def errors(self) -> List[str]:
        return self._errors

    def connect_all(self) -> None:
        """Connect to all configured MCP servers."""
        if not self._config:
            return

        for name, config in self._config.items():
            try:
                client = MCPClient(config)
                client.connect()
                self._clients[name] = client
            except Exception as e:
                self._errors.append(f"{name}: {e}")

        self._connected = True

    def connect_server(self, name: str) -> bool:
        """Connect to a specific MCP server by name."""
        config = self._config.get(name)
        if not config:
            return False
        try:
            client = MCPClient(config)
            client.connect()
            self._clients[name] = client
            return True
        except Exception as e:
            self._errors.append(f"{name}: {e}")
            return False

    @property
    def all_tools(self) -> List[MCPTool]:
        """Get all tools from all connected MCP servers."""
        tools = []
        for client in self._clients.values():
            tools.extend(client.tools)
        return tools

    def all_tool_schemas(self) -> List[dict]:
        """Get all tool schemas in Anthropic format."""
        return [t.to_anthropic_schema() for t in self.all_tools]

    def call_tool(self, tool_name: str, arguments: dict, timeout: float = 120) -> dict | None:
        """Call a tool on the appropriate MCP server.

        Returns None if the tool is not found in any MCP server.
        """
        for client in self._clients.values():
            for tool in client.tools:
                if tool.name == tool_name:
                    return client.call_tool(tool_name, arguments, timeout)
        return None

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool name is provided by any MCP server."""
        return any(t.name == tool_name for t in self.all_tools)

    def get_tool_names(self) -> List[str]:
        """Get all MCP tool names."""
        return [t.name for t in self.all_tools]

    def close_all(self) -> None:
        """Close all MCP server connections."""
        for client in self._clients.values():
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()
        self._connected = False

    def status(self) -> str:
        """Return a human-readable status of all MCP connections."""
        if not self._config:
            return "No MCP servers configured."
        lines = []
        for name, config in self._config.items():
            client = self._clients.get(name)
            if client and client._connected:
                lines.append(f"  {_GREEN}✓{_RESET} {name}: {len(client.tools)} tools ({config.transport})")
            elif any(name in e for e in self._errors):
                err = [e for e in self._errors if name in e][0]
                lines.append(f"  {_RED}✗{_RESET} {name}: {err}")
            else:
                lines.append(f"  {_DIM}○{_RESET} {name}: not connected ({config.transport})")
        return "\n".join(lines)


# ── ANSI colors (avoid circular import) ────────────────────────────────
_GREEN = "\033[92m"
_RED = "\033[91m"
_RESET = "\033[0m"
_DIM = "\033[2m"
