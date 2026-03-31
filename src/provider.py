"""Provider abstraction: supports Anthropic, OpenRouter, and any OpenAI-compatible endpoint.

Environment variables (pick one set):

  Anthropic (default):
    ANTHROPIC_API_KEY   or  ANTHROPIC_AUTH_TOKEN
    ANTHROPIC_BASE_URL  (optional, for proxies)

  OpenRouter:
    OPENROUTER_API_KEY
    # model format: "openrouter/<provider>/<model>"
    # e.g.  openrouter/anthropic/claude-sonnet-4-5
    #        openrouter/openai/gpt-4o
    #        openrouter/google/gemini-2.0-flash

  OpenAI-compatible (any endpoint):
    OPENAI_API_KEY
    OPENAI_BASE_URL     (e.g. https://api.groq.com/openai/v1)
"""
from __future__ import annotations

import os
import sys
from typing import Iterator


# ── helpers ──────────────────────────────────────────────────────────────────

def _die(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def detect_provider(model: str) -> str:
    """Return 'openrouter', 'openai_compat', or 'anthropic'."""
    if model.startswith("openrouter/"):
        return "openrouter"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_BASE_URL"):
        return "openai_compat"
    return "anthropic"


# ── Anthropic client wrapper ──────────────────────────────────────────────────

class AnthropicProvider:
    name = "anthropic"

    def __init__(self):
        try:
            import anthropic as _anthropic
        except ImportError:
            _die("anthropic package not found — run: pip install anthropic")

        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if not api_key:
            _die("set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN")

        kwargs: dict = {"api_key": api_key}
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = _anthropic.Anthropic(**kwargs)

    def _thinking_params(self, model: str, thinking_budget: int | None = None) -> dict | None:
        """Return thinking parameters if the model supports extended thinking."""
        try:
            from .model_registry import supports_thinking
            if not supports_thinking(model):
                return None
        except Exception:
            return None

        budget = thinking_budget
        if budget is None or budget == -1:
            # Auto budget: moderate default
            budget = 8096
        if budget == 0:
            return None

        return {
            "type": "enabled",
            "budget_tokens": int(budget),
        }

    def stream(self, *, model: str, system: str, messages: list, tools: list,
               max_tokens: int = 8096, thinking_budget: int | None = None):
        """Returns a context manager that yields the raw anthropic stream.

        If thinking_budget is None and model supports thinking, defaults to 8096.
        Set thinking_budget=0 to explicitly disable thinking.
        """
        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools

        # Add thinking if supported and not explicitly disabled
        if thinking_budget is not None and thinking_budget > 0:
            thinking = self._thinking_params(model, thinking_budget)
            if thinking:
                kwargs["thinking"] = thinking
        elif thinking_budget is None:
            # Auto-enable thinking for models that support it
            thinking = self._thinking_params(model)
            if thinking:
                kwargs["thinking"] = thinking

        try:
            return self._client.messages.stream(**kwargs)
        except TypeError:
            # Older SDK versions may not accept 'thinking'
            kwargs.pop("thinking", None)
            return self._client.messages.stream(**kwargs)

    def complete(self, *, model: str, system: str, messages: list,
                 max_tokens: int = 2048, thinking_budget: int | None = None) -> str:
        """Single non-streaming call, returns text."""
        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )

        # Add thinking if supported
        if thinking_budget is not None and thinking_budget > 0:
            thinking = self._thinking_params(model, thinking_budget)
            if thinking:
                kwargs["thinking"] = thinking
        elif thinking_budget is None:
            thinking = self._thinking_params(model)
            if thinking:
                kwargs["thinking"] = thinking

        try:
            resp = self._client.messages.create(**kwargs)
        except TypeError:
            # Older SDK versions may not accept 'thinking'
            kwargs.pop("thinking", None)
            resp = self._client.messages.create(**kwargs)
        # Extract text from response (may include thinking blocks)
        text_parts = []
        for block in resp.content:
            if hasattr(block, "type") and block.type == "text":
                text_parts.append(block.text)
        return "\n".join(text_parts) if text_parts else resp.content[0].text if resp.content else ""


# ── OpenAI-compatible client wrapper (OpenRouter + any OpenAI endpoint) ───────

class OpenAICompatProvider:
    """Wraps openai SDK for OpenRouter / Groq / Together / custom endpoints."""

    name = "openai_compat"

    def __init__(self, provider: str = "openrouter"):
        try:
            from openai import OpenAI
        except ImportError:
            _die("openai package not found — run: pip install openai")

        if provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                _die("set OPENROUTER_API_KEY")
            base_url = "https://openrouter.ai/api/v1"
            self.name = "openrouter"
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                _die("set OPENAI_API_KEY")
            base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            self.name = "openai_compat"

        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def _normalize_model(self, model: str) -> str:
        """Strip 'openrouter/' prefix if present."""
        if model.startswith("openrouter/"):
            return model[len("openrouter/"):]
        return model

    def _normalize_tools(self, tools: list[dict]) -> list[dict]:
        """Convert Anthropic tool schema → OpenAI function_call schema."""
        oai_tools = []
        for t in tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            })
        return oai_tools

    def _normalize_messages(self, system: str, messages: list[dict]) -> list[dict]:
        """Convert Anthropic message format → OpenAI message format."""
        result = [{"role": "system", "content": system}]
        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                result.append({"role": role, "content": content})
                continue

            # List content (tool_use / tool_result blocks)
            if role == "assistant":
                # Find text and tool_use blocks
                text_parts = []
                tool_calls = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            import json
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"]),
                                },
                            })
                out: dict = {"role": "assistant"}
                if text_parts:
                    out["content"] = " ".join(text_parts)
                if tool_calls:
                    out["tool_calls"] = tool_calls
                result.append(out)

            elif role == "user":
                # Could be tool_result blocks
                tool_results = []
                plain_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block.get("content", ""),
                        })
                    else:
                        plain_parts.append(str(block))
                if tool_results:
                    result.extend(tool_results)
                if plain_parts:
                    result.append({"role": "user", "content": "\n".join(plain_parts)})

        return result

    def stream(self, *, model: str, system: str, messages: list, tools: list,
               max_tokens: int = 8096, thinking_budget: int | None = None):
        """Returns an OpenAIStreamAdapter context manager."""
        return _OpenAIStreamContext(
            client=self._client,
            model=self._normalize_model(model),
            messages=self._normalize_messages(system, messages),
            tools=self._normalize_tools(tools),
            max_tokens=max_tokens,
        )

    def complete(self, *, model: str, system: str, messages: list,
                 max_tokens: int = 2048, thinking_budget: int | None = None) -> str:
        oai_msgs = self._normalize_messages(system, messages)
        resp = self._client.chat.completions.create(
            model=self._normalize_model(model),
            messages=oai_msgs,
            max_tokens=max_tokens,
            stream=False,
        )
        return resp.choices[0].message.content or ""


class _OpenAIStreamContext:
    """Mimics anthropic MessageStreamManager interface for the agent loop."""

    def __init__(self, client, model, messages, tools, max_tokens):
        self._client = client
        self._model = model
        self._messages = messages
        self._tools = tools
        self._max_tokens = max_tokens
        self._stream = None
        self._adapter: "_OpenAIStreamAdapter | None" = None

    def __enter__(self) -> "_OpenAIStreamAdapter":
        kwargs: dict = dict(
            model=self._model,
            messages=self._messages,
            max_tokens=self._max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        if self._tools:
            kwargs["tools"] = self._tools
        self._stream = self._client.chat.completions.create(**kwargs)
        self._adapter = _OpenAIStreamAdapter(self._stream)
        return self._adapter

    def __exit__(self, *args):
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass


class _OpenAIStreamAdapter:
    """Wraps OpenAI streaming response to emit anthropic-style events."""

    def __init__(self, stream):
        self._stream = stream
        self._final_message = None
        self._events: list = []
        self._built = False

    def __iter__(self):
        import json

        # We'll reconstruct anthropic-style events from OpenAI chunks
        current_tool_calls: dict[int, dict] = {}
        text_accumulated = ""
        usage_data = None

        # synthetic content_block_start for text
        yield _Event("content_block_start", content_block=_Block("text", id=None, name=None))

        for chunk in self._stream:
            choice = chunk.choices[0] if chunk.choices else None
            if chunk.usage:
                usage_data = chunk.usage

            if not choice:
                continue

            delta = choice.delta

            # text delta
            if delta.content:
                text_accumulated += delta.content
                yield _Event("content_block_delta", delta=_Delta("text_delta", text=delta.content))

            # tool call deltas
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in current_tool_calls:
                        current_tool_calls[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function else "",
                            "args": "",
                        }
                        # Emit tool_use block start
                        yield _Event(
                            "content_block_stop"  # close text block first
                        )
                        yield _Event(
                            "content_block_start",
                            content_block=_Block(
                                "tool_use",
                                id=current_tool_calls[idx]["id"],
                                name=current_tool_calls[idx]["name"],
                            ),
                        )
                    if tc.function and tc.function.name and not current_tool_calls[idx]["name"]:
                        current_tool_calls[idx]["name"] = tc.function.name
                    if tc.id and not current_tool_calls[idx]["id"]:
                        current_tool_calls[idx]["id"] = tc.id
                    if tc.function and tc.function.arguments:
                        current_tool_calls[idx]["args"] += tc.function.arguments
                        yield _Event(
                            "content_block_delta",
                            delta=_Delta("input_json_delta", partial_json=tc.function.arguments),
                        )

            if choice.finish_reason:
                break

        # close open blocks
        if current_tool_calls:
            yield _Event("content_block_stop")
        else:
            yield _Event("content_block_stop")

        # store final message for get_final_message()
        content_blocks = []
        if text_accumulated:
            content_blocks.append({"type": "text", "text": text_accumulated})
        for tc in current_tool_calls.values():
            import json as _json
            try:
                parsed = _json.loads(tc["args"] or "{}")
            except Exception:
                parsed = {}
            content_blocks.append({
                "type": "tool_use",
                "id": tc["id"] or f"call_{tc['name']}",
                "name": tc["name"],
                "input": parsed,
            })

        stop_reason = "tool_use" if current_tool_calls else "end_turn"
        self._final_message = _FinalMessage(
            content=content_blocks,
            stop_reason=stop_reason,
            usage=usage_data,
        )

    def get_final_message(self):
        return self._final_message


class _Event:
    def __init__(self, type_: str, **kwargs):
        self.type = type_
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Block:
    def __init__(self, type_: str, id=None, name=None):
        self.type = type_
        self.id = id
        self.name = name


class _Delta:
    def __init__(self, type_: str, **kwargs):
        self.type = type_
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FinalMessage:
    def __init__(self, content, stop_reason, usage):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage


# ── Factory ───────────────────────────────────────────────────────────────────

def get_provider(model: str):
    """Return the right provider instance for the given model name."""
    provider = detect_provider(model)
    if provider == "openrouter":
        return OpenAICompatProvider("openrouter")
    if provider == "openai_compat":
        return OpenAICompatProvider("openai_compat")
    return AnthropicProvider()
