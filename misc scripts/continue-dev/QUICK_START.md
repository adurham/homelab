# Continue.dev Quick Start Guide

## 🚀 Immediate Setup

### 1. Apply Optimized Configuration
```bash
cp "misc scripts/continue-dev/continue-config.yaml" ~/.continue/config.yaml
```

### 2. Start LM Studio (if not running)
```bash
# Manual method (recommended):
# 1. Open LM Studio from Applications
# 2. Load qwen/qwen3-coder-30b model
# 3. Go to "Local Server" tab
# 4. Click "Start Server"

# Or use startup script:
./misc scripts/continue-dev/start-lm-studio-ai.sh
```

### 3. Verify Setup
```bash
curl -s http://localhost:1234/v1/models | jq -r '.data[] | select(.id | contains("qwen3-coder-30b")) | .id'
```

## 🎯 Quick Test Commands

In VS Code with Continue.dev:

**General Homelab Work:**
```
/homelab "Explain the terraform infrastructure setup"
```

**Terraform Expertise:**
```
/terraform "Review the Tanium client configurations"
```

**Home Assistant Help:**
```
/homeassistant "Review this automation for safety"
```

**Quick Fixes:**
```
/quick-fix "Fix YAML syntax errors"
```

**Complex Debugging:**
```
/debug @terminal @problems Help debug this issue
```

## ✅ What's Optimized

- ✅ 17 enhanced context providers (vs 9 default)
- ✅ Homelab-specific commands (/homelab, /terraform, /homeassistant, /ansible, /quick-fix, /debug)
- ✅ Optimized model parameters (temperature 0.1, context 131k tokens)
- ✅ Project-aware configuration (auto-loads in homelab repo)
- ✅ Performance caching enabled
- ✅ VS Code integration settings

## 📋 Files Modified/Created

**Configuration Files:**
- `misc scripts/continue-dev/continue-config.yaml` - Main optimized config
- `.continue/config.local.yaml` - Project-specific overrides (gitignored)
- `.vscode/settings.json` - VS Code integration

**Scripts:**
- `misc scripts/continue-dev/start-lm-studio-ai.sh` - LM Studio startup script
- `misc scripts/continue-dev/SETUP_GUIDE.md` - Detailed setup guide

**Documentation:**
- `misc scripts/continue-dev/README.md` - Main documentation
- `misc scripts/continue-dev/QUICK_START.md` - This quick start guide

## 🔧 Troubleshooting

**LM Studio won't start:**
1. Open LM Studio manually
2. Download qwen/qwen3-coder-30b model
3. Go to "Local Server" tab
4. Click "Start Server"

**Continue.dev not connecting:**
1. Verify server: `curl http://localhost:1234/v1/models`
2. Check config: `~/.continue/config.yaml` exists
3. Restart VS Code

**Models not showing:**
1. Ensure LM Studio shows the model as "Loaded"
2. Check exact model names match config
3. Restart Continue.dev in VS Code

## 🎉 You're Ready!

Your Continue.dev setup is optimized for homelab development with enterprise-grade AI assistance!
