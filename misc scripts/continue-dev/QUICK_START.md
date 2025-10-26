# Quick Start: Get Running in 5 Minutes ⚡

## Prerequisites

- ✅ VSCode with Continue.dev extension
- ✅ LM Studio installed
- ✅ Docker Desktop (for MCP servers)
- ✅ M4 MacBook Pro 36GB RAM

## Steps

### 1. Download Models (2-3 min)

In **LM Studio**, download:
- **qwen/qwen3-coder-30b** (primary)
- **qwen/qwen2.5-coder-32b** (backup)
- Optional: **mlx-community/deepseek-coder-33b-instruct-hf-4bit-mlx**

**How**: LM Studio → Search → Search name → Download

### 2. Start LM Studio Server (30 sec)

1. LM Studio → "Local Server" tab
2. Click "Start Server"
3. Load a model (double-click)
4. ✅ Server runs on `http://localhost:1234/v1`

### 3. Copy Config (10 sec)

```bash
cp "misc scripts/continue-dev/continue-config.yaml" ~/.continue/config.yaml
```

### 4. Start Docker (optional, 30 sec)

1. Open Docker Desktop
2. Wait for it to start
3. MCP servers auto-connect

### 5. Restart VSCode (10 sec)

1. Quit VSCode completely (Cmd+Q)
2. Reopen VSCode
3. Open Continue chat (Cmd+L)

## 🎉 Done! Try It

Open Continue and type:
- `/cursor-agent` - Smart agent
- Ask about your code
- Use `@code` to search codebase

## Optional: Add Cloud API Keys

Create `~/.continue/.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
VOYAGE_API_KEY=pa-...
```

Get keys: [Anthropic](https://console.anthropic.com/) | [OpenAI](https://platform.openai.com/) | [Voyage](https://www.voyageai.com/)

## What You Got

✅ 4 local models (free, fast, private)  
✅ 2 cloud models (optional, paid)  
✅ Smart commands (`/cursor-agent`, `/cloud-architect`, etc.)  
✅ MCP servers for enhanced capabilities  
✅ Context providers (`@code`, `@file`, `@tree`, etc.)

## Troubleshooting

**LM Studio not connecting?**  
→ Check server is running, verify `http://localhost:1234/v1`

**Models not showing?**  
→ Verify model names, restart VSCode

**Need help?**  
→ See `README.md` for detailed guide

---

**Next**: Read `README.md` for full setup details | `USAGE_TIPS.md` for best practices
