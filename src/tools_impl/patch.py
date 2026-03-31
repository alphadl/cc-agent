"""Patch tool — apply unified diffs (single-file) safely."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_unified_diff(diff: str) -> tuple[str | None, list[tuple[int, list[str]]], str | None]:
    """Return (target_path, hunks, error). Hunks are (old_start, lines)."""
    lines = diff.splitlines()
    target: str | None = None
    hunks: list[tuple[int, list[str]]] = []
    i = 0

    # Find a '+++ b/...' line if present
    while i < len(lines):
        line = lines[i]
        if line.startswith("+++ "):
            p = line[4:].strip()
            if p.startswith("b/"):
                p = p[2:]
            if p != "/dev/null":
                target = p
        i += 1

    # Extract hunks
    i = 0
    while i < len(lines):
        m = _HUNK_RE.match(lines[i])
        if not m:
            i += 1
            continue
        old_start = int(m.group(1))
        i += 1
        hunk_lines: list[str] = []
        while i < len(lines) and not lines[i].startswith("@@ "):
            # Stop if a new file header begins
            if lines[i].startswith("--- ") or lines[i].startswith("diff --git "):
                break
            hunk_lines.append(lines[i])
            i += 1
        hunks.append((old_start, hunk_lines))

    if not hunks:
        return target, [], "No hunks found in diff."
    return target, hunks, None


def _apply_hunks(original: str, hunks: list[tuple[int, list[str]]]) -> tuple[str | None, str | None]:
    """Apply hunks to original file content. Returns (updated, error)."""
    orig_lines = original.splitlines(keepends=True)
    out: list[str] = []
    src_idx = 0  # 0-based index into orig_lines

    for old_start_1based, hunk_lines in hunks:
        target_idx = max(0, old_start_1based - 1)
        if target_idx < src_idx:
            return None, "Overlapping hunks or invalid hunk order."

        # Copy unchanged lines before hunk
        out.extend(orig_lines[src_idx:target_idx])
        src_idx = target_idx

        for hl in hunk_lines:
            if not hl:
                continue
            tag = hl[0]
            text = hl[1:]
            if tag == " ":
                # context line must match
                if src_idx >= len(orig_lines):
                    return None, "Hunk context goes past end of file."
                if orig_lines[src_idx].rstrip("\n") != text.rstrip("\n"):
                    return None, "Hunk context did not match file content."
                out.append(orig_lines[src_idx])
                src_idx += 1
            elif tag == "-":
                # deletion must match
                if src_idx >= len(orig_lines):
                    return None, "Hunk deletion goes past end of file."
                if orig_lines[src_idx].rstrip("\n") != text.rstrip("\n"):
                    return None, "Hunk deletion did not match file content."
                src_idx += 1
            elif tag == "+":
                # insertion
                out.append(text + "\n")
            elif tag == "\\":
                # "\ No newline at end of file" — ignore
                continue
            else:
                return None, f"Invalid hunk line prefix: {tag!r}"

    # Copy remaining tail
    out.extend(orig_lines[src_idx:])
    return "".join(out), None


class PatchTool(Tool):
    name = "Patch"
    description = (
        "Apply a unified diff (single file) to the filesystem. "
        "This enables surgical multi-line edits without exact-string matching. "
        "If the patch cannot be applied cleanly, it fails without modifying the file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path of the file to patch. If omitted, inferred from diff headers when possible.",
            },
            "diff": {
                "type": "string",
                "description": "Unified diff text.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, validates patch but does not write. Default false.",
            },
        },
        "required": ["diff"],
    }
    requires_permission = "write"

    def run(self, diff: str, file_path: str | None = None, dry_run: bool = False, **_: Any) -> ToolResult:
        inferred_path, hunks, err = _parse_unified_diff(diff)
        if err:
            return ToolResult(err, is_error=True)

        target = file_path or inferred_path
        if not target:
            return ToolResult("file_path is required (could not infer from diff).", is_error=True)

        path = Path(target)
        if not path.is_absolute():
            return ToolResult("file_path must be an absolute path.", is_error=True)
        if not path.exists():
            return ToolResult(f"File not found: {target}", is_error=True)
        if not path.is_file():
            return ToolResult(f"Not a file: {target}", is_error=True)

        try:
            original = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(str(e), is_error=True)

        updated, apply_err = _apply_hunks(original, hunks)
        if apply_err or updated is None:
            return ToolResult(f"Patch failed: {apply_err}", is_error=True)

        if dry_run:
            return ToolResult(f"Patch OK (dry-run): {target}")

        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as e:
            return ToolResult(str(e), is_error=True)

        return ToolResult(f"Patched {target} successfully.")

