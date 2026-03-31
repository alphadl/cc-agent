"""Git tool — structured git operations with clean output."""
from __future__ import annotations

import subprocess
from typing import Any

from .base import Tool, ToolResult

_TIMEOUT = 30
_MAX_OUTPUT = 20_000


def _git(args: list[str], cwd: str | None = None) -> tuple[str, bool]:
    """Run a git command, return (output, is_error)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True,
            timeout=_TIMEOUT, cwd=cwd,
        )
        out = result.stdout + (("\n" + result.stderr) if result.stderr.strip() else "")
        out = out[:_MAX_OUTPUT]
        return out.strip(), result.returncode != 0
    except subprocess.TimeoutExpired:
        return "git command timed out", True
    except FileNotFoundError:
        return "git not found in PATH", True
    except Exception as e:
        return str(e), True


class GitTool(Tool):
    name = "Git"
    description = (
        "Run safe, read-only git operations: status, diff, log, branch, show. "
        "Use Bash for write operations (commit, push, checkout). "
        "Returns structured, readable output."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["status", "diff", "log", "branch", "show", "stash-list"],
                "description": "The git subcommand to run.",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Extra arguments to pass (e.g. ['--stat'] for diff --stat, ['--oneline', '-20'] for log).",
            },
            "path": {
                "type": "string",
                "description": "Working directory (defaults to cwd).",
            },
        },
        "required": ["command"],
    }
    requires_permission = "read"

    # Safe commands only — write ops go through Bash with permission checks
    _SAFE = {"status", "diff", "log", "branch", "show", "stash-list"}

    def run(self, command: str, args: list[str] | None = None, path: str | None = None, **_: Any) -> ToolResult:
        if command not in self._SAFE:
            return ToolResult(f"Command '{command}' not allowed. Use Bash for write operations.", is_error=True)

        git_args = [command] + (args or [])

        # Sensible defaults per command
        if command == "log" and not args:
            git_args = ["log", "--oneline", "--graph", "--decorate", "-20"]
        elif command == "diff" and not args:
            git_args = ["diff", "--stat"]
        elif command == "branch" and not args:
            git_args = ["branch", "-vv"]
        elif command == "stash-list":
            git_args = ["stash", "list"]

        output, is_error = _git(git_args, cwd=path)
        return ToolResult(output or "(no output)", is_error=is_error)
