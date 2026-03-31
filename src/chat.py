"""claw-code: Interactive agent REPL powered by Anthropic Claude.

Features:
  - Real agentic loop: model can call Read/Write/Edit/Glob/Grep/Bash/Git/WebFetch tools
  - MCP (Model Context Protocol) for external tool servers
  - Streaming output with live tool execution display
  - Rich terminal UI: Markdown rendering, tool panels, context bar, thinking panels
  - Thinking / extended reasoning support for Anthropic models
  - Permission system with interactive approval + configurable hooks
  - Auto-compaction when context fills up
  - Three-tier CLAUDE.md context loading
  - Slash commands: /clear /compact /context /model /tools /mcp /help /exit
  - YOLO mode (--yolo) to skip all permission prompts
  - Session persistence: auto-save and resume (--resume SESSION_ID)
  - Headless mode: ./cc -p "task" for CI/pipeline integration
"""
from __future__ import annotations

import os
import readline  # noqa: F401 — enables arrow keys / history
import sys
import textwrap
from pathlib import Path
from typing import Any

# ── Rich Terminal UI ────────────────────────────────────────────────────
from .terminal_ui import (
    C, Banner, ContextBar, ThinkingPanel, ToolPanel, MarkdownRenderer, _GLYPHS,
    apply_theme, build_prompt,
    render_markdown as _render_md,
)

_DEFAULT_MODEL = "claude-sonnet-4-6"


# ── Helpers ──────────────────────────────────────────────────────────────

def _get_provider(model: str):
    from .provider import get_provider
    return get_provider(model)


def _render_markdown(text: str) -> None:
    """Render text as Markdown to the terminal."""
    try:
        print(_render_md(text))
    except Exception:
        print(text)


def _prompt_permission(tool_name: str, tool_input: dict) -> bool:
    """Ask the user interactively for tool permission. Returns True to allow."""
    g = _GLYPHS
    desc = ToolPanel._format_input(tool_name, tool_input)
    print(f"\n  {C.WARNING}{g['warn']}  Permission required:{C.RESET} {C.BOLD}{C.TOOL_NAME}{tool_name}{C.RESET}")
    print(f"   {desc}")
    print(f"   {C.DIM}[y] once  [Y] session  [n] deny  [N] deny session{C.RESET}")
    while True:
        try:
            choice = input(f"   {C.ACCENT}{g['arrow_r']}{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
        if choice in ("y", ""):
            return True
        if choice == "Y":
            return True  # caller must call grant_session separately
        if choice in ("n", "N"):
            return False
        print("   Please enter y / Y / n / N")


# ── Main REPL ───────────────────────────────────────────────────────────

def run_chat(
    model: str | None = None,
    system: str | None = None,
    yolo: bool | None = None,
    cwd: str | None = None,
    print_mode: bool = False,
    prompt: str | None = None,
    resume: str | None = None,
) -> None:
    from .agent_loop import AgentLoop
    from .config import load_config, init_user_config
    from .context_manager import build_system_prompt, estimate_tokens
    from .permission_system import PermissionSystem
    from .session import Session
    from .model_registry import get_context_window
    from .mcp_tools import get_mcp_tools
    from .custom_tools import load_tool_specs

    # ── Load config ─────────────────────────────────────────────────────
    cfg = load_config(cwd)
    if model is not None:
        cfg.model = model
    if yolo is not None:
        cfg.yolo = yolo

    init_user_config()

    apply_theme(getattr(cfg, "ui_theme", "dark"))

    client = _get_provider(cfg.model)
    current_model = cfg.model
    context_window = get_context_window(cfg.model)

    # Build system prompt
    sys_prompt = system or build_system_prompt(cwd)

    # ── Custom tools + MCP integration ──────────────────────────────────
    custom_tool_classes: list[type] = []
    if getattr(cfg, "extra_tools", None):
        try:
            custom_tool_classes = load_tool_specs(cfg.extra_tools)
        except Exception as e:
            print(f"  {C.ERROR}Custom tool load failed:{C.RESET} {e}")
            custom_tool_classes = []

    mcp_tool_classes, mcp_manager = get_mcp_tools(cwd)

    # ── Session ─────────────────────────────────────────────────────────
    if resume:
        try:
            sess = Session.load(resume)
            messages: list[dict] = sess.messages
            total_in = sess.total_input_tokens
            total_out = sess.total_output_tokens
            if not print_mode:
                print(f"  {C.SUCCESS}{_GLYPHS['check']} Resumed session {sess.session_id}{C.RESET}  ({len(messages)} messages)\n")
        except FileNotFoundError:
            print(f"  {C.ERROR}Session not found: {resume}{C.RESET}", file=sys.stderr)
            sys.exit(1)
    else:
        sess = Session.new(model=current_model, provider=client.name, cwd=str(Path(cwd or ".").resolve()))
        messages = sess.messages
        total_in = 0
        total_out = 0

    # ── Permissions ─────────────────────────────────────────────────────
    perms = PermissionSystem(
        auto_approve_reads=cfg.auto_approve_reads,
        auto_approve_writes=cfg.auto_approve_writes,
        auto_approve_execute=cfg.auto_approve_execute,
        yolo_mode=cfg.yolo,
        deny_tools=cfg.deny_tools,
        allow_tools=cfg.allow_tools,
        deny_bash_substrings=cfg.deny_bash_substrings,
        allow_bash_prefixes=cfg.allow_bash_prefixes,
        deny_write_path_prefixes=cfg.deny_write_path_prefixes,
        allow_write_path_prefixes=cfg.allow_write_path_prefixes,
    )

    # ── Banner ──────────────────────────────────────────────────────────
    if not print_mode and getattr(cfg, "ui_show_banner", True):
        mcp_info = ""
        if mcp_tool_classes:
            mcp_info = f"{C.SUCCESS}MCP: {len(mcp_tool_classes)} tools from {len(mcp_manager._clients)} server(s){C.RESET}"
        print(Banner.render(
            provider=client.name,
            model=current_model,
            cwd=str(Path(cwd or ".").resolve()),
            yolo=cfg.yolo,
            context_window=context_window,
            mcp_status=mcp_info,
        ))
        print()

    # ── Callbacks ───────────────────────────────────────────────────────
    def _permission_callback(tool_name: str, tool_input: dict) -> bool:
        if print_mode:
            return True  # headless: auto-approve all
        allowed = _prompt_permission(tool_name, tool_input)
        if allowed:
            perms.grant_session(tool_name)
        return allowed

    def _save_session() -> None:
        sess.messages = messages
        sess.total_input_tokens = total_in
        sess.total_output_tokens = total_out
        sess.model = current_model
        sess.provider = client.name
        sess.save()

    # ── Agent turn ──────────────────────────────────────────────────────
    def _run_agent_turn(user_input: str) -> None:
        nonlocal total_in, total_out, messages
        messages.append({"role": "user", "content": user_input})

        # Determine thinking budget: from config, 0=disable, None=auto
        think_budget = cfg.thinking_budget if cfg.thinking_budget >= 0 else None

        loop = AgentLoop(
            client=client,
            model=current_model,
            system=sys_prompt,
            permissions=perms,
            extra_tools=(custom_tool_classes + mcp_tool_classes) if (custom_tool_classes or mcp_tool_classes) else None,
            permission_callback=_permission_callback,
            parallel_tools=cfg.parallel_tools,
            max_tool_iterations=cfg.max_tool_iterations,
            max_retries=cfg.max_retries,
            retry_delays=cfg.retry_delays,
            thinking_budget=think_budget,
        )
        loop._messages = messages
        _streaming_buf = []

        try:
            for event in loop.run(messages):
                etype = event.get("type")

                # ── Text streaming ───────────────────────────────────────
                if etype == "text_delta":
                    _streaming_buf.append(event["text"])
                    if not print_mode and cfg.stream_dots:
                        print(".", end="", flush=True)

                elif etype == "text_done":
                    full_text = "".join(_streaming_buf)
                    _streaming_buf.clear()
                    if not print_mode and cfg.stream_dots:
                        print("\r\033[K", end="", flush=True)  # clear dots
                    if cfg.render_markdown:
                        _render_markdown(full_text)
                    else:
                        print(full_text)

                # ── Thinking panels ──────────────────────────────────────
                elif etype == "thinking_start":
                    if not print_mode:
                        print(ThinkingPanel.start(), end="", flush=True)

                elif etype == "thinking_delta":
                    if not print_mode:
                        print(".", end="", flush=True)

                elif etype == "thinking_done":
                    if not print_mode:
                        print(ThinkingPanel.done(event.get("thinking", "")))

                # ── Usage tracking ───────────────────────────────────────
                elif etype == "usage":
                    u = event.get("usage")
                    if u:
                        total_in += getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", 0) or 0
                        total_out += getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", 0) or 0

                elif etype == "turn_end":
                    pass  # usage already counted

                # ── Tool panels ──────────────────────────────────────────
                elif etype == "tool_start":
                    print(ToolPanel.start(event["name"], event["input"]))

                elif etype == "tool_result":
                    print(ToolPanel.result(
                        event["name"], event["result"],
                        event.get("is_error", False), cfg.tool_result_preview_chars,
                    ))

                # ── Status events ────────────────────────────────────────
                elif etype == "retry":
                    print(f"\n  {C.WARNING}{_GLYPHS['arrow_r']} Retry {event['attempt']}/{event['max']} "
                          f"in {event['delay']}s: {event['error']}{C.RESET}")

                elif etype == "permission_deny":
                    print(f"\n  {C.ERROR}{_GLYPHS['cross']} Tool denied{C.RESET}: {event.get('reason', '')}")

                elif etype == "compact":
                    print(f"\n  {C.DIM}{_GLYPHS['save']} {event['message']}{C.RESET}")

                elif etype == "error":
                    print(f"\n{C.ERROR}{_GLYPHS['cross']} Error: {event['message']}{C.RESET}")

        except KeyboardInterrupt:
            print(f"\n  {C.DIM}[interrupted]{C.RESET}")
            if messages and messages[-1].get("role") == "user":
                messages.pop()
            return

        messages = loop._messages

        # ── Post-turn status bar ────────────────────────────────────────
        if not print_mode and cfg.show_cost and getattr(cfg, "ui_show_hud", True):
            est = estimate_tokens(messages, current_model)
            bar = ContextBar.render(est, context_window, model=current_model,
                                    input_tokens=total_in, output_tokens=total_out,
                                    session_id=sess.session_id, message_count=len(messages),
                                    yolo=cfg.yolo)
            print(f"\n  {bar}")
            cost_per_mtok = 0.003
            cost_usd = (total_in + total_out) / 1_000_000 * cost_per_mtok
            print(f"  {C.DIM}~${cost_usd:.4f}{C.RESET}\n")

        if cfg.auto_save_session:
            _save_session()

    # ── Headless mode ───────────────────────────────────────────────────
    if print_mode and prompt:
        try:
            _run_agent_turn(prompt)
        finally:
            mcp_manager.close_all()
        return

    # ── Interactive REPL ────────────────────────────────────────────────
    while True:
        try:
            prompt_str = build_prompt(cwd=str(Path(cwd or ".").resolve()), model=current_model, yolo=cfg.yolo)
            user_input = input(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C.DIM}Bye!{C.RESET}")
            _save_session()
            mcp_manager.close_all()
            break

        if not user_input:
            continue

        # ── Slash commands ──────────────────────────────────────────────
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()

            if cmd in ("/exit", "/quit", "/q"):
                print(f"{C.DIM}Bye!{C.RESET}")
                break

            elif cmd == "/clear":
                messages.clear()
                total_in = total_out = 0
                print(f"  {C.DIM}[conversation cleared]{C.RESET}")
                continue

            elif cmd == "/compact":
                if not messages:
                    print(f"  {C.DIM}[nothing to compact]{C.RESET}")
                    continue
                import asyncio
                print(f"  {C.DIM}Compacting…{C.RESET}", end="", flush=True)
                try:
                    from .context_manager import compact_messages
                    messages = asyncio.run(compact_messages(messages, client, current_model, sys_prompt))
                    print(f"\r  {C.SUCCESS}✓ Compacted to {len(messages)} messages{C.RESET}     ")
                except Exception as e:
                    print(f"\r  {C.ERROR}Compact failed: {e}{C.RESET}")
                continue

            elif cmd == "/context":
                est = estimate_tokens(messages, current_model)
                bar = ContextBar.render(est, context_window, model=current_model,
                                        input_tokens=total_in, output_tokens=total_out,
                                        session_id=sess.session_id, message_count=len(messages),
                                        yolo=cfg.yolo)
                print(f"  {bar}")
                continue

            elif cmd == "/model":
                if len(parts) < 2:
                    print(f"  Current model: {C.BOLD}{current_model}{C.RESET}")
                else:
                    current_model = parts[1].strip()
                    print(f"  Switched to: {C.BOLD}{current_model}{C.RESET}")
                continue

            elif cmd == "/tools":
                from .tools_impl import ALL_TOOLS
                print(f"  {C.BOLD}Available tools:{C.RESET}")
                for t in ALL_TOOLS:
                    print(f"    {C.ACCENT}{t.name}{C.RESET}  —  {t.description[:70]}…")
                if mcp_tool_classes:
                    print(f"\n  {C.BOLD}MCP tools:{C.RESET}")
                    for t in mcp_manager.all_tools[:20]:
                        print(f"    {C.ACCENT}{t.name}{C.RESET}  —  {t.description[:60]}")
                    if len(mcp_manager.all_tools) > 20:
                        print(f"    {C.DIM}... and {len(mcp_manager.all_tools) - 20} more{C.RESET}")
                continue

            elif cmd == "/yolo":
                perms.yolo_mode = not perms.yolo_mode
                cfg.yolo = perms.yolo_mode
                state = f"{C.WARNING}{_GLYPHS['bolt']} ON{C.RESET}" if perms.yolo_mode else f"{C.SUCCESS}OFF{C.RESET}"
                print(f"  YOLO mode: {state}")
                continue

            elif cmd == "/config":
                import json as _json
                from .config import _USER_CONFIG_PATH
                d = cfg.to_dict()
                print(f"\n  {C.BOLD}Current config:{C.RESET}  (source: {C.DIM}{_USER_CONFIG_PATH}{C.RESET})")
                for k, v in d.items():
                    print(f"    {C.ACCENT}{k}{C.RESET} = {C.BOLD}{v!r}{C.RESET}")
                print(f"\n  {C.DIM}Edit {_USER_CONFIG_PATH} or set CC_AGENT_<KEY>=value to override.{C.RESET}\n")
                continue

            elif cmd == "/history":
                if not messages:
                    print(f"  {C.DIM}[no history]{C.RESET}")
                else:
                    for i, m in enumerate(messages):
                        role = m["role"].upper()
                        content = m.get("content", "")
                        if isinstance(content, list):
                            preview = str(content)[:100]
                        else:
                            preview = str(content)[:100].replace("\n", " ")
                        color = C.ACCENT if role == "USER" else C.SUCCESS
                        print(f"  {C.DIM}[{i}]{C.RESET} {color}{role}{C.RESET}: {preview}")
                continue

            elif cmd == "/help":
                print(
                    f"\n  {C.BOLD}Slash commands:{C.RESET}\n"
                    f"    {C.ACCENT}/clear{C.RESET}        clear conversation history\n"
                    f"    {C.ACCENT}/compact{C.RESET}      summarize old messages to free context\n"
                    f"    {C.ACCENT}/context{C.RESET}      show token usage and context window bar\n"
                    f"    {C.ACCENT}/model <id>{C.RESET}   switch model\n"
                    f"    {C.ACCENT}/tools{C.RESET}        list available agent tools\n"
                    f"    {C.ACCENT}/mcp{C.RESET}          show MCP server status and tools\n"
                    f"    {C.ACCENT}/rename <title>{C.RESET} name current session\n"
                    f"    {C.ACCENT}/export [path]{C.RESET} export current session to Markdown\n"
                    f"    {C.ACCENT}/delete <id>{C.RESET}  delete a saved session\n"
                    f"    {C.ACCENT}/yolo{C.RESET}         toggle auto-approve for all tools\n"
                    f"    {C.ACCENT}/config{C.RESET}       show current config and config file path\n"
                    f"    {C.ACCENT}/history{C.RESET}      show conversation history\n"
                    f"    {C.ACCENT}/sessions{C.RESET}     list saved sessions\n"
                    f"    {C.ACCENT}/exit{C.RESET}         quit\n\n"
                    f"  {C.BOLD}Tips:{C.RESET}\n"
                    f"    • The agent can read, edit, and create files in your project.\n"
                    f"    • Reads and writes are auto-approved; Bash still asks.\n"
                    f"    • Use {C.ACCENT}/yolo{C.RESET} to skip all permission prompts.\n"
                    f"    • Add a {C.BOLD}CLAUDE.md{C.RESET} to your project for custom instructions.\n"
                    f"    • Resume a session: {C.ACCENT}./cc --resume <session-id>{C.RESET}\n"
                    f"    • Config file: {C.DIM}~/.cc-agent/config.json{C.RESET}\n"
                )
                continue

            elif cmd == "/sessions":
                from .session import Session as _Sess
                all_sess = _Sess.list_all()
                if not all_sess:
                    print(f"  {C.DIM}No saved sessions{C.RESET}")
                else:
                    print(f"  {C.BOLD}Saved sessions:{C.RESET}")
                    for s in all_sess[:10]:
                        marker = f"{C.SUCCESS}← current{C.RESET}" if s.session_id == sess.session_id else ""
                        title = f"  {C.DIM}{s.title}{C.RESET}" if getattr(s, "title", "") else ""
                        print(f"    {C.ACCENT}{s.session_id}{C.RESET}  "
                              f"{C.DIM}{s.updated_at[:16]}  {s.model}  {len(s.messages)} msgs{C.RESET}{title}  {marker}")
                continue

            elif cmd == "/mcp":
                if not mcp_manager.server_configs:
                    print(f"  {C.DIM}No MCP servers configured.{C.RESET}")
                    print(f"  {C.DIM}Create ~/.cc-agent/mcp_servers.json or .mcp.json to add servers.{C.RESET}")
                else:
                    print(f"  {C.BOLD}MCP Servers:{C.RESET}")
                    print(mcp_manager.status())
                    if mcp_manager.all_tools:
                        print(f"\n  {C.BOLD}MCP Tools ({len(mcp_manager.all_tools)}):{C.RESET}")
                        for t in mcp_manager.all_tools[:20]:
                            print(f"    {C.ACCENT}{t.name}{C.RESET}  —  {t.description[:60]}")
                        if len(mcp_manager.all_tools) > 20:
                            print(f"    {C.DIM}... and {len(mcp_manager.all_tools) - 20} more{C.RESET}")
                continue

            elif cmd == "/rename":
                if len(parts) < 2 or not parts[1].strip():
                    print(f"  {C.DIM}Usage: /rename <title>{C.RESET}")
                    continue
                sess.title = parts[1].strip()
                _save_session()
                print(f"  {C.SUCCESS}✓ Renamed session to:{C.RESET} {sess.title}")
                continue

            elif cmd == "/export":
                from .session import Session as _Sess
                export_path = parts[1].strip() if len(parts) > 1 else f"{sess.session_id}.md"
                try:
                    md = sess.export_markdown()
                    Path(export_path).write_text(md, encoding="utf-8")
                    print(f"  {C.SUCCESS}✓ Exported to:{C.RESET} {export_path}")
                except Exception as e:
                    print(f"  {C.ERROR}Export failed:{C.RESET} {e}")
                continue

            elif cmd == "/delete":
                from .session import Session as _Sess
                target = parts[1].strip() if len(parts) > 1 else ""
                if not target:
                    print(f"  {C.DIM}Usage: /delete <session-id>{C.RESET}")
                    continue
                if target == sess.session_id:
                    print(f"  {C.ERROR}Refusing to delete the current session.{C.RESET}")
                    continue
                ok = _Sess.delete(target)
                if ok:
                    print(f"  {C.SUCCESS}✓ Deleted session:{C.RESET} {target}")
                else:
                    print(f"  {C.ERROR}Session not found:{C.RESET} {target}")
                continue

            else:
                print(f"  Unknown command: {cmd}  (type /help)")
                continue

        # ── Agent turn ──────────────────────────────────────────────────
        _run_agent_turn(user_input)
