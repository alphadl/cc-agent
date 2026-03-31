"""Context management: CLAUDE.md loading, system prompt building, token budgeting, auto-compact."""
from __future__ import annotations

import os
from pathlib import Path

_GLOBAL_CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"
_COMPACT_THRESHOLD = 0.85


def _load_claude_md(directory: Path) -> str | None:
    md = directory / "CLAUDE.md"
    if md.is_file():
        try:
            return md.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def build_system_prompt(cwd: str | None = None) -> str:
    """Build system prompt from three-tier CLAUDE.md hierarchy.

    Tier 1: ~/.claude/CLAUDE.md   (personal global preferences)
    Tier 2: <repo-root>/CLAUDE.md (project-level instructions)
    Tier 3: <cwd>/CLAUDE.md       (subdirectory instructions)
    """
    parts: list[str] = []

    parts.append(
        "You are cc-agent, a powerful agentic AI assistant. "
        "You have access to tools: Read, Write, Edit, Glob, Grep, Bash, Git, WebFetch. "
        "When given a task, break it down, use your tools methodically, and complete it fully. "
        "Always read a file before writing or editing it. "
        "Be concise in your responses — show actions, not lengthy explanations."
    )

    if _GLOBAL_CLAUDE_MD.exists():
        content = _load_claude_md(_GLOBAL_CLAUDE_MD.parent)
        if content:
            parts.append(f"\n## User Preferences (from ~/.claude/CLAUDE.md)\n{content}")

    work_dir = Path(cwd) if cwd else Path.cwd()
    visited: set[Path] = set()
    search_dirs: list[Path] = []
    d = work_dir
    for _ in range(8):
        if d in visited:
            break
        visited.add(d)
        search_dirs.append(d)
        if (d / ".git").exists() or (d / "pyproject.toml").exists():
            break
        parent = d.parent
        if parent == d:
            break
        d = parent

    for sd in reversed(search_dirs):
        content = _load_claude_md(sd)
        if content:
            label = "Project" if sd != work_dir else f"Directory ({sd.name})"
            parts.append(f"\n## {label} Instructions (from {sd}/CLAUDE.md)\n{content}")

    return "\n\n".join(parts)


def estimate_tokens(messages: list[dict], model: str = "") -> int:
    """Count tokens accurately using the token_counter module.

    Falls back to cl100k_base BPE or rough len/4 estimate depending on
    available backends (tiktoken, Anthropic API, built-in BPE).
    """
    from .token_counter import count_messages_tokens
    try:
        return count_messages_tokens(messages, model)
    except Exception:
        # Last-resort fallback if token_counter itself fails
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) // 4
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += len(str(block.get("text", "") or block.get("content", ""))) // 4
        return total


def should_compact(messages: list[dict], model: str = "", threshold: float | None = None) -> bool:
    from .model_registry import get_context_window
    from .token_counter import count_system_tokens
    window = get_context_window(model) if model else 128_000
    token_count = estimate_tokens(messages, model)
    thresh = _COMPACT_THRESHOLD if threshold is None else threshold
    return token_count / window > thresh


async def compact_messages(
    messages: list[dict],
    client,
    model: str,
    system: str,
    keep_last: int | None = None,
) -> list[dict]:
    """Summarize older messages to free up context space."""
    if len(messages) <= 4:
        return messages

    k = 8 if keep_last is None else max(2, int(keep_last))
    to_summarize = messages[:-k]
    keep = messages[-k:]

    summary_prompt = (
        "Summarize the following conversation history concisely. "
        "Focus on: files read/modified, tasks completed, key decisions made, "
        "and any important context the assistant should remember.\n\n"
        + "\n".join(
            f"[{m['role'].upper()}]: "
            + (m["content"] if isinstance(m["content"], str)
               else str(m["content"])[:500])
            for m in to_summarize
        )
    )

    try:
        summary_text = client.complete(
            model=model,
            max_tokens=2048,
            system="You are a conversation summarizer. Be concise and factual.",
            messages=[{"role": "user", "content": summary_prompt}],
        )
    except Exception:
        summary_text = f"[{len(to_summarize)} earlier messages removed to free context space]"

    return [
        {"role": "user", "content": f"[Conversation summary]\n{summary_text}"},
        {"role": "assistant", "content": "Understood. Continuing with that context."},
    ] + keep
