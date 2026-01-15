#!/bin/bash
set -e

echo "🚀 Bootstrapping Development Environment..."

# Function to check command existence
command_exists () {
    type "$1" &> /dev/null ;
}

# 1. Check/Install Python Dependencies
echo "📦 Checking Python dependencies..."
if ! command_exists pip3; then
    echo "❌ pip3 not found. Please install Python 3."
    exit 1
fi

pip3 install ansible-lint pre-commit --upgrade

# 2. Install Pre-commit Hooks
echo "🪝 Installing git hooks..."
if [ -f ".pre-commit-config.yaml" ]; then
    pre-commit install
else
    echo "⚠️ .pre-commit-config.yaml not found. Skipping hook installation."
fi

echo "✅ Environment Setup Complete!"
echo "   Run 'pre-commit run --all-files' to verify your codebase."
