"""Read tool — reads files with line numbers (cat -n style)."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult

_MAX_LINES = 2000


class ReadTool(Tool):
    name = "Read"
    description = (
        "Read a file from the filesystem. Returns contents with line numbers "
        "(cat -n format). Reads up to 2000 lines by default. "
        "Use offset and limit to read specific sections of large files."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to read.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed). Omit to start from the beginning.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of lines to read. Defaults to {_MAX_LINES}.",
            },
        },
        "required": ["file_path"],
    }
    requires_permission = "read"

    def run(self, file_path: str, offset: int = 1, limit: int = _MAX_LINES, **_: Any) -> ToolResult:
        path = Path(file_path)
        if not path.exists():
            return ToolResult(f"File not found: {file_path}", is_error=True)
        if not path.is_file():
            return ToolResult(f"Not a file: {file_path}", is_error=True)

        # Binary / image check
        mime, _ = mimetypes.guess_type(str(path))
        if mime and not mime.startswith("text"):
            return ToolResult(f"[Binary file: {mime}] — cannot display as text.", is_error=False)

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(str(e), is_error=True)

        lines = text.splitlines(keepends=True)
        start = max(0, (offset or 1) - 1)
        end = start + (limit or _MAX_LINES)
        chunk = lines[start:end]

        numbered = "".join(
            f"{start + i + 1}\t{line}" for i, line in enumerate(chunk)
        )
        if end < len(lines):
            numbered += f"\n[... {len(lines) - end} more lines. Use offset/limit to read more.]"

        return ToolResult(numbered or "[empty file]")
