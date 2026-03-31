"""WebFetch tool — fetch a URL and return its text content."""
from __future__ import annotations

import urllib.request
import urllib.error
from typing import Any

from .base import Tool, ToolResult

_MAX_CHARS = 50_000
_TIMEOUT = 20


class WebFetchTool(Tool):
    name = "WebFetch"
    description = (
        "Fetch the content of a URL and return it as plain text. "
        "HTML is converted to readable text by stripping tags. "
        "Use for reading documentation, GitHub files, APIs, or any web page."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "description": f"Maximum characters to return. Default {_MAX_CHARS}.",
            },
        },
        "required": ["url"],
    }
    requires_permission = "read"

    def run(self, url: str, max_chars: int = _MAX_CHARS, **_: Any) -> ToolResult:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "cc-agent/1.0 (python urllib)"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read(max_chars * 4)  # read extra for HTML stripping
        except urllib.error.HTTPError as e:
            return ToolResult(f"HTTP {e.code}: {e.reason}", is_error=True)
        except urllib.error.URLError as e:
            return ToolResult(f"URL error: {e.reason}", is_error=True)
        except Exception as e:
            return ToolResult(str(e), is_error=True)

        # Decode
        encoding = "utf-8"
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("charset="):
                encoding = part[8:].strip()
        try:
            text = raw.decode(encoding, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")

        # Strip HTML tags if HTML content
        if "html" in content_type.lower():
            text = _strip_html(text)

        text = text[:max_chars]
        if len(text) == max_chars:
            text += f"\n[Truncated at {max_chars} chars]"
        return ToolResult(text)


def _strip_html(html: str) -> str:
    """Very lightweight HTML → text: remove tags, decode common entities."""
    import re
    # Remove script/style blocks
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all other tags
    html = re.sub(r"<[^>]+>", " ", html)
    # Decode common entities
    for entity, char in [
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
    ]:
        html = html.replace(entity, char)
    # Collapse whitespace
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()
