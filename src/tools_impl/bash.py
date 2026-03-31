"""Bash tool — execute shell commands with timeout and safety checks."""
from __future__ import annotations

import os
import shlex
import subprocess
from typing import Any

from .base import Tool, ToolResult

_DEFAULT_TIMEOUT = 120  # seconds
_MAX_OUTPUT = 30_000   # chars

# Patterns that always require explicit permission (destructive)
_DANGER_PATTERNS = [
    "rm -rf", "rm -r", "dd if=", "mkfs", ":(){:|:&};:",
    "chmod 777", "> /dev/", "format ", "del /f", "deltree",
]


class BashTool(Tool):
    name = "Bash"
    description = (
        "Execute a shell command. Commands run in the current working directory. "
        "Timeout defaults to 120 seconds. Large outputs are truncated. "
        "Avoid interactive commands — use non-interactive flags (e.g. -y, --no-input)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory to run the command in (optional).",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds. Default {_DEFAULT_TIMEOUT}.",
            },
        },
        "required": ["command"],
    }
    requires_permission = "execute"

    def run(self, command: str, timeout: int = _DEFAULT_TIMEOUT, cwd: str | None = None, **_: Any) -> ToolResult:
        # Warn about obviously dangerous patterns
        lower = command.lower()
        for pat in _DANGER_PATTERNS:
            if pat in lower:
                return ToolResult(
                    f"Command blocked: contains dangerous pattern '{pat}'. "
                    "Use explicit permission override if you really need this.",
                    is_error=True,
                )

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=os.environ.copy(),
                cwd=cwd,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            combined = stdout
            if stderr:
                combined += ("\n" if combined else "") + stderr

            if len(combined) > _MAX_OUTPUT:
                combined = combined[:_MAX_OUTPUT] + f"\n[... output truncated at {_MAX_OUTPUT} chars]"

            if proc.returncode != 0:
                return ToolResult(combined or f"Exit code {proc.returncode}", is_error=True)
            return ToolResult(combined or f"(exit code 0, no output)")

        except subprocess.TimeoutExpired:
            return ToolResult(f"Command timed out after {timeout}s", is_error=True)
        except OSError as e:
            return ToolResult(str(e), is_error=True)
