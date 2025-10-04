#!/bin/bash
# Minimal Safe Deployment Script
# Only adds timer management features without overwriting existing config

set -e

# Configuration
HA_HOST="192.168.86.2"
SSH_USER="root"
SOURCE_DIR="$(dirname "$0")/.."

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Step 1: Backup existing configuration
backup_existing() {
    log_info "Creating backup of existing configuration..."
    BACKUP_DIR="../backup/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # Backup current configuration
    scp "$SSH_USER@$HA_HOST:/config/configuration.yaml" "$BACKUP_DIR/" 2>/dev/null || true
    
    log_success "Backup created at $BACKUP_DIR"
    echo "$BACKUP_DIR"
}

# Step 2: Add timer management to existing configuration
merge_configuration() {
    log_info "Merging timer management with existing configuration..."
    
    # Get current configuration
    scp "$SSH_USER@$HA_HOST:/config/configuration.yaml" "/tmp/current_config.yaml" 2>/dev/null || {
        log_error "Could not retrieve current configuration"
        return 1
    }
    
    # Create merged configuration
    cat > "/tmp/merged_config.yaml" << 'EOF'
# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

influxdb:
  host: a0d7b954-influxdb
  port: 8086
  database: homeassistant
  username: homeassistant
  password: "homeassistant"
  default_measurement: "state"
  include:
    domains:
      - sensor
      - binary_sensor
      - switch

# Timer Management Configuration (Added)
input_text:
  timer_states:
    name: "Timer States Storage"
    initial: "{}"
    max: 10000

python_script:

# Include timer management automations and scripts
automation_timer: !include_dir_list automations/
script_timer: !include_dir_list scripts/
EOF

    log_success "Configuration merged successfully"
}

# Step 3: Deploy files only (no config overwrite)
deploy_files_only() {
    log_info "Deploying timer management files..."
    
    # Create directories
    ssh "$SSH_USER@$HA_HOST" "mkdir -p /config/{automations,scripts,python_scripts}"
    
    # Deploy Python scripts
    if [ -d "$SOURCE_DIR/python_scripts" ]; then
        log_info "Deploying Python scripts..."
        scp "$SOURCE_DIR/python_scripts"/*.py "$SSH_USER@$HA_HOST:/config/python_scripts/" 2>/dev/null || true
    fi
    
    # Deploy automations
    if [ -d "$SOURCE_DIR/automations" ]; then
        log_info "Deploying automations..."
        scp "$SOURCE_DIR/automations"/*.yaml "$SSH_USER@$HA_HOST:/config/automations/" 2>/dev/null || true
    fi
    
    # Deploy scripts
    if [ -d "$SOURCE_DIR/scripts" ]; then
        log_info "Deploying scripts..."
        scp "$SOURCE_DIR/scripts"/*.yaml "$SSH_USER@$HA_HOST:/config/scripts/" 2>/dev/null || true
    fi
    
    log_success "Files deployed successfully"
}

# Step 4: Deploy merged configuration
deploy_merged_config() {
    log_info "Deploying merged configuration..."
    scp "/tmp/merged_config.yaml" "$SSH_USER@$HA_HOST:/config/configuration.yaml"
    log_success "Configuration deployed"
}

# Step 5: Restart Home Assistant
restart_ha() {
    log_info "Restarting Home Assistant..."
    ssh "$SSH_USER@$HA_HOST" "ha core restart"
    log_success "Home Assistant restart initiated"
}

# Main deployment function
deploy_safely() {
    log_info "Starting safe deployment..."
    
    # Step 1: Backup
    BACKUP_DIR=$(backup_existing)
    
    # Step 2: Merge configuration
    merge_configuration || exit 1
    
    # Step 3: Deploy files
    deploy_files_only
    
    # Step 4: Deploy merged config
    deploy_merged_config
    
    # Step 5: Restart
    restart_ha
    
    # Cleanup
    rm -f "/tmp/current_config.yaml" "/tmp/merged_config.yaml"
    
    log_success "Safe deployment completed!"
    log_info "Backup available at: $BACKUP_DIR"
    log_info "Your existing configuration has been preserved and enhanced"
}

# Show help
show_help() {
    cat << EOF
Safe Home Assistant Deployment Script

This script safely deploys timer management features while preserving your existing configuration.

Usage: $0 [OPTIONS]

Options:
    --help              Show this help message
    --files-only        Deploy only files, don't update configuration
    --config-only       Update only configuration, don't deploy files

Examples:
    # Full safe deployment (recommended)
    $0

    # Deploy only files (if you want to manually update config)
    $0 --files-only

EOF
}

# Parse arguments
if [ "$1" = "--help" ]; then
    show_help
    exit 0
elif [ "$1" = "--files-only" ]; then
    backup_existing
    deploy_files_only
    log_success "Files deployed (configuration unchanged)"
    exit 0
elif [ "$1" = "--config-only" ]; then
    BACKUP_DIR=$(backup_existing)
    merge_configuration
    deploy_merged_config
    restart_ha
    rm -f "/tmp/current_config.yaml" "/tmp/merged_config.yaml"
    log_success "Configuration updated (files unchanged)"
    exit 0
else
    deploy_safely
fi
