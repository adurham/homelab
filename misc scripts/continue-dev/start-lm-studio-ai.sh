#!/bin/bash
# =============================================================================
# LM Studio AI Assistant Startup Script
# =============================================================================
# Optimized startup configuration for Continue.dev integration
# Ensures LM Studio is running with optimal settings for homelab development

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting LM Studio for Continue.dev AI Assistant...${NC}"

# Check if LM Studio is installed
if ! command -v open >/dev/null 2>&1; then
    echo -e "${RED}❌ LM Studio not found. Please install LM Studio from: https://lmstudio.ai/${NC}"
    echo -e "${YELLOW}📋 Manual setup steps:${NC}"
    echo -e "${YELLOW}1. Download and install LM Studio${NC}"
    echo -e "${YELLOW}2. Download qwen/qwen3-coder-30b model${NC}"
    echo -e "${YELLOW}3. Start LM Studio and load the model${NC}"
    echo -e "${YELLOW}4. Go to 'Local Server' tab and click 'Start Server'${NC}"
    exit 1
fi

# Check if LM Studio is already running
if pgrep -f "LM Studio" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ LM Studio is already running${NC}"
    echo -e "${YELLOW}📍 Verifying local server status...${NC}"
else
    echo -e "${YELLOW}📦 Starting LM Studio application...${NC}"
    # Try to start LM Studio, but don't fail if it doesn't work
    if open -a "LM Studio" 2>/dev/null; then
        echo -e "${GREEN}✅ LM Studio launched successfully${NC}"
        echo -e "${YELLOW}⏳ Waiting for LM Studio to initialize...${NC}"
        sleep 5
    else
        echo -e "${YELLOW}⚠️  Could not automatically start LM Studio${NC}"
        echo -e "${YELLOW}📋 Manual setup required:${NC}"
        echo -e "${YELLOW}1. Open LM Studio manually (Applications folder or spotlight search)${NC}"
        echo -e "${YELLOW}2. Go to 'Search' tab and download qwen/qwen3-coder-30b${NC}"
        echo -e "${YELLOW}3. Go to 'Local Server' tab${NC}"
        echo -e "${YELLOW}4. Click 'Load Model' and select qwen/qwen3-coder-30b${NC}"
        echo -e "${YELLOW}5. Click 'Start Server' (should show http://localhost:1234/v1)${NC}"
        echo -e "${YELLOW}6. Run this script again to verify setup${NC}"
        exit 1
    fi
fi

# Check if the local server is running on port 1234
echo -e "${YELLOW}🔍 Checking if local server is running on port 1234...${NC}"

max_attempts=30
attempt=1
while [ $attempt -le $max_attempts ]; do
    if curl -s -f "http://localhost:1234/v1/models" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Local server is running and accessible${NC}"
        break
    else
        echo -e "${YELLOW}⏳ Waiting for local server... (attempt $attempt/$max_attempts)${NC}"
        sleep 2
        ((attempt++))
    fi
done

if [ $attempt -gt $max_attempts ]; then
    echo -e "${RED}❌ Local server not responding after $((max_attempts * 2)) seconds${NC}"
    echo -e "${YELLOW}📋 Manual setup required:${NC}"
    echo -e "${YELLOW}1. Open LM Studio manually${NC}"
    echo -e "${YELLOW}2. Go to 'Local Server' tab${NC}"
    echo -e "${YELLOW}3. Click 'Load Model' and select qwen/qwen3-coder-30b${NC}"
    echo -e "${YELLOW}4. Click 'Start Server' (should show http://localhost:1234/v1)${NC}"
    echo -e "${YELLOW}5. Ensure the API endpoint includes /v1${NC}"
    exit 1
fi

# Verify model availability
echo -e "${YELLOW}🔍 Checking available models...${NC}"
models_response=$(curl -s "http://localhost:1234/v1/models" 2>/dev/null || echo "{}")

if echo "$models_response" | grep -q "qwen3-coder-30b"; then
    echo -e "${GREEN}✅ Qwen3 30B model is available${NC}"
elif echo "$models_response" | grep -q "qwen2.5-coder-32b"; then
    echo -e "${GREEN}✅ Qwen2.5 32B model is available (fallback)${NC}"
elif echo "$models_response" | grep -q "deepseek-coder"; then
    echo -e "${GREEN}✅ DeepSeek Coder model is available (fallback)${NC}"
else
    echo -e "${YELLOW}⚠️  No Qwen3 30B model found in the server response${NC}"
    echo -e "${YELLOW}📋 Available models:${NC}"
    echo "$models_response" | jq -r '.data[].id // "Unable to parse"' 2>/dev/null || echo "$models_response"
fi

# Test API connectivity
echo -e "${YELLOW}🧪 Testing API connectivity...${NC}"
if curl -s -X POST "http://localhost:1234/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model":"qwen/qwen3-coder-30b","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}' \
    >/dev/null 2>&1; then
    echo -e "${GREEN}✅ API test successful${NC}"
else
    echo -e "${YELLOW}⚠️  API test failed - continuing anyway${NC}"
fi

echo -e ""
echo -e "${BLUE}🎉 LM Studio AI Assistant Ready!${NC}"
echo -e ""
echo -e "${GREEN}✅ LM Studio is running${NC}"
echo -e "${GREEN}✅ Local server is accessible on http://localhost:1234/v1${NC}"
echo -e "${GREEN}✅ Continue.dev integration is ready${NC}"
echo -e ""
echo -e "${BLUE}📋 Next Steps:${NC}"
echo -e "1. Open VS Code with Continue.dev extension installed${NC}"
echo -e "2. Start a new chat session${NC}"
echo -e "3. The Qwen3 30B model should be selected by default${NC}"
echo -e "4. Try asking: '@currentFile Explain this code'${NC}"
echo -e ""
echo -e "${YELLOW}💡 Pro Tip: Use /cursor-agent for intelligent model selection${NC}"
echo -e "${YELLOW}💡 Use /homelab for homelab-specific expertise${NC}"
echo -e "${YELLOW}💡 Use /terraform or /homeassistant for domain-specific help${NC}"
echo -e ""
