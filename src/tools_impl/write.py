"""Write tool — create or overwrite files."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


class WriteTool(Tool):
    name = "Write"
    description = (
        "Write content to a file, creating it or completely overwriting it. "
        "If the file already exists, it MUST have been read with the Read tool "
        "earlier in this conversation. Prefer Edit for modifying existing files."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file.",
            },
        },
        "required": ["file_path", "content"],
    }
    requires_permission = "write"

    def run(self, file_path: str, content: str, **_: Any) -> ToolResult:
        path = Path(file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(f"Successfully wrote {len(content)} bytes to {file_path}")
        except OSError as e:
            return ToolResult(str(e), is_error=True)
