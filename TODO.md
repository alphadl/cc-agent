# TODO: cc-agent → Claude Code Parity

> Feature gaps and missing capabilities compared to the official Claude Code (TypeScript).

---

## 🔴 P0 — Critical: Blocks core usability

| # | Missing Feature | Claude Code Has | cc-agent Current State | Notes |
|---|----------------|-----------------|----------------------|-------|
| 1 | **Parallel tool execution** | Runs ≥2 independent tool calls concurrently | ✅ Implemented (ThreadPoolExecutor) | `src/agent_loop.py` can execute approved tool calls concurrently |
| 2 | **MCP (Model Context Protocol) support** | Connects to external MCP servers for tools | No MCP (`include_mcp` flag exists but does nothing) | Listed in `get_tools(..., include_mcp=True)` but no implementation (`src/plugins/__init__.py`, `src/memdir/`, `src/bridge/`, `src/remote/` are all empty stubs) |
| 3 | **Actual token counting** | Uses exact tokenizer (e.g. tiktoken / Anthropic's token count) | ✅ Implemented (multi-backend) | `src/token_counter.py` uses Anthropic count_tokens / tiktoken / builtin fallback |
| 4 | **Thinking / extended reasoning** | `thinking` blocks with configurable token budget | ✅ Implemented (best-effort) | Provider passes `thinking` when supported; SDK incompat falls back gracefully |
| 5 | **Headless / non-interactive mode** | `claude --print "task"` runs and exits | ✅ Implemented (`-p/--print`) | `./cc -p "..."` runs one turn and exits |
| 6 | **Conversation resume / session persistence** | Sessions survive terminal close | ✅ Implemented | `src/session.py` persists to `~/.cc-agent/sessions/<id>.json`; `--resume` supported |
| 7 | **Rich terminal UI** | Scrollable history, sidebar, streaming tool output panels | Basic `print()` REPL with ANSI colors | `src/ink.py`, `src/screens/`, `src/outputStyles/` are all empty — no Textual / Rich layout |

---

## 🟠 P1 — Important: Significant capability gap

| # | Missing Feature | Claude Code Has | cc-agent Current State | Notes |
|---|----------------|----------------|----------------------|-------|
| 8 | **Diff / patch tool** | `patch` tool for surgical edits | ✅ Implemented | `Patch` tool applies unified diffs (single-file) |
| 9 | **Tool: Task/Notebook** | `Task` tool to spawn sub-agents for parallel exploration | 6 tools only (Read, Write, Edit, Glob, Grep, Bash) | Sub-agent delegation is core to Claude Code's effectiveness on complex tasks |
| 10 | **Tool: File search / codebase index** | `codebase-search` semantic + symbol search | Only regex Grep + Glob | No AST/symbol-level search, no embedding-based search |
| 11 | **Tool: Web fetch / browse** | `web_fetch` to read URLs | ✅ Implemented | `src/tools_impl/web_fetch.py` |
| 12 | **Structured output mode** | `@format` / `structured-content` responses | No support for Anthropic's structured output | Needed for reliable JSON/schema-guaranteed model responses |
| 13 | **Image / multimodal input** | Paste images, analyze screenshots | Text-only — no image encoding in provider or agent loop | Anthropic API supports image blocks; not wired |
| 14 | **Project memory / learning** | `.claude/` persistent memory across sessions | `CLAUDE.md` loads on startup but no auto-updating memory file | No incremental learning about project conventions |
| 15 | **Custom slash commands / skills system** | Custom `/` commands defined in config | Hardcoded slash commands only (`src/skills/` is empty) | Users cannot define their own commands |
| 16 | **Permission rules (configurable)** | `permissions.allow` / `permissions.deny` rules in config | Only 3 auto-approve flags (reads, writes, execute) + YOLO mode | No fine-grained per-tool or per-command rules — e.g. "always approve `git status`, always ask for `git push`" |
| 17 | **Git integration tools** | `git` tool for diff, commit, log, branch operations | ✅ Implemented (read-only) | `src/tools_impl/git_tool.py` (status/diff/log/branch/show) |
| 18 | **Cost tracking** | Real-time cost display per token count | `src/cost_tracker.py` is a stub — only records generic "units", never called by agent loop | No API-key cost integration |
| 19 | **Context window awareness per model** | Auto-detects model context limits | ✅ Implemented | `src/model_registry.py` |
| 20 | **Error recovery / retry** | Retries failed API calls with backoff | ✅ Implemented | `AgentLoop` retries with backoff |
| 21 | **Tool sandboxing** | Tools run in controlled environment | Bash runs with full inherited `os.environ` and no filesystem restrictions | `DANGER_PATTERNS` are easy to bypass; no jail/namespace isolation |

---

## 🟡 P2 — Medium-priority: Nice-to-have

| # | Missing Feature | Notes |
|---|----------------|-------|
| 22 | **Plugin system** | `src/plugins/` empty — no way to add third-party tools |
| 23 | **Vim keybindings** | `src/vim/` empty |
| 24 | **Voice input** | `src/voice/` empty |
| 25 | **IDE/server mode (MCP server)** | `src/server/` empty — can't act as MCP server for editors |
| 26 | **Remote runtime / sandbox** | `src/remote_runtime.py` and `src/runtime.py` are stubs |
| 27 | **Bootstrap / project scaffolding** | `src/bootstrap/` empty — no `init` command for new projects |
| 28 | **Keybinding customization** | `src/keybindings/` empty |
| 29 | **Upstream proxy** | `src/upstreamproxy/` empty |
| 30 | **State management** | `src/state/` empty — no undo / checkpoint / rollback |
| 31 | **Migrations system** | `src/migrations/` empty |
| 32 | **Multi-file read tool** | Can only read one file at a time | ✅ Implemented | `ReadMany` tool |
| 33 | **Background tool execution** | No way to run a long command in the background and check output later |
| 34 | **Prompt cache / cached tokens** | Not leveraging Anthropic's `cached_tokens` for CLAUDE.md / system prompt |
| 35 | **Test coverage** | Only 1 test file (`tests/test_porting_workspace.py`); no agent loop / tool / permission tests |

---

## 📁 Empty / Stub Modules (`src/`)

Modules that exist as packages with only `__init__.py`:

```
assistant/    bootstrap/    bridge/       buddy/        cli/
components/   constants/    coordinator/  hooks/        keybindings/
memdir/       migrations/   moreright/    native_ts/    outputStyles/
plugins/      remote/       schemas/      screens/      server/
services/     skills/       state/        types/        upstreamproxy/
utils/        vim/          voice/
```

---

## 🔗 References

- Claude Code docs: https://docs.anthropic.com/en/docs/claude-code/overview
- MCP spec: https://modelcontextprotocol.io/
- Anthropic tool-use API: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
