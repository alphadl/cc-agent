"""Glob tool — find files by pattern sorted by modification time."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult

_MAX_RESULTS = 500


class GlobTool(Tool):
    name = "Glob"
    description = (
        "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
        "Returns matching paths sorted by modification time (newest first). "
        "Optionally restrict to a subdirectory with the `path` parameter."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files against.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to current working directory.",
            },
        },
        "required": ["pattern"],
    }
    requires_permission = "read"

    def run(self, pattern: str, path: str | None = None, **_: Any) -> ToolResult:
        base = Path(path) if path else Path.cwd()
        if not base.exists():
            return ToolResult(f"Directory not found: {base}", is_error=True)

        try:
            matches = sorted(
                base.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except Exception as e:
            return ToolResult(str(e), is_error=True)

        files = [p for p in matches if p.is_file()][:_MAX_RESULTS]

        if not files:
            return ToolResult(f"No files matched pattern '{pattern}' in {base}")

        lines = [str(p) for p in files]
        result = "\n".join(lines)
        if len(files) == _MAX_RESULTS:
            result += f"\n[Results truncated at {_MAX_RESULTS}]"
        return ToolResult(result)
