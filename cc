#!/usr/bin/env python3
"""cc-agent launcher.

Usage:
    ./cc                          # interactive agent REPL
    ./cc --yolo                   # auto-approve all tool calls
    ./cc --model openrouter/...   # use OpenRouter model
    ./cc -p "task description"    # headless: run task and exit
    ./cc --resume <session-id>    # resume previous session
    ./cc summary                  # porting workspace summary
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))

# Prefer the repo-level uv venv if available and we're not already in it
_VENV_PYTHON = os.path.join(os.path.dirname(_ROOT), ".venv", "bin", "python")
if os.path.isfile(_VENV_PYTHON) and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PYTHON):
    os.execv(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv)

sys.path.insert(0, _ROOT)

_WORKSPACE_CMDS = {
    "summary", "manifest", "parity-audit", "setup-report",
    "command-graph", "tool-pool", "bootstrap-graph", "subsystems",
    "commands", "tools", "route", "bootstrap", "turn-loop",
    "flush-transcript", "load-session", "remote-mode", "ssh-mode",
    "teleport-mode", "direct-connect-mode", "deep-link-mode",
    "show-command", "show-tool", "exec-command", "exec-tool", "chat",
}

args = sys.argv[1:]
first = args[0] if args else ""
if first and not first.startswith("-") and first in _WORKSPACE_CMDS:
    pass  # explicit subcommand — pass through
elif first in ("--help", "-h"):
    pass
else:
    # No explicit subcommand — default to 'chat'
    sys.argv = [sys.argv[0], "chat"] + args

from src.main import main  # noqa: E402
raise SystemExit(main())
