#!/bin/bash

# Complete Home Assistant Deployment Script
# Deploys automations and imports Grafana dashboard

set -e  # Exit on any error

echo "🚀 COMPLETE HOME ASSISTANT DEPLOYMENT"
echo "====================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the right directory
if [ ! -f "../ha_config.env" ]; then
    print_error "ha_config.env not found. Please run from deployment/ directory."
    exit 1
fi

print_status "Loading environment variables..."
source ../ha_config.env

# Validate required environment variables
if [ -z "$HA_URL" ] || [ -z "$HA_TOKEN" ]; then
    print_error "HA_URL or HA_TOKEN not set in ha_config.env"
    exit 1
fi

print_success "Environment loaded successfully"
echo ""

# Step 1: Deploy automations
print_status "Step 1: Deploying Home Assistant automations..."
echo "Using API endpoint: $HA_URL"
echo ""

if python3 create_grafana_automations_simple.py; then
    print_success "Automations deployed successfully"
else
    print_error "Automation deployment failed"
    exit 1
fi

echo ""

# Step 2: Import Grafana dashboard (optional)
print_status "Step 2: Importing Grafana dashboard..."
echo ""

# Check if Grafana URL is configured
if [ -z "$GRAFANA_URL" ]; then
    print_warning "GRAFANA_URL not configured. Skipping Grafana dashboard import."
    print_warning "To enable Grafana integration, add GRAFANA_URL to ha_config.env"
    echo ""
    print_success "Deployment completed without Grafana integration"
    exit 0
fi

# Check if Grafana credentials are configured
if [ -z "$GRAFANA_USER" ] || [ -z "$GRAFANA_PASSWORD" ]; then
    print_warning "Grafana credentials not configured. Using defaults (admin/admin)"
    print_warning "To set custom credentials, add GRAFANA_USER and GRAFANA_PASSWORD to ha_config.env"
fi

if ./setup_grafana_integration.sh; then
    print_success "Grafana dashboard imported successfully"
else
    print_warning "Grafana dashboard import failed, but automations are deployed"
    print_warning "You can manually import the dashboard later"
fi

echo ""
print_success "🎉 COMPLETE DEPLOYMENT FINISHED!"
echo ""
echo "📊 What was deployed:"
echo "  ✅ Home Assistant automations with Grafana logging"
echo "  ✅ Grafana dashboard with automation metrics"
echo ""
echo "🔍 Next steps:"
echo "  1. Check Home Assistant web UI for new automations"
echo "  2. Access Grafana at $GRAFANA_URL to view metrics"
echo "  3. Monitor automation performance"
echo ""
echo "📚 Documentation:"
echo "  • RULES.md - Deployment rules and procedures"
echo "  • GRAFANA_INTEGRATION_README.md - Grafana setup guide"
echo ""
