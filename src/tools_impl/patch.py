"""Patch tool — apply unified diffs safely.

Supports:
- Single-file diffs (no headers)
- Multi-file diffs with `diff --git a/... b/...` headers
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _strip_ab(path: str) -> str:
    p = path.strip()
    if p.startswith("a/") or p.startswith("b/"):
        return p[2:]
    return p


def _parse_single_file_diff(diff: str) -> tuple[str | None, list[tuple[int, list[str]]], str | None]:
    """Parse hunks from a diff chunk; may include ---/+++ headers."""
    lines = diff.splitlines()
    target: str | None = None
    hunks: list[tuple[int, list[str]]] = []

    # Prefer '+++ ' for target path
    for line in lines:
        if line.startswith("+++ "):
            p = line[4:].strip()
            p = _strip_ab(p)
            if p != "/dev/null":
                target = p
                break

    i = 0
    while i < len(lines):
        m = _HUNK_RE.match(lines[i])
        if not m:
            i += 1
            continue
        old_start = int(m.group(1))
        i += 1
        hunk_lines: list[str] = []
        while i < len(lines):
            if lines[i].startswith("@@ "):
                break
            if lines[i].startswith("diff --git "):
                break
            if lines[i].startswith("--- ") or lines[i].startswith("+++ "):
                break
            hunk_lines.append(lines[i])
            i += 1
        hunks.append((old_start, hunk_lines))

    if not hunks:
        return target, [], "No hunks found in diff."
    return target, hunks, None


def _split_multi_file_diff(diff: str) -> list[tuple[str | None, str, str | None]]:
    """Split a possibly-multi-file diff into chunks.

    Returns list of (path_from_header, chunk_text, error).
    """
    lines = diff.splitlines(keepends=False)
    chunks: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if line.startswith("diff --git "):
            if current:
                chunks.append(current)
                current = []
        current.append(line)
    if current:
        chunks.append(current)

    # If no diff headers, treat entire input as one chunk
    if len(chunks) == 1 and not (chunks[0] and chunks[0][0].startswith("diff --git ")):
        return [(None, diff, None)]

    out: list[tuple[str | None, str, str | None]] = []
    for ch in chunks:
        header_path: str | None = None
        if ch and ch[0].startswith("diff --git "):
            parts = ch[0].split()
            if len(parts) >= 4:
                # "diff --git a/x b/y" — prefer b/ path
                header_path = _strip_ab(parts[3])
        out.append((header_path, "\n".join(ch) + "\n", None))
    return out


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
                    return None, f"Hunk context did not match at original line {src_idx + 1}."
                out.append(orig_lines[src_idx])
                src_idx += 1
            elif tag == "-":
                # deletion must match
                if src_idx >= len(orig_lines):
                    return None, "Hunk deletion goes past end of file."
                if orig_lines[src_idx].rstrip("\n") != text.rstrip("\n"):
                    return None, f"Hunk deletion did not match at original line {src_idx + 1}."
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
        "Apply a unified diff (single or multi-file) to the filesystem. "
        "This enables surgical multi-line edits without exact-string matching. "
        "If the patch cannot be applied cleanly, it fails without modifying the file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path of the file to patch (single-file mode). If omitted, inferred from diff headers when possible.",
            },
            "diff": {
                "type": "string",
                "description": "Unified diff text.",
            },
            "base_dir": {
                "type": "string",
                "description": "Base directory to resolve relative paths from diff headers. Defaults to current working directory.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, validates patch but does not write. Default false.",
            },
        },
        "required": ["diff"],
    }
    requires_permission = "write"

    def run(
        self,
        diff: str,
        file_path: str | None = None,
        base_dir: str | None = None,
        dry_run: bool = False,
        **_: Any,
    ) -> ToolResult:
        base = Path(base_dir) if base_dir else Path.cwd()
        chunks = _split_multi_file_diff(diff)

        applied: list[str] = []
        for header_path, chunk, _err in chunks:
            inferred_path, hunks, err = _parse_single_file_diff(chunk)
            if err:
                return ToolResult(err, is_error=True)

            target = file_path or inferred_path or header_path
            if not target:
                return ToolResult("file_path is required (could not infer from diff).", is_error=True)

            path = Path(target)
            if not path.is_absolute():
                path = base / _strip_ab(str(path))

            if not path.exists():
                return ToolResult(f"File not found: {path}", is_error=True)
            if not path.is_file():
                return ToolResult(f"Not a file: {path}", is_error=True)

            try:
                original = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                return ToolResult(str(e), is_error=True)

            updated, apply_err = _apply_hunks(original, hunks)
            if apply_err or updated is None:
                return ToolResult(f"Patch failed for {path}: {apply_err}", is_error=True)

            if not dry_run:
                try:
                    path.write_text(updated, encoding="utf-8")
                except OSError as e:
                    return ToolResult(str(e), is_error=True)

            applied.append(str(path))

        prefix = "Patch OK (dry-run)" if dry_run else "Patched"
        return ToolResult(f"{prefix} {len(applied)} file(s):\n" + "\n".join(applied))

