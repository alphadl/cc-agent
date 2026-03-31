"""The core agentic loop: sends messages, executes tool calls, loops until done."""
from __future__ import annotations

import json
import time
import concurrent.futures
from typing import Any, Callable, Generator

from .context_manager import should_compact, compact_messages
from .permission_system import PermissionSystem
from .tools_impl import ALL_TOOLS
from .tools_impl.base import Tool, ToolResult

_MAX_TOOL_ITERATIONS = 50
_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 3, 8]  # seconds between retries


def _build_tools_schema(tools: list[type[Tool]]) -> list[dict]:
    return [t.schema() for t in tools]


class AgentLoop:
    """The main tool-use loop.

    Events yielded (dicts with 'type' key):
        text_delta      — streaming text from the model
        text_done       — model finished one text block
        tool_start      — about to execute a tool {name, input}
        tool_result     — tool finished {name, result, is_error}
        permission_ask  — need user to approve a tool {tool_name, tool_input}
        permission_deny — tool was denied {tool_name, reason}
        turn_end        — model's turn complete (stop_reason=end_turn)
        compact         — context was compacted
        error           — something went wrong {message}
        retry           — retrying after error {attempt, max, delay}
    """

    def __init__(
        self,
        client,
        model: str,
        system: str,
        permissions: PermissionSystem | None = None,
        extra_tools: list[type[Tool]] | None = None,
        permission_callback: Callable[[str, dict], bool] | None = None,
        parallel_tools: bool = True,
        max_tool_iterations: int = _MAX_TOOL_ITERATIONS,
        max_retries: int = _MAX_RETRIES,
        retry_delays: list[float] | None = None,
        thinking_budget: int | None = None,
    ):
        self.client = client
        self.model = model
        self.system = system
        self.permissions = permissions or PermissionSystem(auto_approve_reads=True)
        self.tools: list[type[Tool]] = list(ALL_TOOLS) + (extra_tools or [])
        self._tool_map: dict[str, type[Tool]] = {t.name: t for t in self.tools}
        self._tool_instances: dict[str, Tool] = {t.name: t() for t in self.tools}
        self._permission_callback = permission_callback
        self._messages: list[dict] = []
        self._parallel_tools = parallel_tools
        self._max_tool_iterations = max_tool_iterations
        self._max_retries = max_retries
        self._retry_delays = retry_delays if retry_delays is not None else list(_RETRY_DELAYS)
        self._thinking_budget = thinking_budget

    # ── helpers ──────────────────────────────────────────────────────────────

    def _compact_sync(self) -> None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    f = pool.submit(asyncio.run,
                                    compact_messages(self._messages, self.client, self.model, self.system))
                    self._messages = f.result(timeout=30)
            else:
                self._messages = loop.run_until_complete(
                    compact_messages(self._messages, self.client, self.model, self.system))
        except Exception:
            pass

    def _execute_one_tool(self, tc: dict) -> tuple[dict, ToolResult]:
        """Run a single tool call, return (tc, result)."""
        instance = self._tool_instances.get(tc["name"])
        if instance is None:
            return tc, ToolResult(f"Unknown tool: {tc['name']}", is_error=True)
        try:
            return tc, instance.run(**tc["input"])
        except Exception as e:
            return tc, ToolResult(f"Tool error: {e}", is_error=True)

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self, messages: list[dict]) -> Generator[dict, None, None]:
        self._messages = messages
        iterations = 0

        while iterations < self._max_tool_iterations:
            iterations += 1

            # Auto-compact if context is filling up
            if should_compact(self._messages, self.model):
                yield {"type": "compact", "message": "Compacting conversation history…"}
                self._compact_sync()

            # Stream next model response (with retry on transient errors)
            tool_calls: list[dict] = []
            full_text = ""
            stop_reason = "end_turn"
            usage = None

            for attempt in range(self._max_retries):
                try:
                    tool_calls, full_text, stop_reason, usage = yield from self._stream_turn()
                    break  # success
                except KeyboardInterrupt:
                    yield {"type": "error", "message": "[Interrupted]"}
                    return
                except Exception as e:
                    if attempt < self._max_retries - 1:
                        delay = self._retry_delays[attempt] if attempt < len(self._retry_delays) else self._retry_delays[-1]
                        yield {"type": "retry", "attempt": attempt + 1, "max": self._max_retries, "delay": delay, "error": str(e)}
                        time.sleep(delay)
                    else:
                        yield {"type": "error", "message": f"API error after {self._max_retries} attempts: {e}"}
                        return

            if full_text:
                yield {"type": "text_done", "text": full_text}

            # Always emit usage after each model call
            if usage:
                yield {"type": "usage", "usage": usage}
            if stop_reason == "end_turn" or not tool_calls:
                yield {"type": "turn_end", "usage": usage}
                return

            # ── Execute tool calls (parallel where possible) ──────────────────

            # First: permission checks (must be serial for interactive prompts)
            approved: list[dict] = []
            denied_results: list[dict] = []

            for tc in tool_calls:
                tool_name = tc["name"]
                tool_input = tc["input"]
                tool_id = tc["id"]

                perm = self.permissions.check(tool_name, tool_input)
                if not perm.allow:
                    if perm.reason == "requires_approval":
                        yield {"type": "permission_ask", "tool_name": tool_name, "tool_input": tool_input}
                        allowed = self._permission_callback(tool_name, tool_input) if self._permission_callback else False
                        if allowed:
                            approved.append(tc)
                            continue
                        yield {"type": "permission_deny", "tool_name": tool_name, "reason": "User denied"}
                    else:
                        yield {"type": "permission_deny", "tool_name": tool_name, "reason": perm.reason}
                    denied_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": "Tool execution was denied.",
                        "is_error": True,
                    })
                else:
                    approved.append(tc)

            # Signal starts for all approved tools
            for tc in approved:
                yield {"type": "tool_start", "name": tc["name"], "input": tc["input"]}

            # Run approved tools — parallel if enabled and multiple
            tool_results: list[dict] = list(denied_results)
            if self._parallel_tools and len(approved) > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(approved)) as pool:
                    futures = {pool.submit(self._execute_one_tool, tc): tc for tc in approved}
                    for future in concurrent.futures.as_completed(futures):
                        tc, result = future.result()
                        self.permissions.run_post_hooks(tc["name"], tc["input"], result)
                        yield {"type": "tool_result", "name": tc["name"], "result": result.content, "is_error": result.is_error}
                        tool_results.append(result.to_api(tc["id"]))
            else:
                for tc in approved:
                    _, result = self._execute_one_tool(tc)
                    self.permissions.run_post_hooks(tc["name"], tc["input"], result)
                    yield {"type": "tool_result", "name": tc["name"], "result": result.content, "is_error": result.is_error}
                    tool_results.append(result.to_api(tc["id"]))

            if tool_results:
                self._messages.append({"role": "user", "content": tool_results})

    def _stream_turn(self):
        """Stream one model turn. Returns (tool_calls, full_text, stop_reason, usage).
        This is a generator that also yields text_delta, thinking events."""
        tool_calls: list[dict] = []
        current_tool_use: dict | None = None
        current_thinking: dict | None = None
        full_text = ""
        thinking_text = ""
        stop_reason = "end_turn"
        usage = None

        with self.client.stream(
            model=self.model,
            max_tokens=8096,
            system=self.system,
            tools=_build_tools_schema(self.tools),
            messages=self._messages,
            thinking_budget=self._thinking_budget,
        ) as stream:
            for event in stream:
                etype = getattr(event, "type", "")

                if etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block and getattr(block, "type", "") == "tool_use":
                        current_tool_use = {"id": block.id, "name": block.name, "input_raw": ""}
                    elif block and getattr(block, "type", "") == "thinking":
                        current_thinking = {"text": ""}
                        yield {"type": "thinking_start"}

                elif etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        dtype = getattr(delta, "type", "")
                        if dtype == "text_delta":
                            text = getattr(delta, "text", "")
                            full_text += text
                            yield {"type": "text_delta", "text": text}
                        elif dtype == "input_json_delta" and current_tool_use:
                            current_tool_use["input_raw"] += getattr(delta, "partial_json", "")
                        elif dtype == "thinking_delta" and current_thinking:
                            t_text = getattr(delta, "thinking", "")
                            current_thinking["text"] += t_text
                            thinking_text += t_text
                            yield {"type": "thinking_delta", "thinking": t_text}

                elif etype == "content_block_stop":
                    if current_tool_use:
                        try:
                            parsed = json.loads(current_tool_use["input_raw"] or "{}")
                        except json.JSONDecodeError:
                            parsed = {}
                        current_tool_use["input"] = parsed
                        tool_calls.append(current_tool_use)
                        current_tool_use = None
                    elif current_thinking:
                        yield {"type": "thinking_done", "thinking": current_thinking["text"]}
                        current_thinking = None

            final = stream.get_final_message()
            stop_reason = final.stop_reason if final else "end_turn"
            usage = getattr(final, "usage", None)

        # Build assistant message
        if tool_calls:
            content: list = []
            if full_text:
                content.append({"type": "text", "text": full_text})
            for tc in tool_calls:
                content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
            if self._messages and self._messages[-1].get("role") == "assistant":
                self._messages[-1] = {"role": "assistant", "content": content}
            else:
                self._messages.append({"role": "assistant", "content": content})
        elif full_text:
            if self._messages and self._messages[-1].get("role") == "assistant":
                self._messages[-1] = {"role": "assistant", "content": full_text}
            else:
                self._messages.append({"role": "assistant", "content": full_text})

        return tool_calls, full_text, stop_reason, usage
