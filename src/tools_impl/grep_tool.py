"""Grep tool — fast regex search using ripgrep (rg) with fallback to Python re."""
from __future__ import annotations

import re
import subprocess
import shutil
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult

_MAX_LINES = 500


class GrepTool(Tool):
    name = "Grep"
    description = (
        "Search file contents using regular expressions. "
        "Uses ripgrep (rg) when available for maximum speed. "
        "Returns matching file paths by default; set output_mode='content' "
        "to show matching lines."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search. Defaults to current directory.",
            },
            "glob": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. '*.py').",
            },
            "output_mode": {
                "type": "string",
                "enum": ["files_with_matches", "content", "count"],
                "description": "Output mode. Default: files_with_matches.",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case-insensitive search. Default false.",
            },
            "context": {
                "type": "integer",
                "description": "Lines of context around each match (content mode only).",
            },
            "head_limit": {
                "type": "integer",
                "description": "Maximum number of output lines to return (after offset). Default 200.",
            },
            "offset": {
                "type": "integer",
                "description": "Skip the first N output lines (for pagination). Default 0.",
            },
        },
        "required": ["pattern"],
    }
    requires_permission = "read"

    def run(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        output_mode: str = "files_with_matches",
        case_insensitive: bool = False,
        context: int = 0,
        head_limit: int = 200,
        offset: int = 0,
        **_: Any,
    ) -> ToolResult:
        search_path = path or str(Path.cwd())

        if shutil.which("rg"):
            return self._rg(pattern, search_path, glob, output_mode, case_insensitive, context, head_limit, offset)
        return self._python_grep(pattern, search_path, glob, output_mode, case_insensitive, context, head_limit, offset)

    def _rg(
        self,
        pattern: str,
        path: str,
        glob: str | None,
        output_mode: str,
        case_insensitive: bool,
        context: int,
        head_limit: int,
        offset: int,
    ) -> ToolResult:
        cmd = ["rg", pattern, path]
        if case_insensitive:
            cmd.append("-i")
        if glob:
            cmd += ["--glob", glob]
        if output_mode == "files_with_matches":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")
        elif context:
            cmd += ["-C", str(context)]
        cmd += ["--no-heading", "-n"] if output_mode == "content" else []

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout.strip()
            if not output:
                return ToolResult(f"No matches for '{pattern}'")
            all_lines = output.splitlines()
            start = max(0, int(offset or 0))
            limit = max(1, int(head_limit or 200))
            lines = all_lines[start:start + min(limit, _MAX_LINES)]
            text = "\n".join(lines)
            if start + limit < len(all_lines):
                text += f"\n[More results available. offset={start + limit}]"
            if len(lines) >= _MAX_LINES:
                text += f"\n[Truncated at {_MAX_LINES} lines]"
            return ToolResult(text)
        except subprocess.TimeoutExpired:
            return ToolResult("Search timed out after 30s", is_error=True)
        except OSError as e:
            return ToolResult(str(e), is_error=True)

    def _python_grep(
        self,
        pattern: str,
        path: str,
        glob: str | None,
        output_mode: str,
        case_insensitive: bool,
        context: int,
        head_limit: int,
        offset: int,
    ) -> ToolResult:
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(f"Invalid regex: {e}", is_error=True)

        base = Path(path)
        if base.is_file():
            files = [base]
        else:
            files_gen = base.rglob(glob or "*") if glob else base.rglob("*")
            files = [f for f in files_gen if f.is_file()]

        results: list[str] = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if output_mode == "files_with_matches":
                if regex.search(text):
                    results.append(str(f))
            elif output_mode == "count":
                count = len(regex.findall(text))
                if count:
                    results.append(f"{f}:{count}")
            else:
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if regex.search(line):
                        results.append(f"{f}:{i+1}:{line}")

            if len(results) >= _MAX_LINES:
                break

        if not results:
            return ToolResult(f"No matches for '{pattern}'")
        start = max(0, int(offset or 0))
        limit = max(1, int(head_limit or 200))
        page = results[start:start + min(limit, _MAX_LINES)]
        text = "\n".join(page)
        if start + limit < len(results):
            text += f"\n[More results available. offset={start + limit}]"
        return ToolResult(text)
