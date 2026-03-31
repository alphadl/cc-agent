# cc-agent

```text
cc-agent :: tool-use loop | patch | sessions | permissions | multi-provider
```

## 特色
- **并发工具调用** + **会话持久化**（`--resume`）
- **Patch(unified diff, 支持多文件)** / ReadMany / Grep 分页 / Glob exclude
- **默认更安全**：Write 不覆盖（需 `allow_overwrite=true`）；Bash 需审批；写入可按路径前缀 allow/deny

## 快速开始
### Anthropic
```bash
pip install anthropic rich
export ANTHROPIC_API_KEY=...
./cc
```

### OpenRouter
```bash
pip install openai rich
export OPENROUTER_API_KEY=...
./cc --model qwen/qwen3-235b-a22b
```

### OpenAI-compatible
```bash
pip install openai rich
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=...
./cc --model llama-3.3-70b-versatile
```

## 用法
```bash
./cc
./cc -p "summarize this repo"
./cc --model claude-sonnet-4-6
./cc --resume <session-id>
./cc --cwd /path/to/project
./cc --yolo
```

## 工具
Read / ReadMany / Write / Edit / Patch / Glob / Grep / Bash / Git / WebFetch (+ MCP / custom tools)

## 配置（最小）
`.cc-agent.json`：
```json
{
  "model": "claude-sonnet-4-6",
  "parallel_tools": true,
  "auto_approve_reads": true,
  "auto_approve_writes": true,
  "deny_bash_substrings": ["git push", "rm -rf"],
  "deny_write_path_prefixes": ["~/.ssh/", "/etc/"]
}
```

## 免责声明
- 非 Anthropic 官方/无背书；不包含任何 Anthropic 专有源代码
