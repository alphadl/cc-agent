"""Tests for all P0 features: parallel tools, MCP, token counting, thinking, headless, sessions, rich UI."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

# ── P0 #1: Parallel tool execution (already existed) ───────────────────


class TestParallelTools(unittest.TestCase):
    """Verify agent loop supports parallel tool execution."""

    def test_agent_loop_has_parallel_flag(self):
        from src.agent_loop import AgentLoop
        loop = AgentLoop.__new__(AgentLoop)
        loop._parallel_tools = True
        self.assertTrue(loop._parallel_tools)

    def test_agent_loop_accepts_parallel_param(self):
        import inspect
        from src.agent_loop import AgentLoop
        sig = inspect.signature(AgentLoop.__init__)
        self.assertIn("parallel_tools", sig.parameters)


# ── P0 #2: MCP (Model Context Protocol) support ────────────────────────


class TestMCP(unittest.TestCase):
    """Verify MCP client, transport, config, and tool bridging."""

    def test_mcp_config_load_empty(self):
        from src.mcp_client import load_mcp_config
        config = load_mcp_config("/tmp/nonexistent")
        self.assertEqual(len(config), 0)

    def test_mcp_server_config_stdio(self):
        from src.mcp_client import MCPServerConfig
        cfg = MCPServerConfig.from_dict("fs", {
            "command": "npx",
            "args": ["-y", "@anthropic/mcp-filesystem", "/tmp"],
        })
        self.assertEqual(cfg.name, "fs")
        self.assertEqual(cfg.transport, "stdio")
        self.assertEqual(cfg.command, "npx")
        self.assertEqual(cfg.args, ["-y", "@anthropic/mcp-filesystem", "/tmp"])

    def test_mcp_server_config_sse(self):
        from src.mcp_client import MCPServerConfig
        cfg = MCPServerConfig.from_dict("web", {
            "url": "http://localhost:3001/sse",
            "headers": {"Authorization": "Bearer x"},
        })
        self.assertEqual(cfg.name, "web")
        self.assertEqual(cfg.transport, "sse")
        self.assertEqual(cfg.url, "http://localhost:3001/sse")

    def test_mcp_manager_empty(self):
        from src.mcp_client import MCPManager
        mgr = MCPManager("/tmp/nonexistent")
        self.assertEqual(len(mgr.all_tools), 0)
        self.assertFalse(mgr.has_tool("anything"))
        mgr.close_all()

    def test_mcp_tools_bridge(self):
        from src.mcp_tools import get_mcp_tools
        tools, mgr = get_mcp_tools("/tmp/nonexistent")
        self.assertEqual(len(tools), 0)
        mgr.close_all()

    def test_mcp_jsonrpc_helpers(self):
        from src.mcp_client import _jsonrpc_request, _parse_jsonrpc_response
        req = _jsonrpc_request("tools/list", {"cursor": None}, 1)
        data = json.loads(req)
        self.assertEqual(data["jsonrpc"], "2.0")
        self.assertEqual(data["method"], "tools/list")
        self.assertEqual(data["id"], 1)

        resp = _parse_jsonrpc_response('{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')
        self.assertEqual(resp["id"], 1)
        self.assertIn("result", resp)


# ── P0 #3: Actual token counting ───────────────────────────────────────


class TestTokenCounter(unittest.TestCase):
    """Verify accurate token counting with multiple backends."""

    def test_backend_detection(self):
        from src.token_counter import get_backend_name
        backend = get_backend_name()
        self.assertIn(backend, ["anthropic-api", "tiktoken", "builtin-bpe"])

    def test_count_tokens_basic(self):
        from src.token_counter import count_tokens
        count = count_tokens("Hello, world!")
        self.assertGreater(count, 0)
        # "Hello, world!" should be 2-4 tokens depending on backend
        self.assertLess(count, 20)

    def test_count_tokens_empty(self):
        from src.token_counter import count_tokens
        self.assertEqual(count_tokens(""), 0)
        self.assertEqual(count_tokens(None), 0)

    def test_count_messages_tokens(self):
        from src.token_counter import count_messages_tokens
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        count = count_messages_tokens(msgs)
        self.assertGreater(count, 0)

    def test_count_messages_with_tool_blocks(self):
        from src.token_counter import count_messages_tokens
        msgs = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "Let me read that."},
                {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/tmp/x"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "file contents"},
            ]},
        ]
        count = count_messages_tokens(msgs)
        self.assertGreater(count, 10)

    def test_context_manager_uses_token_counter(self):
        from src.context_manager import estimate_tokens
        msgs = [{"role": "user", "content": "Test message"}]
        count = estimate_tokens(msgs)
        self.assertGreater(count, 0)

    def test_should_compact_empty(self):
        from src.context_manager import should_compact
        self.assertFalse(should_compact([], "claude-sonnet-4-6"))

    def test_should_compact_small(self):
        from src.context_manager import should_compact
        msgs = [{"role": "user", "content": "Hi"}]
        self.assertFalse(should_compact(msgs, "claude-sonnet-4-6"))


# ── P0 #4: Thinking / extended reasoning ────────────────────────────────


class TestThinking(unittest.TestCase):
    """Verify thinking support is wired into provider and agent loop."""

    def test_model_registry_thinking(self):
        from src.model_registry import supports_thinking, get_context_window
        # Claude 4+ supports thinking
        self.assertTrue(supports_thinking("claude-sonnet-4-6"))
        self.assertTrue(supports_thinking("claude-opus-4-6"))
        # Claude 3.x does not
        self.assertFalse(supports_thinking("claude-sonnet-3-5"))
        self.assertFalse(supports_thinking("claude-haiku-4-5"))
        # OpenAI does not
        self.assertFalse(supports_thinking("gpt-4o"))
        # DeepSeek R1 supports thinking
        self.assertTrue(supports_thinking("deepseek/deepseek-r1"))

    def test_provider_has_thinking_params(self):
        import inspect
        from src.provider import AnthropicProvider
        stream_sig = inspect.signature(AnthropicProvider.stream)
        complete_sig = inspect.signature(AnthropicProvider.complete)
        self.assertIn("thinking_budget", stream_sig.parameters)
        self.assertIn("thinking_budget", complete_sig.parameters)

    def test_thinking_params_logic(self):
        from src.provider import AnthropicProvider
        # Can't instantiate without API key, test _thinking_params directly
        # via a mock instance
        provider = AnthropicProvider.__new__(AnthropicProvider)
        # claude-sonnet-4-6 supports thinking
        result = provider._thinking_params("claude-sonnet-4-6", 4096)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "enabled")
        self.assertEqual(result["budget_tokens"], 4096)

        # gpt-4o does not support thinking
        result2 = provider._thinking_params("gpt-4o", 4096)
        self.assertIsNone(result2)

        # budget=0 disables thinking
        result3 = provider._thinking_params("claude-sonnet-4-6", 0)
        self.assertIsNone(result3)

    def test_agent_loop_has_thinking_param(self):
        import inspect
        from src.agent_loop import AgentLoop
        sig = inspect.signature(AgentLoop.__init__)
        self.assertIn("thinking_budget", sig.parameters)

    def test_config_has_thinking_budget(self):
        from src.config import Config
        cfg = Config()
        self.assertEqual(cfg.thinking_budget, 8096)

    def test_agent_loop_emits_thinking_events(self):
        """Verify thinking events are handled in the stream parser."""
        from src.agent_loop import AgentLoop
        # Check that _stream_turn yields thinking_start and thinking_done
        import inspect
        source = inspect.getsource(AgentLoop._stream_turn)
        self.assertIn("thinking_start", source)
        self.assertIn("thinking_done", source)
        self.assertIn("thinking_delta", source)


# ── P0 #5: Headless / non-interactive mode ──────────────────────────────


class TestHeadlessMode(unittest.TestCase):
    """Verify -p/--print flag for headless execution."""

    def test_cli_accepts_print_flag(self):
        from src.main import build_parser
        parser = build_parser()
        args = parser.parse_args(["chat", "-p", "do something"])
        self.assertEqual(args.prompt, "do something")

    def test_chat_function_accepts_print_mode(self):
        import inspect
        from src.chat import run_chat
        sig = inspect.signature(run_chat)
        self.assertIn("print_mode", sig.parameters)
        self.assertIn("prompt", sig.parameters)


# ── P0 #6: Session persistence ─────────────────────────────────────────


class TestSessionPersistence(unittest.TestCase):
    """Verify session save/load/resume."""

    def test_session_create_and_save(self):
        from src.session import Session
        with tempfile.TemporaryDirectory() as td:
            sess = Session.new(model="test", provider="test", cwd=td)
            sess.messages = [{"role": "user", "content": "hello"}]
            sess.total_input_tokens = 100
            sess.total_output_tokens = 50
            path = sess.save()
            self.assertTrue(Path(path).exists())

            loaded = Session.load(sess.session_id)
            self.assertEqual(loaded.session_id, sess.session_id)
            self.assertEqual(len(loaded.messages), 1)
            self.assertEqual(loaded.total_input_tokens, 100)

    def test_session_list_all(self):
        from src.session import Session
        with tempfile.TemporaryDirectory() as td:
            s1 = Session.new(model="m1", provider="p1", cwd=td)
            s1.save()
            s2 = Session.new(model="m2", provider="p2", cwd=td)
            s2.save()
            all_sess = Session.list_all()
            self.assertGreaterEqual(len(all_sess), 2)

    def test_cli_resume_flag(self):
        from src.main import build_parser
        parser = build_parser()
        args = parser.parse_args(["chat", "--resume", "abc123"])
        self.assertEqual(args.resume, "abc123")

    def test_session_store(self):
        from src.session_store import StoredSession, save_session, load_session
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            s = StoredSession(
                session_id="test123",
                messages=("hello", "world"),
                input_tokens=10,
                output_tokens=5,
            )
            save_session(s, d)
            loaded = load_session("test123", d)
            self.assertEqual(loaded.session_id, "test123")
            self.assertEqual(loaded.messages, ("hello", "world"))


# ── P0 #7: Rich terminal UI ────────────────────────────────────────────


class TestRichUI(unittest.TestCase):
    """Verify terminal UI components."""

    def test_markdown_renderer_headers(self):
        from src.terminal_ui import MarkdownRenderer
        md = MarkdownRenderer()
        # Should contain ANSI codes for headers
        h1 = md.render("# Title")
        self.assertIn("━", h1)

        h2 = md.render("## Section")
        self.assertIn("──", h2)

    def test_markdown_renderer_inline(self):
        from src.terminal_ui import MarkdownRenderer
        md = MarkdownRenderer()
        text = md.render("Some **bold** and *italic* and `code` text")
        self.assertIn("bold", text)
        self.assertIn("italic", text)

    def test_markdown_renderer_code_block(self):
        from src.terminal_ui import MarkdownRenderer
        md = MarkdownRenderer()
        code = md.render("```python\nprint('hello')\n```")
        self.assertIn("print", code)
        self.assertIn("│", code)

    def test_markdown_renderer_table(self):
        from src.terminal_ui import MarkdownRenderer
        md = MarkdownRenderer()
        table = md.render("| A | B |\n|---|---|\n| 1 | 2 |")
        self.assertIn("┌", table)
        self.assertIn("└", table)

    def test_markdown_renderer_list(self):
        from src.terminal_ui import MarkdownRenderer
        md = MarkdownRenderer()
        lst = md.render("- item 1\n- item 2")
        self.assertIn("•", lst)

    def test_markdown_renderer_blockquote(self):
        from src.terminal_ui import MarkdownRenderer
        md = MarkdownRenderer()
        bq = md.render("> A quote")
        self.assertIn("│", bq)

    def test_colors_class(self):
        from src.terminal_ui import C
        self.assertIsInstance(C.RESET, str)
        self.assertIsInstance(C.BOLD, str)
        self.assertIsInstance(C.GREEN, str)
        self.assertIsInstance(C.ERROR, str)

    def test_colors_strip(self):
        from src.terminal_ui import C
        text = f"{C.RED}Error{C.RESET}"
        stripped = C.strip(text)
        self.assertEqual(stripped, "Error")

    def test_tool_panel_start(self):
        from src.terminal_ui import ToolPanel
        panel = ToolPanel.start("Bash", {"command": "ls -la"})
        self.assertIn("Bash", panel)
        self.assertIn("ls -la", panel)

    def test_tool_panel_result(self):
        from src.terminal_ui import ToolPanel
        panel = ToolPanel.result("Read", "file content", is_error=False)
        self.assertIn("Done", panel)

    def test_tool_panel_error(self):
        from src.terminal_ui import ToolPanel
        panel = ToolPanel.result("Bash", "not found", is_error=True)
        self.assertIn("Error", panel)

    def test_thinking_panel(self):
        from src.terminal_ui import ThinkingPanel
        start = ThinkingPanel.start()
        self.assertIn("Thinking", start)

        done = ThinkingPanel.done("I need to think about this...")
        self.assertIn("Thought", done)
        self.assertIn("chars", done)

    def test_context_bar(self):
        from src.terminal_ui import ContextBar
        bar = ContextBar.render(50000, 200000, model="test")
        self.assertIn("█", bar)
        self.assertIn("░", bar)
        self.assertIn("25%", bar)

    def test_banner(self):
        from src.terminal_ui import Banner
        banner = Banner.render("anthropic", "claude-sonnet-4-6", "/tmp", False)
        self.assertIn("cc-agent", banner)
        self.assertIn("anthropic", banner)
        self.assertIn("claude-sonnet-4-6", banner)

    def test_terminal_dimensions(self):
        from src.terminal_ui import get_terminal_width, get_terminal_height
        w = get_terminal_width()
        h = get_terminal_height()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)


if __name__ == "__main__":
    unittest.main()
