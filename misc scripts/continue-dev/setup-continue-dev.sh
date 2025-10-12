#!/bin/bash

# Continue.dev Setup Script for Cursor-like Functionality
# This script sets up Continue.dev VSCode extension with local and cloud AI models

set -e

echo "🚀 Setting up Continue.dev with Cursor-like functionality..."

# Check if VSCode is installed
if ! command -v code &> /dev/null; then
    echo "❌ VSCode is not installed or not in PATH"
    echo "Please install VSCode and ensure 'code' command is available"
    exit 1
fi

# Install Continue.dev extension
echo "📦 Installing Continue.dev extension..."
code --install-extension continue.continue

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "⚠️  Ollama is not installed. Installing Ollama..."
    
    # Install Ollama (macOS)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        curl -fsSL https://ollama.ai/install.sh | sh
    else
        echo "Please install Ollama manually from https://ollama.ai"
        exit 1
    fi
fi

# Start Ollama service
echo "🔄 Starting Ollama service..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to start
echo "⏳ Waiting for Ollama to start..."
sleep 5

# Pull optimized models for M4 Max with 36GB RAM
echo "📥 Pulling AI models optimized for your M4 Max with 36GB RAM..."

# Large models - your M4 Max can handle these easily
echo "  - Pulling Llama 3.1 70B (Best overall performance)..."
ollama pull llama3.1:70b

echo "  - Pulling CodeLlama 70B (Code-specialized)..."
ollama pull codellama:70b

# Medium models for faster responses when needed
echo "  - Pulling DeepSeek Coder 33B (Fast & smart)..."
ollama pull deepseek-coder:33b

echo "  - Pulling Qwen2.5 Coder 32B (Very fast responses)..."
ollama pull qwen2.5-coder:32b

# Smaller models for ultra-fast responses
echo "  - Pulling Llama 3.1 8B (Ultra fast for quick tasks)..."
ollama pull llama3.1:8b

echo "  - Pulling CodeLlama 13B (Balanced speed/quality)..."
ollama pull codellama:13b

# Embedding model for codebase understanding
echo "  - Pulling embedding model for codebase search..."
ollama pull nomic-embed-text

# Stop Ollama service (it will restart automatically when needed)
kill $OLLAMA_PID 2>/dev/null || true

# Create Continue config directory
CONTINUE_DIR="$HOME/.continue"
mkdir -p "$CONTINUE_DIR"

# Copy the configuration
echo "⚙️  Setting up Continue.dev configuration..."
cp continue-config.json "$CONTINUE_DIR/config.json"

echo "✅ Setup complete!"
echo ""
echo "🔧 Next steps:"
echo "1. Restart VSCode to load the extension"
echo ""
echo "2. Open Command Palette (Cmd+Shift+P) and try:"
echo "   - 'Continue: Open Continue' - Open Continue chat"
echo "   - 'Continue: Run Custom Command' - Use custom commands"
echo ""
echo "🎯 Available models (all local, no API keys needed!):"
echo "   - Llama 3.1 70B: Best overall coding performance"
echo "   - CodeLlama 70B: Specialized for code generation"
echo "   - DeepSeek Coder 33B: Fast & smart for debugging"
echo "   - Qwen2.5 Coder 32B: Very fast responses"
echo "   - Llama 3.1 8B: Ultra fast for quick tasks"
echo "   - CodeLlama 13B: Balanced speed/quality"
echo ""
echo "🎮 Available custom commands:"
echo "   - cursor-agent: Autonomous coding agent"
echo "   - explain-codebase: Comprehensive codebase analysis"
echo "   - refactor-project: Code refactoring and improvements"
echo "   - debug-issue: Advanced debugging assistance"
echo "   - write-tests: Generate comprehensive test suites"
echo "   - security-audit: Security analysis and remediation"
echo "   - performance-optimization: Performance analysis"
echo "   - documentation-generator: Generate project docs"
echo "   - code-review: Thorough code review"
echo "   - migration-assistant: Framework/version migrations"
echo ""
echo "💡 Tips for M4 Max optimization:"
echo "   - Start with Llama 3.1 70B for best quality"
echo "   - Use CodeLlama 70B for code-specific tasks"
echo "   - Switch to smaller models for faster iterations"
echo "   - All models run locally - complete privacy!"
echo "   - Your 36GB RAM can handle multiple large models"
