#!/bin/bash

# Setup script for Local + Cloud AI with Continue.dev
# This script helps set up the hybrid AI configuration

set -e

echo "🚀 Continue.dev Local + Cloud AI Setup"
echo "======================================"
echo ""

# Check if Continue.dev directory exists
CONTINUE_DIR="$HOME/.continue"
if [ ! -d "$CONTINUE_DIR" ]; then
    mkdir -p "$CONTINUE_DIR"
    echo "✅ Created Continue.dev directory"
fi

# Copy config
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONFIG_FILE="$SCRIPT_DIR/continue-config.yaml"

if [ -f "$CONFIG_FILE" ]; then
    cp "$CONFIG_FILE" "$CONTINUE_DIR/config.yaml"
    echo "✅ Copied configuration to ~/.continue/config.yaml"
else
    echo "❌ Error: continue-config.yaml not found in $SCRIPT_DIR"
    exit 1
fi

# Create .env.example if it doesn't exist
ENV_EXAMPLE="$CONTINUE_DIR/.env.example"
if [ -f "$SCRIPT_DIR/.env.example" ] && [ ! -f "$ENV_EXAMPLE" ]; then
    cp "$SCRIPT_DIR/.env.example" "$ENV_EXAMPLE"
    echo "✅ Created .env.example file"
fi

# Check for existing .env
ENV_FILE="$CONTINUE_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo ""
    echo "📝 Next steps:"
    echo "1. Create $ENV_FILE with your API keys"
    echo "2. Copy from $ENV_EXAMPLE (or $SCRIPT_DIR/.env.example)"
    echo "3. Add your Anthropic, OpenAI, and Voyage API keys"
    echo ""
else
    echo "✅ Found existing .env file"
fi

# Check for LM Studio
if command -v lmstudio &> /dev/null || open -Ra "LM Studio" 2>/dev/null; then
    echo "✅ LM Studio is installed"
    echo "   Please start LM Studio server and load a model"
    echo "   Important: Server must run on http://localhost:1234/v1"
else
    echo "⚠️  LM Studio not found"
    echo "   Download from: https://lmstudio.ai/"
fi

# Check for Docker
if command -v docker &> /dev/null; then
    if docker info &> /dev/null; then
        echo "✅ Docker is running (MCP servers available)"
    else
        echo "⚠️  Docker is installed but not running"
        echo "   Start Docker Desktop for MCP server integration"
    fi
else
    echo "ℹ️  Docker not found (optional for MCP servers)"
    echo "   Download from: https://www.docker.com/products/docker-desktop/"
fi

echo ""
echo "✨ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Download models in LM Studio (see QUICK_START.md for recommended models)"
echo "2. Start LM Studio server on port 1234"
echo "3. Add API keys to $CONTINUE_DIR/.env (optional, for cloud models)"
echo "4. Start Docker Desktop (optional, for MCP servers)"
echo "5. Restart VSCode to load configuration"
echo ""
echo "For detailed instructions, see README.md"
echo "For quick start, see QUICK_START.md"
