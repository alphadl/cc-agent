# cc-agent

<p align="center">
  <img src="assets/clawd-hero.jpeg" alt="cc-agent" width="300" />
</p>

<p align="center">
  <strong>A real Python agentic harness for Claude — not just an archive</strong>
</p>

<p align="center">
  <a href="https://github.com/alphadl/cc-agent"><img src="https://img.shields.io/badge/Python-3.8+-blue?style=for-the-badge&logo=python" alt="Python 3.8+" /></a>
  <a href="https://www.anthropic.com"><img src="https://img.shields.io/badge/Powered%20by-Claude-orange?style=for-the-badge" alt="Powered by Claude" /></a>
</p>

---

## What is cc-agent?

**cc-agent** is a Python-native Claude Code–style agent harness. It gives Claude real tools to read, write, edit, search, and execute — then loops until the task is done.

Inspired by the architectural patterns of Anthropic's Claude Code (TypeScript), reimplemented cleanly in Python with some improvements along the way.

> **cc** = Claude Code. **agent** = it actually does things.

---

## Features

- **Real agentic loop** — model calls tools, sees results, keeps going until done
- **10 core tools** — Read, ReadMany, Write, Edit, Patch, Glob, Grep, Bash, Git, WebFetch
- **Permission system** — interactive approval, YOLO mode, per-session grants
- **Three-tier context** — loads `~/.claude/CLAUDE.md` → project → cwd automatically
- **Auto-compaction** — summarizes old messages when context window fills up
- **Multi-provider** — Anthropic, OpenRouter, or any OpenAI-compatible endpoint
- **Parallel tools** — independent tool calls run concurrently for speed
- **Streaming REPL** — colored output, live tool execution display, Markdown rendering
- **Session persistence** — resume any past conversation with `--resume`
- **Config system** — layered config via `~/.cc-agent/config.json`, `.cc-agent.json`, or env vars
- **Slash commands** — `/clear` `/compact` `/context` `/model` `/tools` `/config` `/yolo` `/help`

---

## Quickstart

### Anthropic (default)

```bash
git clone https://github.com/alphadl/cc-agent.git
cd cc-agent
pip install anthropic rich
export ANTHROPIC_API_KEY=sk-ant-...
./cc
```

If you use [uv](https://github.com/astral-sh/uv), the launcher auto-detects the venv:

```bash
uv venv && uv pip install anthropic rich
./cc
```

### OpenRouter

Use any model from [openrouter.ai/models](https://openrouter.ai/models) — Claude, GPT-4o, Gemini, Qwen, DeepSeek, and more.

```bash
pip install openai rich
export OPENROUTER_API_KEY=sk-or-...
./cc
```

Once `OPENROUTER_API_KEY` is set, just pass the model ID as-is from the OpenRouter catalog:

```bash
./cc --model qwen/qwen3-235b-a22b
./cc --model anthropic/claude-sonnet-4-5
./cc --model openai/gpt-4o
./cc --model google/gemini-2.0-flash
./cc --model deepseek/deepseek-r1
```

You can also use the `openrouter/` prefix to force OpenRouter even without the env var:

```bash
./cc --model openrouter/qwen/qwen3-235b-a22b
```

### OpenAI-compatible (Groq, Together, local, etc.)

```bash
pip install openai rich
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://api.groq.com/openai/v1
./cc --model llama-3.3-70b-versatile
```

---

## Usage

```bash
./cc                                     # start interactive agent session
./cc --yolo                              # auto-approve all tool calls
./cc --model claude-opus-4-6             # specify Anthropic model
./cc --model qwen/qwen3-235b-a22b        # OpenRouter model (OPENROUTER_API_KEY set)
./cc --cwd /path/to/project              # set working directory
./cc -p "summarize this repo"            # headless / non-interactive mode
./cc --resume <session-id>               # resume a previous session
```

### Provider detection (automatic)

| Condition | Provider used |
|-----------|---------------|
| Model starts with `openrouter/` | OpenRouter |
| `OPENROUTER_API_KEY` is set | OpenRouter |
| `OPENAI_API_KEY` or `OPENAI_BASE_URL` is set | OpenAI-compatible |
| otherwise | Anthropic |

When `OPENROUTER_API_KEY` is set, you do **not** need the `openrouter/` prefix — just use model IDs directly from the OpenRouter catalog.

### Slash commands

| Command | Description |
|---------|-------------|
| `/clear` | Clear conversation history |
| `/compact` | Summarize old messages to free context |
| `/context` | Show token usage bar |
| `/model <id>` | Switch model mid-session |
| `/tools` | List available tools |
| `/config` | Show current config and config file path |
| `/yolo` | Toggle auto-approve for all tools |
| `/history` | Show conversation history |
| `/sessions` | List saved sessions |
| `/help` | Show all commands |
| `/exit` | Quit |

---

## Tools

| Tool | Description |
|------|-------------|
| `Read` | Read files with line numbers (up to 2000 lines) |
| `ReadMany` | Read multiple files in one call (line-numbered) |
| `Write` | Create or overwrite files |
| `Edit` | Exact string replacement (fails if not unique — safe by design) |
| `Patch` | Apply a unified diff (single-file) safely |
| `Glob` | Find files by pattern, sorted by modification time |
| `Grep` | Regex search via ripgrep (falls back to Python re) |
| `Bash` | Run shell commands with timeout and danger-pattern checks |
| `Git` | Read-only git operations: status, diff, log, branch, show |
| `WebFetch` | Fetch a URL and return plain text (HTML stripped, max 50k chars) |

---

## Permission System

Default behavior (configurable via `~/.cc-agent/config.json`):

- **Read / ReadMany / Glob / Grep / Git / WebFetch** — auto-approved (read-only, safe)
- **Write / Edit / Patch** — auto-approved by default
- **Bash** — asks for approval (potentially dangerous)

You can also add **fine-grained rules** in config:

- **deny_tools / allow_tools** — always deny/allow specific tools
- **deny_bash_substrings** — deny Bash commands containing substrings (e.g. `"git push"`)
- **allow_bash_prefixes** — auto-allow Bash commands with specific prefixes (e.g. `"pytest"`, `"git status"`)

Interactive prompt for Bash calls:
```
⚠  Permission required: Bash
   $ pytest tests/ -v
   [y] allow once  [Y] allow for session  [n] deny  [N] deny for session
   >
```

Skip all prompts with `--yolo` or `/yolo` inside the session.

---

## Config System

Settings are loaded in order (later overrides earlier):

1. Built-in defaults
2. `~/.cc-agent/config.json` — user global config (created on first run)
3. `.cc-agent.json` in project root — project-level overrides
4. `CC_AGENT_<KEY>=value` environment variables

View current config inside a session with `/config`.

Key options (with defaults):

```json
{
  "model": "claude-sonnet-4-6",
  "max_tokens": 8096,
  "thinking_budget": 8096,
  "auto_approve_reads": true,
  "auto_approve_writes": true,
  "auto_approve_execute": false,
  "yolo": false,
  "deny_tools": [],
  "allow_tools": [],
  "deny_bash_substrings": [],
  "allow_bash_prefixes": [],
  "parallel_tools": true,
  "render_markdown": true,
  "stream_dots": true,
  "show_cost": true,
  "auto_save_session": true,
  "max_tool_iterations": 50,
  "max_retries": 3,
  "compact_threshold": 0.85,
  "compact_keep_messages": 8
}
```

Override via env var example:
```bash
CC_AGENT_MODEL=qwen/qwen3-235b-a22b CC_AGENT_YOLO=true ./cc
```

---

## Context Management (CLAUDE.md)

cc-agent loads instructions from three locations, in order:

1. `~/.claude/CLAUDE.md` — personal global preferences
2. `<project-root>/CLAUDE.md` — project-level instructions
3. `<cwd>/CLAUDE.md` — subdirectory instructions

Create a `CLAUDE.md` in your project to give the agent persistent context:

```markdown
## Project: my-api

- Language: Python 3.11, FastAPI
- Tests: pytest, run with `pytest tests/ -v`
- Style: black + ruff, no unused imports
- Never modify migration files directly
```

---

## Session Persistence

Every conversation is auto-saved to `~/.cc-agent/sessions/<id>.json`.

```bash
./cc --resume <session-id>   # resume a previous session
```

List sessions inside a running session with `/sessions`.

---

## Project Layout

```
cc-agent/
├── cc                          # launcher script (run this)
├── src/
│   ├── main.py                 # CLI entrypoint
│   ├── chat.py                 # interactive REPL
│   ├── agent_loop.py           # core tool-use loop (parallel, retry)
│   ├── provider.py             # multi-provider abstraction
│   ├── config.py               # layered config system
│   ├── session.py              # session persistence
│   ├── context_manager.py      # CLAUDE.md loading + auto-compact
│   ├── model_registry.py       # per-model context window sizes
│   ├── permission_system.py    # approval hooks
│   └── tools_impl/
│       ├── read.py
│       ├── read_many.py
│       ├── write.py
│       ├── edit.py
│       ├── patch.py
│       ├── glob_tool.py
│       ├── grep_tool.py
│       ├── bash.py
│       ├── git_tool.py
│       └── web_fetch.py
└── tests/
```

---

## Origin

This project started as [claw-code](https://github.com/instructkr/claw-code), a Python porting workspace that studied the Claude Code harness architecture. The core agent harness (tools, loop, permissions, context) was implemented from scratch in Python, drawing on the architectural patterns of the original TypeScript system.

- Not affiliated with or endorsed by Anthropic
- Does not contain any proprietary Anthropic source code

---

## License

MIT
