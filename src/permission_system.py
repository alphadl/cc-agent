"""Permission and hook system for the agent harness.

PreToolUse hooks run before a tool executes and can block it.
PostToolUse hooks run after execution (e.g. auto-format, auto-commit).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .tools_impl.base import ToolResult


class PermissionLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


# Which tools are in which tier
_TOOL_PERMISSION_LEVEL: dict[str, PermissionLevel] = {
    "Read": PermissionLevel.READ,
    "ReadMany": PermissionLevel.READ,
    "Glob": PermissionLevel.READ,
    "Grep": PermissionLevel.READ,
    "Git": PermissionLevel.READ,
    "WebFetch": PermissionLevel.READ,
    "Write": PermissionLevel.WRITE,
    "Edit": PermissionLevel.WRITE,
    "Patch": PermissionLevel.WRITE,
    "Bash": PermissionLevel.EXECUTE,
}

_SAFE_READONLY_BASH = frozenset([
    "git log", "git status", "git diff", "git show", "git branch",
    "ls", "pwd", "cat", "echo", "which", "python --version",
    "node --version", "uname", "date",
])


@dataclass
class HookResult:
    allow: bool = True
    reason: str = ""
    modified_input: dict | None = None


PreHookFn = Callable[[str, dict], HookResult]
PostHookFn = Callable[[str, dict, ToolResult], None]


class PermissionSystem:
    """Manages tool permission approval and hook pipelines."""

    def __init__(
        self,
        auto_approve_reads: bool = True,
        auto_approve_writes: bool = False,
        auto_approve_execute: bool = False,
        yolo_mode: bool = False,
        deny_tools: list[str] | None = None,
        allow_tools: list[str] | None = None,
        deny_bash_substrings: list[str] | None = None,
        allow_bash_prefixes: list[str] | None = None,
    ):
        self.auto_approve_reads = auto_approve_reads
        self.auto_approve_writes = auto_approve_writes
        self.auto_approve_execute = auto_approve_execute
        self.yolo_mode = yolo_mode  # approve everything without prompting

        self._deny_tools_cfg = {t.strip() for t in (deny_tools or []) if t and t.strip()}
        self._allow_tools_cfg = {t.strip() for t in (allow_tools or []) if t and t.strip()}
        self._deny_bash_substrings_cfg = [s.lower() for s in (deny_bash_substrings or []) if s]
        self._allow_bash_prefixes_cfg = [s for s in (allow_bash_prefixes or []) if s]

        # Persistent approvals granted during this session
        self._session_allowed: set[str] = set()
        self._always_deny: set[str] = set()

        # Hook pipelines
        self._pre_hooks: list[PreHookFn] = []
        self._post_hooks: list[PostHookFn] = []

        # Shell hooks from env (like Claude Code hooks system)
        self._shell_pre_hook = os.environ.get("CLAW_PRE_TOOL_HOOK")
        self._shell_post_hook = os.environ.get("CLAW_POST_TOOL_HOOK")

    # ─── Hook registration ───────────────────────────────────────────────────

    def add_pre_hook(self, fn: PreHookFn) -> None:
        self._pre_hooks.append(fn)

    def add_post_hook(self, fn: PostHookFn) -> None:
        self._post_hooks.append(fn)

    # ─── Permission check ────────────────────────────────────────────────────

    def check(self, tool_name: str, tool_input: dict) -> HookResult:
        """Run pre-hooks then permission check. Returns HookResult."""
        if tool_name in self._deny_tools_cfg:
            return HookResult(allow=False, reason=f"{tool_name} denied by config")

        if tool_name in self._allow_tools_cfg:
            return HookResult(allow=True)

        if tool_name in self._always_deny:
            return HookResult(allow=False, reason=f"{tool_name} is denied for this session")

        # Run registered pre-hooks
        for hook in self._pre_hooks:
            result = hook(tool_name, tool_input)
            if not result.allow:
                return result

        # Shell pre-hook (CLAW_PRE_TOOL_HOOK env var)
        if self._shell_pre_hook:
            hr = self._run_shell_hook(self._shell_pre_hook, tool_name, tool_input)
            if not hr.allow:
                return hr

        # Already approved for session
        if tool_name in self._session_allowed:
            return HookResult(allow=True)

        # YOLO mode — skip all prompts
        if self.yolo_mode:
            return HookResult(allow=True)

        level = _TOOL_PERMISSION_LEVEL.get(tool_name, PermissionLevel.EXECUTE)

        if level == PermissionLevel.READ and self.auto_approve_reads:
            return HookResult(allow=True)
        if level == PermissionLevel.WRITE and self.auto_approve_writes:
            return HookResult(allow=True)
        if level == PermissionLevel.EXECUTE and self.auto_approve_execute:
            # Heuristic: approve obviously safe bash commands
            cmd = tool_input.get("command", "")
            if any(cmd.startswith(safe) for safe in _SAFE_READONLY_BASH):
                return HookResult(allow=True)
            if any(cmd.startswith(prefix) for prefix in self._allow_bash_prefixes_cfg):
                return HookResult(allow=True)

        # Enforce bash denylist regardless of other toggles (except YOLO above)
        if tool_name == "Bash":
            cmd = (tool_input.get("command", "") or "").strip()
            lower = cmd.lower()
            for sub in self._deny_bash_substrings_cfg:
                if sub and sub in lower:
                    return HookResult(allow=False, reason=f"bash command denied by config: contains '{sub}'")

        # Needs interactive approval — caller must prompt user
        return HookResult(allow=False, reason="requires_approval")

    def run_post_hooks(self, tool_name: str, tool_input: dict, result: ToolResult) -> None:
        for hook in self._post_hooks:
            hook(tool_name, tool_input, result)
        if self._shell_post_hook:
            self._run_shell_hook(self._shell_post_hook, tool_name, tool_input)

    def grant_session(self, tool_name: str) -> None:
        self._session_allowed.add(tool_name)

    def deny_session(self, tool_name: str) -> None:
        self._always_deny.add(tool_name)

    def _run_shell_hook(self, hook_cmd: str, tool_name: str, tool_input: dict) -> HookResult:
        import json
        env = os.environ.copy()
        env["CLAW_TOOL_NAME"] = tool_name
        env["CLAW_TOOL_INPUT"] = json.dumps(tool_input)
        try:
            r = subprocess.run(hook_cmd, shell=True, capture_output=True, text=True, env=env, timeout=10)
            if r.returncode != 0:
                return HookResult(allow=False, reason=r.stdout.strip() or r.stderr.strip() or "hook blocked")
        except Exception:
            pass
        return HookResult(allow=True)
