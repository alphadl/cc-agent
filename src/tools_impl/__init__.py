"""Real tool implementations for cc-agent harness."""
from __future__ import annotations

from .bash import BashTool
from .edit import EditTool
from .git_tool import GitTool
from .glob_tool import GlobTool
from .grep_tool import GrepTool
from .patch import PatchTool
from .read import ReadTool
from .read_many import ReadManyTool
from .web_fetch import WebFetchTool
from .write import WriteTool

ALL_TOOLS = [
    ReadTool, ReadManyTool,
    WriteTool, EditTool, PatchTool,
    GlobTool, GrepTool,
    BashTool, GitTool, WebFetchTool,
]

__all__ = [
    "ReadTool", "WriteTool", "EditTool", "GlobTool", "GrepTool",
    "PatchTool", "ReadManyTool",
    "BashTool", "GitTool", "WebFetchTool",
    "ALL_TOOLS",
]
