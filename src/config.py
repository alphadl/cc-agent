"""cc-agent configuration system.

Config is loaded from (in order, later overrides earlier):
  1. Built-in defaults (this file)
  2. ~/.cc-agent/config.json  (user global config)
  3. <project>/.cc-agent.json (project-level config)
  4. CLI flags

Run `./cc config` to view/edit current config.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_USER_CONFIG_PATH = Path.home() / ".cc-agent" / "config.json"
_PROJECT_CONFIG_NAME = ".cc-agent.json"


@dataclass
class Config:
    # ── Model ──────────────────────────────────────────────────────────
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8096
    thinking_budget: int = 8096             # thinking token budget (0 = disabled, -1 = auto)

    # ── Permissions ────────────────────────────────────────────────────
    # True = auto-approve without asking
    auto_approve_reads: bool = True      # Read, Glob, Grep, Git — always safe
    auto_approve_writes: bool = True     # Write, Edit — approve by default
    auto_approve_execute: bool = False   # Bash — still ask (potentially dangerous)
    yolo: bool = False                   # approve everything, no prompts at all

    # Fine-grained permission rules (optional, evaluated before prompts)
    deny_tools: list[str] = field(default_factory=list)          # e.g. ["Bash"]
    allow_tools: list[str] = field(default_factory=list)         # always allow these tools
    deny_bash_substrings: list[str] = field(default_factory=list)  # e.g. ["git push", "rm -rf"]
    allow_bash_prefixes: list[str] = field(default_factory=list)   # e.g. ["pytest", "git status", "rg "]
    deny_write_path_prefixes: list[str] = field(default_factory=list)  # e.g. ["/etc/", "~/.ssh/"]
    allow_write_path_prefixes: list[str] = field(default_factory=list) # if non-empty, writes must match one

    # Custom tools
    extra_tools: list[str] = field(default_factory=list)  # e.g. ["my_tools:MyTool", "my_pkg.tools"]

    # ── Agent loop ─────────────────────────────────────────────────────
    parallel_tools: bool = True          # run independent tool calls concurrently
    max_tool_iterations: int = 50        # safety cap on tool-use rounds
    max_retries: int = 3                 # API error retry attempts
    retry_delays: list = field(default_factory=lambda: [1, 3, 8])

    # ── Context management ─────────────────────────────────────────────
    compact_threshold: float = 0.85      # auto-compact at 85% context fill
    compact_keep_messages: int = 8       # keep last N messages after compaction

    # ── Output ─────────────────────────────────────────────────────────
    render_markdown: bool = True         # render responses as Markdown
    stream_dots: bool = True             # show dots while streaming
    show_cost: bool = True               # show estimated cost per turn
    tool_result_preview_chars: int = 120 # chars of tool output to preview

    # ── Sessions ───────────────────────────────────────────────────────
    auto_save_session: bool = True       # save session after each turn

    def to_dict(self) -> dict:
        return asdict(self)

    def save_user(self) -> Path:
        _USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _USER_CONFIG_PATH.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return _USER_CONFIG_PATH


def _merge(base: dict, override: dict) -> dict:
    """Shallow merge: override wins on key conflicts."""
    result = dict(base)
    for k, v in override.items():
        if k in result:  # only accept known keys
            result[k] = v
    return result


def load_config(cwd: str | None = None) -> Config:
    """Load config with Claude: defaults → user → project → env."""
    cfg = Config()
    defaults = cfg.to_dict()

    # 1. User config (~/.cc-agent/config.json)
    if _USER_CONFIG_PATH.exists():
        try:
            user_data = json.loads(_USER_CONFIG_PATH.read_text(encoding="utf-8"))
            defaults = _merge(defaults, user_data)
        except Exception:
            pass

    # 2. Project config (.cc-agent.json in cwd or parents)
    search = Path(cwd) if cwd else Path.cwd()
    for parent in [search] + list(search.parents):
        proj = parent / _PROJECT_CONFIG_NAME
        if proj.exists():
            try:
                proj_data = json.loads(proj.read_text(encoding="utf-8"))
                defaults = _merge(defaults, proj_data)
            except Exception:
                pass
            break
        if (parent / ".git").exists():
            break

    # 3. Environment variable overrides (CC_AGENT_<KEY>=value)
    for key in defaults:
        env_key = f"CC_AGENT_{key.upper()}"
        val = os.environ.get(env_key)
        if val is not None:
            current = defaults[key]
            if isinstance(current, bool):
                defaults[key] = val.lower() in ("1", "true", "yes")
            elif isinstance(current, int):
                try:
                    defaults[key] = int(val)
                except ValueError:
                    pass
            elif isinstance(current, float):
                try:
                    defaults[key] = float(val)
                except ValueError:
                    pass
            else:
                defaults[key] = val

    # Build final config object
    valid = {k: defaults[k] for k in Config.__dataclass_fields__}
    return Config(**valid)


def init_user_config() -> Path:
    """Write default config to ~/.cc-agent/config.json if it doesn't exist."""
    if not _USER_CONFIG_PATH.exists():
        Config().save_user()
    return _USER_CONFIG_PATH
