"""Edit tool — exact string replacement in files."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


class EditTool(Tool):
    name = "Edit"
    description = (
        "Replace an exact string in a file. "
        "The file must have been read with Read earlier in this conversation. "
        "`old_string` must appear EXACTLY once in the file — provide more surrounding "
        "context if it appears multiple times. "
        "Set `replace_all=true` to replace every occurrence."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to find and replace.",
            },
            "new_string": {
                "type": "string",
                "description": "Text to replace it with.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences instead of requiring uniqueness. Default false.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }
    requires_permission = "write"

    def run(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        **_: Any,
    ) -> ToolResult:
        path = Path(file_path)
        if not path.exists():
            return ToolResult(f"File not found: {file_path}", is_error=True)

        try:
            original = path.read_text(encoding="utf-8")
        except OSError as e:
            return ToolResult(str(e), is_error=True)

        count = original.count(old_string)
        if count == 0:
            return ToolResult(
                f"old_string not found in {file_path}. "
                "Make sure it matches exactly (including whitespace and indentation).",
                is_error=True,
            )
        if count > 1 and not replace_all:
            return ToolResult(
                f"old_string appears {count} times in {file_path}. "
                "Provide more surrounding context to make it unique, "
                "or set replace_all=true.",
                is_error=True,
            )

        if replace_all:
            updated = original.replace(old_string, new_string)
            n = count
        else:
            updated = original.replace(old_string, new_string, 1)
            n = 1

        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as e:
            return ToolResult(str(e), is_error=True)

        return ToolResult(f"Replaced {n} occurrence(s) in {file_path}")
