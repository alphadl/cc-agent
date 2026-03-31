"""MCP Tool Adapter — bridges MCP server tools into cc-agent's tool system.

Creates dynamic Tool subclasses for each MCP-discovered tool, allowing the
agent loop to invoke them seamlessly alongside built-in tools.
"""
from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Optional, Type

from .tools_impl.base import Tool, ToolResult
from .mcp_client import MCPClient, MCPManager, MCPTool


class MCPToolAdapter(Tool):
    """Dynamic adapter that wraps an MCP tool as a cc-agent Tool."""

    def __init__(self, mcp_tool: MCPTool, client: MCPClient):
        self._mcp_tool = mcp_tool
        self._client = client
        # Set class-level attributes for the Tool protocol
        self.__class__.name = mcp_tool.name
        self.__class__.description = mcp_tool.description
        self.__class__.input_schema = mcp_tool.input_schema
        self.__class__.requires_permission = "execute"

    @classmethod
    def schema(cls) -> dict:
        # Instance-level schema is set via __init__, class-level fallback
        if hasattr(cls, '_instance_schema'):
            return cls._instance_schema
        return {
            "name": getattr(cls, 'name', 'mcp_tool'),
            "description": getattr(cls, 'description', ''),
            "input_schema": getattr(cls, 'input_schema', {"type": "object", "properties": {}}),
        }

    def run(self, **kwargs: Any) -> ToolResult:
        result = self._client.call_tool(self._mcp_tool.name, kwargs)
        if result is None:
            return ToolResult(f"MCP tool '{self._mcp_tool.name}' not found", is_error=True)
        return ToolResult(
            content=result.get("content", ""),
            is_error=result.get("isError", False),
        )

    def run_safe(self, **kwargs: Any) -> ToolResult:
        """Run with extra error handling for the agent loop."""
        try:
            return self.run(**kwargs)
        except Exception as e:
            return ToolResult(f"MCP tool error: {e}", is_error=True)


def create_mcp_tool_classes(manager: MCPManager) -> List[Type[Tool]]:
    """Create Tool subclasses for all MCP tools from a connected MCPManager.

    Returns a list of Tool classes that can be passed to AgentLoop as extra_tools.
    """
    tool_classes = []

    for client in manager._clients.values():
        for mcp_tool in client.tools:
            # Create a unique class for each MCP tool
            class_name = f"MCP_{mcp_tool.server_name}_{mcp_tool.name.replace('.', '_').replace('-', '_')}"

            # Create the class dynamically
            tool_class = type(class_name, (Tool,), {
                'name': mcp_tool.name,
                'description': mcp_tool.description,
                'input_schema': mcp_tool.input_schema,
                'requires_permission': 'execute',
                '_mcp_tool': mcp_tool,
                '_mcp_client': client,
                'run': lambda self, **kw: ToolResult(
                    content=self._mcp_client.call_tool(self._mcp_tool.name, kw).get("content", ""),
                    is_error=False,
                ) if self._mcp_client.call_tool(self._mcp_tool.name, kw) else ToolResult("MCP error", is_error=True),
            })

            tool_classes.append(tool_class)

    return tool_classes


def get_mcp_tools(cwd: str | None = None) -> tuple[List[type], MCPManager]:
    """Connect to all configured MCP servers and return (tool_classes, manager).

    Returns empty list if no MCP servers are configured or connection fails.
    The manager should be closed when done (manager.close_all()).
    """
    manager = MCPManager(cwd)

    if not manager.server_configs:
        return [], manager

    try:
        manager.connect_all()
        tools = create_mcp_tool_classes(manager)
        return tools, manager
    except Exception:
        return [], manager
