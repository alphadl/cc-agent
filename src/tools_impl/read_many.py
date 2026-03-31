"""ReadMany tool — read multiple text files in one call."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


class ReadManyTool(Tool):
    name = "ReadMany"
    description = (
        "Read multiple files in a single tool call. "
        "Returns each file with line numbers, separated by a header. "
        "Use this to quickly load related files (configs, small modules, etc.)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Absolute paths of files to read.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed) for each file. Default 1.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read per file. Default 200.",
            },
            "max_files": {
                "type": "integer",
                "description": "Safety cap on number of files. Default 10.",
            },
        },
        "required": ["file_paths"],
    }
    requires_permission = "read"

    def run(
        self,
        file_paths: list[str],
        offset: int = 1,
        limit: int = 200,
        max_files: int = 10,
        **_: Any,
    ) -> ToolResult:
        if not isinstance(file_paths, list) or not file_paths:
            return ToolResult("file_paths must be a non-empty list", is_error=True)

        paths = [Path(p) for p in file_paths[: max(1, int(max_files))]]
        blocks: list[str] = []

        for p in paths:
            header = f"=== {p} ==="
            if not p.exists():
                blocks.append(f"{header}\n[File not found]\n")
                continue
            if not p.is_file():
                blocks.append(f"{header}\n[Not a file]\n")
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                blocks.append(f"{header}\n[{e}]\n")
                continue

            lines = text.splitlines(keepends=True)
            start = max(0, (offset or 1) - 1)
            end = start + (limit or 200)
            chunk = lines[start:end]
            numbered = "".join(f"{start + i + 1}\t{line}" for i, line in enumerate(chunk))
            if end < len(lines):
                numbered += f"\n[... {len(lines) - end} more lines. Use offset/limit to read more.]"
            blocks.append(f"{header}\n{numbered or '[empty file]'}\n")

        return ToolResult("\n".join(blocks).rstrip() or "(no output)")

