#!/bin/bash

# Setup script for Home Assistant deployment environment
# Creates virtual environment and installs required packages

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

# Check if Python 3 is available
if ! command -v python3 >/dev/null 2>&1; then
    warn "Python 3 not found. Please install Python 3 first."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    log "Creating Python virtual environment..."
    python3 -m venv venv
else
    log "Virtual environment already exists"
fi

# Activate virtual environment and install packages
log "Installing required packages..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

log "Virtual environment setup complete!"
log "To activate manually: source venv/bin/activate"
log "To run deployment: ./deploy_homeassistant.sh"
