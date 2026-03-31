"""Session persistence: save and resume conversations."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

_SESSIONS_DIR = Path.home() / ".cc-agent" / "sessions"


@dataclass
class Session:
    session_id: str
    model: str
    provider: str
    created_at: str
    updated_at: str
    messages: list[dict]
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cwd: str = ""
    title: str = ""

    @classmethod
    def new(cls, model: str, provider: str, cwd: str = "") -> "Session":
        now = datetime.now().isoformat()
        return cls(
            session_id=str(uuid.uuid4())[:8],
            model=model,
            provider=provider,
            created_at=now,
            updated_at=now,
            messages=[],
            cwd=cwd,
        )

    def save(self) -> Path:
        _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now().isoformat()
        path = _SESSIONS_DIR / f"{self.session_id}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, session_id: str) -> "Session":
        path = _SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            # Try prefix match
            matches = list(_SESSIONS_DIR.glob(f"{session_id}*.json"))
            if not matches:
                raise FileNotFoundError(f"Session not found: {session_id}")
            path = matches[0]
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    @classmethod
    def list_all(cls) -> list["Session"]:
        if not _SESSIONS_DIR.exists():
            return []
        sessions = []
        for p in sorted(_SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                sessions.append(cls(**data))
            except Exception:
                pass
        return sessions

    @classmethod
    def delete(cls, session_id: str) -> bool:
        path = _SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            matches = list(_SESSIONS_DIR.glob(f"{session_id}*.json"))
            if not matches:
                return False
            path = matches[0]
        try:
            path.unlink()
            return True
        except Exception:
            return False

    def export_markdown(self) -> str:
        lines: list[str] = []
        header = self.title or f"Session {self.session_id}"
        lines.append(f"# {header}")
        lines.append("")
        lines.append(f"- id: `{self.session_id}`")
        if self.model:
            lines.append(f"- model: `{self.model}`")
        if self.provider:
            lines.append(f"- provider: `{self.provider}`")
        if self.cwd:
            lines.append(f"- cwd: `{self.cwd}`")
        lines.append(f"- created_at: `{self.created_at}`")
        lines.append(f"- updated_at: `{self.updated_at}`")
        lines.append("")

        for m in self.messages:
            role = (m.get("role") or "").upper()
            content = m.get("content", "")
            lines.append(f"## {role}")
            lines.append("")
            if isinstance(content, str):
                lines.append(content)
            else:
                lines.append("```json")
                try:
                    lines.append(json.dumps(content, ensure_ascii=False, indent=2))
                except Exception:
                    lines.append(str(content))
                lines.append("```")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
