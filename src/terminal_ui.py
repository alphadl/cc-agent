"""Rich Terminal UI — scrollable history, tool output panels, context bar, streaming display.

Provides a polished terminal interface without external dependencies (pure ANSI/Python).
Falls back gracefully on terminals with limited ANSI support.

Features:
  - Markdown rendering (headers, bold, italic, code blocks, lists, tables)
  - Tool output panels with collapsible sections
  - Thinking/reasoning panels
  - Context window progress bar
  - Scrolling message history (/history --scroll)
  - Color-themed output
  - Live streaming indicators
"""
from __future__ import annotations

import os
import re
import sys
import textwrap
from typing import Optional


# ── Color Palette ────────────────────────────────────────────────────────

class Colors:
    """ANSI color constants. Auto-detects terminal color support."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Semantic aliases
    TEXT = BRIGHT_WHITE
    MUTED = BRIGHT_BLACK
    ACCENT = BRIGHT_CYAN
    SUCCESS = BRIGHT_GREEN
    WARNING = BRIGHT_YELLOW
    ERROR = BRIGHT_RED
    TOOL_NAME = BRIGHT_BLUE
    THINKING = BRIGHT_MAGENTA
    LINK = BRIGHT_CYAN

    @classmethod
    def strip(cls, text: str) -> str:
        """Remove all ANSI escape sequences."""
        return re.sub(r"\033\[[0-9;]*m", "", text)

    @classmethod
    def visible_length(cls, text: str) -> int:
        """Get visible (non-ANSI) length of text."""
        return len(cls.strip(text))

    @classmethod
    def supports_color(cls) -> bool:
        """Check if terminal supports color."""
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("TERM") in ("dumb", ""):
            return False
        if not sys.stdout.isatty():
            return False
        return True

    @classmethod
    def disable(cls) -> None:
        """Disable all colors (for testing/plain output)."""
        for attr in dir(cls):
            if attr.isupper() and isinstance(getattr(cls, attr), str):
                setattr(cls, attr, "")


C = Colors

def apply_theme(theme: str) -> None:
    """Apply a UI theme by adjusting semantic colors (and optionally disabling color)."""
    t = (theme or "dark").strip().lower()
    if t == "mono":
        Colors.disable()
        return
    if not Colors.supports_color():
        Colors.disable()
        return
    if t == "matrix":
        Colors.TEXT = Colors.BRIGHT_GREEN
        Colors.MUTED = Colors.GREEN
        Colors.ACCENT = Colors.BRIGHT_GREEN
        Colors.SUCCESS = Colors.BRIGHT_GREEN
        Colors.WARNING = Colors.BRIGHT_YELLOW
        Colors.ERROR = Colors.BRIGHT_RED
        Colors.TOOL_NAME = Colors.BRIGHT_GREEN
        Colors.THINKING = Colors.BRIGHT_GREEN
        Colors.LINK = Colors.BRIGHT_GREEN
    else:
        # dark (default): keep existing semantic mapping
        Colors.TEXT = Colors.BRIGHT_WHITE
        Colors.MUTED = Colors.BRIGHT_BLACK
        Colors.ACCENT = Colors.BRIGHT_CYAN
        Colors.SUCCESS = Colors.BRIGHT_GREEN
        Colors.WARNING = Colors.BRIGHT_YELLOW
        Colors.ERROR = Colors.BRIGHT_RED
        Colors.TOOL_NAME = Colors.BRIGHT_BLUE
        Colors.THINKING = Colors.BRIGHT_MAGENTA
        Colors.LINK = Colors.BRIGHT_CYAN


def _short_model(model: str) -> str:
    m = (model or "").strip()
    if not m:
        return ""
    return m.split("/")[-1]


def build_prompt(*, cwd: str, model: str, yolo: bool) -> str:
    """Build a compact geek prompt."""
    base = os.path.basename(os.path.abspath(cwd or ".")) or "."
    ms = _short_model(model) or "model"
    y = f"{C.WARNING}!{C.RESET}" if yolo and C.WARNING else "!"
    yolo_tag = f" {y}" if yolo else ""
    return f"{C.DIM}cc-agent{C.RESET} {C.ACCENT}{base}{C.RESET} {C.DIM}{ms}{C.RESET}{yolo_tag} {C.BOLD}{C.ACCENT}>{C.RESET} "


# ── Terminal Dimensions ──────────────────────────────────────────────────

def get_terminal_width() -> int:
    """Get terminal width, defaulting to 80."""
    try:
        size = os.get_terminal_size()
        return max(40, size.columns)
    except Exception:
        return 80


def get_terminal_height() -> int:
    """Get terminal height, defaulting to 24."""
    try:
        size = os.get_terminal_size()
        return max(10, size.lines)
    except Exception:
        return 24


# ── Markdown Renderer ────────────────────────────────────────────────────

class MarkdownRenderer:
    """Renders Markdown to formatted terminal output with ANSI colors."""

    def __init__(self, width: int = None, indent: int = 0):
        self._width = width or get_terminal_width()
        self._indent = indent

    def render(self, text: str) -> str:
        """Render markdown text to terminal-formatted string."""
        lines = text.split("\n")
        output: list = []
        in_code_block = False
        code_lang = ""
        code_lines: list = []
        in_table = False
        table_rows: list = []
        in_list = False
        list_depth = 0

        i = 0
        while i < len(lines):
            line = lines[i]

            # Code block toggle
            if line.strip().startswith("```"):
                if in_code_block:
                    # Close code block
                    output.append(self._render_code_block(code_lang, code_lines))
                    code_lines = []
                    in_code_block = False
                else:
                    # Open code block
                    in_code_block = True
                    code_lang = line.strip()[3:].strip()
                i += 1
                continue

            if in_code_block:
                code_lines.append(line)
                i += 1
                continue

            # Table
            if "|" in line and line.strip().startswith("|"):
                # Skip separator row
                if re.match(r"^\|[\s\-:|]+\|$", line.strip()):
                    i += 1
                    continue
                table_rows.append(self._parse_table_row(line))
                in_table = True
                i += 1
                # Check if next line continues the table
                while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
                    if re.match(r"^\|[\s\-:|]+\|$", lines[i].strip()):
                        i += 1
                        continue
                    table_rows.append(self._parse_table_row(lines[i]))
                    i += 1
                output.append(self._render_table(table_rows))
                table_rows = []
                in_table = False
                continue

            # Blank line
            if not line.strip():
                in_list = False
                output.append("")
                i += 1
                continue

            # Headers
            header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if header_match:
                level = len(header_match.group(1))
                title = header_match.group(2).strip()
                output.append(self._render_header(title, level))
                i += 1
                continue

            # Horizontal rule
            if re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", line.strip()):
                output.append(self._render_hr())
                i += 1
                continue

            # Unordered list
            ul_match = re.match(r"^(\s*)([-*+])\s+(.+)$", line)
            if ul_match:
                indent_str = ul_match.group(1)
                bullet = ul_match.group(2)
                item_text = ul_match.group(3)
                depth = len(indent_str) // 2
                if not in_list or depth != list_depth:
                    in_list = True
                    list_depth = depth
                output.append(self._render_list_item(item_text, depth, ordered=False))
                i += 1
                continue

            # Ordered list
            ol_match = re.match(r"^(\s*)(\d+)\.\s+(.+)$", line)
            if ol_match:
                indent_str = ol_match.group(1)
                num = ol_match.group(2)
                item_text = ol_match.group(3)
                depth = len(indent_str) // 2
                output.append(self._render_list_item(item_text, depth, ordered=True, num=num))
                i += 1
                continue

            # Checkbox list
            cb_match = re.match(r"^(\s*)([-*+])\s+\[([ xX])\]\s+(.+)$", line)
            if cb_match:
                item_text = cb_match.group(4)
                checked = cb_match.group(3) in ("x", "X")
                output.append(self._render_checkbox(item_text, checked))
                i += 1
                continue

            # Blockquote
            if line.strip().startswith(">"):
                quote_text = re.sub(r"^>\s?", "", line).strip()
                output.append(self._render_blockquote(quote_text))
                i += 1
                continue

            # Regular paragraph — apply inline formatting
            output.append(self._render_inline(line.strip()))
            i += 1
            continue

        return "\n".join(output)

    def _render_header(self, text: str, level: int) -> str:
        indent = "  " * self._indent
        if level == 1:
            width = get_terminal_width() - len(indent)
            return f"\n{indent}{C.BOLD}{C.ACCENT}{'━' * width}{C.RESET}\n{indent}{C.BOLD}{C.ACCENT} {text}{C.RESET}\n{indent}{C.BOLD}{C.ACCENT}{'━' * width}{C.RESET}"
        elif level == 2:
            return f"\n{indent}{C.BOLD}{C.TEXT}── {text} ──{C.RESET}\n"
        elif level == 3:
            return f"\n{indent}{C.BOLD}{C.ACCENT}▸ {text}{C.RESET}\n"
        else:
            return f"\n{indent}{C.BOLD}{text}{C.RESET}\n"

    def _render_code_block(self, lang: str, lines: list) -> str:
        indent = "  " * self._indent
        if not lines:
            return f"{indent}{C.DIM}(empty code block){C.RESET}"
        max_line_num = len(lines)
        num_width = len(str(max_line_num))
        output = [f"{indent}{C.DIM}┌{'─' * 40}{C.RESET}"]
        if lang:
            output[0] = f"{indent}{C.DIM}┌ {C.ACCENT}{lang}{C.DIM} {'─' * max(0, 37 - len(lang))}{C.RESET}"
        for i, code_line in enumerate(lines):
            num = f"{C.DIM}{i + 1:>{num_width}}{C.RESET}"
            output.append(f"{indent}{C.DIM}│{C.RESET} {num}  {C.GREEN}{code_line}{C.RESET}")
        output.append(f"{indent}{C.DIM}└{'─' * 40}{C.RESET}")
        return "\n".join(output)

    def _render_inline(self, text: str) -> str:
        """Apply inline Markdown formatting: bold, italic, code, links."""
        indent = "  " * self._indent
        # Code spans
        text = re.sub(r"`([^`]+)`", f"{C.GREEN}`\\1`{C.RESET}", text)
        # Bold + italic
        text = re.sub(r"\*\*\*(.+?)\*\*\*", f"{C.BOLD}{C.ITALIC}\\1{C.RESET}", text)
        # Bold
        text = re.sub(r"\*\*(.+?)\*\*", f"{C.BOLD}\\1{C.RESET}", text)
        # Italic
        text = re.sub(r"\*(.+?)\*", f"{C.ITALIC}\\1{C.RESET}", text)
        # Strikethrough
        text = re.sub(r"~~(.+?)~~", f"{C.DIM}~~\\1~~{C.RESET}", text)
        # Links
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", f"{C.LINK}\\1{C.DIM}(\\2){C.RESET}", text)
        # Wrap to terminal width
        wrapped = textwrap.wrap(text, width=self._width - len(indent) - 2, replace_whitespace=False)
        return "\n".join(f"{indent}{line}" for line in wrapped)

    def _render_list_item(self, text: str, depth: int, ordered: bool = False, num: str = "") -> str:
        indent = "  " * (self._indent + depth)
        bullet = f"{num}." if ordered else f"{C.ACCENT}•{C.RESET}"
        formatted = self._render_inline(text)
        return f"{indent}{bullet} {formatted}"

    def _render_checkbox(self, text: str, checked: bool) -> str:
        indent = "  " * self._indent
        icon = f"{C.SUCCESS}☑{C.RESET}" if checked else f"{C.MUTED}☐{C.RESET}"
        return f"{indent}{icon} {self._render_inline(text)}"

    def _render_blockquote(self, text: str) -> str:
        indent = "  " * self._indent
        lines = textwrap.wrap(text, width=self._width - 6)
        return "\n".join(f"{indent}{C.DIM}│ {C.ITALIC}{line}{C.RESET}" for line in lines)

    def _render_hr(self) -> str:
        indent = "  " * self._indent
        width = self._width - len(indent)
        return f"{indent}{C.DIM}{'─' * width}{C.RESET}"

    def _parse_table_row(self, line: str) -> list:
        """Parse a Markdown table row into cells."""
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        return cells

    def _render_table(self, rows: list) -> str:
        """Render table rows as a formatted table."""
        if not rows:
            return ""
        indent = "  " * self._indent

        # Calculate column widths
        num_cols = max(len(row) for row in rows)
        col_widths = [0] * num_cols
        for row in rows:
            for j, cell in enumerate(row):
                if j < num_cols:
                    col_widths[j] = max(col_widths[j], C.visible_length(self._render_inline(cell)))

        # Limit total width
        total_width = sum(col_widths) + 3 * num_cols + 1
        max_width = self._width - len(indent) - 2
        if total_width > max_width:
            scale = max_width / total_width
            col_widths = [max(10, int(w * scale)) for w in col_widths]

        output = []
        # Header row
        if rows:
            header = rows[0]
            h_line = indent + C.DIM + "┌"
            for j in range(num_cols):
                h_line += "─" * (col_widths[j] + 2) + "┬"
            h_line = h_line.rstrip("┬") + "┐" + C.RESET
            output.append(h_line)

            row_line = indent + C.DIM + "│" + C.RESET
            for j in range(min(num_cols, len(header))):
                cell = self._render_inline(header[j])[:col_widths[j]]
                row_line += f" {C.BOLD}{cell}{C.RESET}{' ' * (col_widths[j] - C.visible_length(cell))} " + C.DIM + "│" + C.RESET
            output.append(row_line)

            sep = indent + C.DIM + "├"
            for j in range(num_cols):
                sep += "─" * (col_widths[j] + 2) + "┼"
            sep = sep.rstrip("┼") + "┤" + C.RESET
            output.append(sep)

            # Data rows
            for row in rows[1:]:
                row_line = indent + C.DIM + "│" + C.RESET
                for j in range(min(num_cols, len(row))):
                    cell = self._render_inline(row[j])[:col_widths[j]]
                    row_line += f" {cell}{' ' * (col_widths[j] - C.visible_length(cell))} " + C.DIM + "│" + C.RESET
                output.append(row_line)

            footer = indent + C.DIM + "└"
            for j in range(num_cols):
                footer += "─" * (col_widths[j] + 2) + "┴"
            footer = footer.rstrip("┴") + "┘" + C.RESET
            output.append(footer)

        return "\n".join(output)


# ── Tool Output Panel ────────────────────────────────────────────────────

class ToolPanel:
    """Renders tool execution panels with compact tool markers."""

    # Tool-specific markers (ASCII-safe)
    _TOOL_ICONS = {
        "Read":     "[R]",
        "ReadMany": "[RM]",
        "Write":    "[W]",
        "Edit":     "[E]",
        "Patch":    "[P]",
        "Glob":     "[GLOB]",
        "Grep":     "[GREP]",
        "Bash":     "[$]",
        "Git":      "[GIT]",
        "WebFetch": "[WEB]",
    }

    @staticmethod
    def _icon_for(name: str) -> str:
        return ToolPanel._TOOL_ICONS.get(name, "[TOOL]")

    @staticmethod
    def start(name: str, tool_input: dict) -> str:
        """Render a tool-start panel."""
        icon = ToolPanel._icon_for(name)
        desc = ToolPanel._format_input(name, tool_input)
        return (
            f"\n  {C.DIM}{_GLYPHS['elbow']}{_GLYPHS['hline'] * 2}{C.RESET} "
            f"{C.BOLD}{C.TOOL_NAME}{name}{C.RESET}  "
            f"{icon}  "
            f"{C.DIM}{desc}{C.RESET}"
        )

    @staticmethod
    def result(name: str, result: str, is_error: bool = False,
               preview_chars: int = 200) -> str:
        """Render a tool-result panel."""
        if is_error:
            icon = f"{C.ERROR}{_GLYPHS['cross']}{C.RESET}"
            label = f"{C.ERROR}FAILED{C.RESET}"
        else:
            icon = f"{C.SUCCESS}{_GLYPHS['check']}{C.RESET}"
            label = f"{C.SUCCESS}OK{C.RESET}"

        if not result:
            preview = ""
        elif is_error:
            lines = [ln for ln in result.splitlines() if ln.strip()][:12]
            preview = " | ".join(lines)[: max(preview_chars, 240)]
        else:
            preview = result.replace("\n", " ")[:preview_chars]
        return (
            f"  {C.DIM}{_GLYPHS['corner']}{_GLYPHS['hline'] * 2}{C.RESET} "
            f"{icon} {label}  "
            f"{C.DIM}{preview}{C.RESET}"
        )

    @staticmethod
    def full_output(name: str, result: str, is_error: bool = False) -> str:
        """Render a full tool output panel with border."""
        border_color = C.ERROR if is_error else C.DIM
        width = get_terminal_width() - 4

        lines = [
            f"  {border_color}╔{'═' * width}╗{C.RESET}",
            f"  {border_color}║{C.RESET} {C.BOLD}{name} output:{C.RESET}",
            f"  {border_color}╠{'═' * width}╣{C.RESET}",
        ]
        for line in result.split("\n")[:50]:
            lines.append(f"  {border_color}║{C.RESET} {line}")
        if result.count("\n") > 50:
            lines.append(f"  {border_color}║{C.RESET} {C.DIM}... ({result.count(chr(10))} total lines){C.RESET}")
        lines.append(f"  {border_color}╚{'═' * width}╝{C.RESET}")
        return "\n".join(lines)

    @staticmethod
    def _format_input(name: str, tool_input: dict) -> str:
        """Pretty-format tool invocation."""
        if name == "Bash":
            return f"$ {tool_input.get('command', '')}"
        if name == "Read":
            return f"Read {tool_input.get('file_path', '')}"
        if name == "Write":
            return f"Write {tool_input.get('file_path', '')}"
        if name == "Edit":
            return f"Edit {tool_input.get('file_path', '')}"
        if name == "Glob":
            return f"Glob {tool_input.get('pattern', '')} in {tool_input.get('path', '.')}"
        if name == "Grep":
            return f"Grep /{tool_input.get('pattern', '')}/ in {tool_input.get('path', '.')}"
        if name == "Git":
            return f"git {tool_input.get('command', '')} {' '.join(str(a) for a in tool_input.get('args', []))}"
        if name == "WebFetch":
            return f"fetch {tool_input.get('url', '')}"
        import json
        return json.dumps(tool_input, ensure_ascii=False)[:120]


# ── Thinking Panel ───────────────────────────────────────────────────────

class ThinkingPanel:
    """Renders thinking/reasoning output with animated indicator."""

    _spinner = None  # Spinner is defined later in this module

    @staticmethod
    def start() -> str:
        if ThinkingPanel._spinner is None:
            ThinkingPanel._spinner = Spinner("dots")
        return f"\n  {C.THINKING}{_GLYPHS['think']} Thinking{C.RESET}{' ' * 20}"

    @staticmethod
    def progress() -> str:
        """Return animated progress frame (to be used with \r)."""
        if ThinkingPanel._spinner is None:
            ThinkingPanel._spinner = Spinner("dots")
        frame = ThinkingPanel._spinner.tick()
        return f"\r  {C.THINKING}{frame} Thinking{C.DIM}⋯{C.RESET}   "

    @staticmethod
    def done(thinking_text: str) -> str:
        char_count = len(thinking_text)
        word_count = len(thinking_text.split())
        if ThinkingPanel._spinner is None:
            ThinkingPanel._spinner = Spinner("dots")
        ThinkingPanel._spinner.reset()
        return (
            f"\r\033[K  {C.THINKING}{_GLYPHS['think']} Thought{C.RESET} "
            f"{C.DIM}({char_count:,} chars, ~{word_count} words){C.RESET}"
        )


# ── Context Bar ──────────────────────────────────────────────────────────

class ContextBar:
    """Renders the context window usage bar with gradient fill."""

    @staticmethod
    def render(used_tokens: int, total_tokens: int, model: str = "",
               input_tokens: int = 0, output_tokens: int = 0,
               session_id: str = "", message_count: int = 0,
               yolo: bool = False) -> str:
        pct = (used_tokens / total_tokens * 100) if total_tokens > 0 else 0
        bar_len = 30
        filled = int(bar_len * min(pct, 100) / 100)

        # Gradient colors: green → yellow → red
        if pct < 50:
            color = C.SUCCESS
            shade = C.GREEN
        elif pct < 75:
            color = C.WARNING
            shade = C.YELLOW
        else:
            color = C.ERROR
            shade = C.RED

        # Build bar with a "head" marker
        if filled > 0:
            bar = f"{color}{_GLYPHS['block'] * (filled - 1)}{shade}{_GLYPHS['block']}{C.DIM}{_GLYPHS['shade'] * (bar_len - filled)}{C.RESET}"
        else:
            bar = f"{C.DIM}{_GLYPHS['shade'] * bar_len}{C.RESET}"

        m = _short_model(model)
        parts = [
            f"{C.ACCENT}{m}{C.RESET}" if m else "",
            f"{C.DIM}ctx{C.RESET}[{bar}] {pct:.0f}%",
            f"{C.DIM}{used_tokens:,}/{total_tokens:,}{C.RESET}",
        ]
        if input_tokens or output_tokens:
            parts.append(f"{C.DIM}↑{input_tokens:,} ↓{output_tokens:,}{C.RESET}")
        if message_count:
            parts.append(f"{C.DIM}msgs:{message_count}{C.RESET}")
        if session_id:
            parts.append(f"{C.DIM}{_GLYPHS['link']} {session_id[:8]}{C.RESET}")
        if yolo:
            parts.append(f"{C.WARNING}!YOLO{C.RESET}" if C.WARNING else "!YOLO")

        return "  ".join(p for p in parts if p)


# ── ASCII Art Logo ───────────────────────────────────────────────────────

_CC_LOGO = r"""
   ______  ______        ___                  __
  / ____/ / ____/  ____ /   | ____  ___  ____/ /_
 / /     / /      / __ `/ /| |/ __ \/ _ \/ __  / /
/ /___  / /___   / /_/ / ___ / /_/ /  __/ /_/ / /
\____/  \____/   \__,_/_/  |_\__, /\___/\__,_/_/
                             /____/
"""

# Compact fallback logo for narrow terminals
_CC_LOGO_COMPACT = r"""
  CC-Agent
"""

_GLYPHS = {
    "arrow":    "->",
    "bullet":   "*",
    "diamond":  "#",
    "check":    "OK",
    "cross":    "X",
    "warn":     "!",
    "gear":     "@",
    "bolt":     "!",
    "link":     "~",
    "lock":     "#",
    "rocket":   "^",
    "terminal": ">",
    "think":    "?",
    "save":     "S",
    "tool":     "T",
    "fire":     "*",
    "star":     "✦",
    "dot":      "•",
    "pipe":     "│",
    "elbow":    "├",
    "corner":   "└",
    "tee":      "┬",
    "hline":    "─",
    "vline":    "│",
    "box_tl":   "╭",
    "box_tr":   "╮",
    "box_bl":   "╰",
    "box_br":   "╯",
    "box_t":    "┬",
    "box_b":    "┴",
    "box_x":    "┼",
    "box_h":    "─",
    "block":    "█",
    "shade":    "░",
    "dark":     "▓",
    "arrow_r":  "→",
    "arrow_l":  "←",
    "arrow_d":  "↓",
    "arrow_u":  "↑",
    "dbl_arrow": "⟫",
    "ellipsis": "⋯",
    "ruler":    "┄",
}


# ── Spinner (frame cycling) ─────────────────────────────────────────────

class Spinner:
    """ANSI spinner for tool execution / thinking progress."""

    _FRAMES_BRAILLE = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _FRAMES_DOTS    = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
    _FRAMES_ARROWS  = ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"]
    _FRAMES_BOX     = ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]
    _FRAMES_CLASSIC = ["/", "-", "\\", "|"]

    STYLES = {"braille": _FRAMES_BRAILLE, "dots": _FRAMES_DOTS,
              "arrows": _FRAMES_ARROWS, "box": _FRAMES_BOX, "classic": _FRAMES_CLASSIC}

    def __init__(self, style: str = "braille"):
        self._frames = self.STYLES.get(style, self._FRAMES_BRAILLE)
        self._i = 0

    def tick(self) -> str:
        frame = self._frames[self._i % len(self._frames)]
        self._i += 1
        return frame

    def reset(self) -> None:
        self._i = 0


# ── Banner ───────────────────────────────────────────────────────────────

class Banner:
    """Startup banner for the agent REPL — hacker-style ASCII art."""

    @staticmethod
    def _pick_logo() -> str:
        width = get_terminal_width()
        if width >= 80:
            return _CC_LOGO
        return _CC_LOGO_COMPACT

    @staticmethod
    def render(provider: str, model: str, cwd: str, yolo: bool,
               context_window: int = 0, mcp_status: str = "") -> str:
        g = _GLYPHS
        logo = Banner._pick_logo()

        # Color the logo lines with gradient effect
        logo_lines = []
        for i, line in enumerate(logo.split("\n")):
            if not line.strip():
                continue
            logo_lines.append(f"{C.DIM}{line}{C.RESET}")

        width = min(get_terminal_width(), 100)
        sep = f"{C.DIM}{g['ruler'] * width}{C.RESET}"

        # Build info rows
        yolo_tag = f"  {C.YELLOW}{g['bolt']} YOLO{C.RESET}" if yolo else ""
        info_lines = [
            f"  {C.ACCENT}{g['diamond']} Provider{C.RESET}  {C.GREEN}{provider}{C.RESET}"
            f"    {C.ACCENT}{g['diamond']} Model{C.RESET}     {C.BOLD}{model}{C.RESET}{yolo_tag}",
            f"  {C.ACCENT}{g['diamond']} Cwd{C.RESET}      {C.DIM}{cwd}{C.RESET}",
        ]
        if context_window:
            info_lines.append(
                f"  {C.ACCENT}{g['diamond']} Context{C.RESET}   {C.DIM}{context_window:,} tokens{C.RESET}"
            )
        if mcp_status:
            info_lines.append(f"  {C.ACCENT}{g['diamond']} MCP{C.RESET}      {mcp_status}")

        # Footer
        footer = (
            f"  {C.DIM}{g['arrow_r']} /help  commands  "
            f"{g['arrow_r']} Ctrl-C  interrupt  "
            f"{g['arrow_r']} /exit  quit{C.RESET}"
        )

        lines = [
            "",
            *logo_lines,
            "",
            sep,
            *info_lines,
            sep,
            footer,
            "",
        ]
        return "\n".join(lines)


# ── Status Line ──────────────────────────────────────────────────────────

class StatusLine:
    """Bottom status line (can be used for persistent status display)."""

    @staticmethod
    def render(status: str, right_text: str = "") -> str:
        width = get_terminal_width()
        visible_left = C.strip(status)
        visible_right = C.strip(right_text)
        gap = width - len(visible_left) - len(visible_right) - 2
        if gap < 1:
            gap = 1
        return f"  {status}{' ' * gap}{C.DIM}{right_text}{C.RESET}"


# ── Convenience Functions ────────────────────────────────────────────────

def render_markdown(text: str) -> str:
    """Render markdown text to terminal output."""
    return MarkdownRenderer().render(text)


def render_tool_start(name: str, tool_input: dict) -> str:
    return ToolPanel.start(name, tool_input)


def render_tool_result(name: str, result: str, is_error: bool = False,
                       preview_chars: int = 200) -> str:
    return ToolPanel.result(name, result, is_error, preview_chars)


def render_context_bar(used: int, total: int, **kwargs) -> str:
    return ContextBar.render(used, total, **kwargs)


def render_banner(provider: str, model: str, cwd: str, yolo: bool, **kwargs) -> str:
    return Banner.render(provider, model, cwd, yolo, **kwargs)
