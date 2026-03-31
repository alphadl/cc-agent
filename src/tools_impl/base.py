"""Base class for all agent tools."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class ToolResult:
    content: str
    is_error: bool = False

    def to_api(self, tool_use_id: str) -> dict:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": self.content,
            "is_error": self.is_error,
        }


class Tool:
    """Base class for all agent tools."""
    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[dict]
    # Permissions: "read", "write", "execute"
    requires_permission: ClassVar[str] = "read"

    @classmethod
    def schema(cls) -> dict:
        return {
            "name": cls.name,
            "description": cls.description,
            "input_schema": cls.input_schema,
        }

    def run(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError
