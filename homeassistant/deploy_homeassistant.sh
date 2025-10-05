#!/bin/bash

# Enhanced Home Assistant Deployment Script
# Includes backup, validation, and safety checks

set -e  # Exit on any error

# Configuration
HA_HOST="root@homeassistant.local"
HA_PORT="2222"
BACKUP_DIR="/config/backups"
MAX_BACKUPS=10

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
    exit 1
}

# Check if configuration.yaml has been modified externally
check_config_changes() {
    log "Checking for external changes to configuration.yaml..."
    
    if [ -f "configuration.yaml" ]; then
        # Calculate hash of local configuration.yaml
        local_hash=$(sha256sum "configuration.yaml" | awk '{print $1}')
        
        # Get hash of remote configuration.yaml
        remote_hash=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "sha256sum /config/configuration.yaml 2>/dev/null | awk '{print \$1}'" || echo "")
        
        if [ -n "$remote_hash" ] && [ "$local_hash" != "$remote_hash" ]; then
            error "configuration.yaml has been modified externally. Aborting deployment to prevent overwriting changes."
        fi
        
        log "configuration.yaml is safe to deploy"
    fi
}

# Create backup using HA CLI
create_backup() {
    log "Creating Home Assistant backup..."
    
    # Create backup using HA CLI
    backup_name="deployment_backup_$(date +%Y%m%d_%H%M%S)"
    backup_result=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha core backup --name $backup_name" 2>&1)
    
    if [ $? -eq 0 ]; then
        log "Backup created successfully: $backup_name"
    else
        error "Failed to create backup: $backup_result"
    fi
    
    # Manage backup rotation
    log "Managing backup rotation..."
    ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "
        # Get list of backups, sorted by date (newest first)
        backups=\$(ha core backup list --json | jq -r '.data.backups[] | .slug' | sort -r)
        backup_count=\$(echo \"\$backups\" | wc -l)
        
        # Remove old backups if we exceed MAX_BACKUPS
        if [ \$backup_count -gt $MAX_BACKUPS ]; then
            echo \"Removing old backups...\"
            echo \"\$backups\" | tail -n +\$((MAX_BACKUPS + 1)) | while read backup; do
                echo \"Removing backup: \$backup\"
                ha core backup remove \$backup
            done
        fi
    "
}

# Validate configuration
validate_config() {
    log "Validating Home Assistant configuration..."
    
    # Check local YAML syntax using virtual environment
    if [ -f "venv/bin/yamllint" ]; then
        log "Running yamllint on local files..."
        if ! ./venv/bin/yamllint .; then
            error "yamllint found issues in local files. Fix them before deploying."
        fi
        log "Local YAML validation passed"
    else
        warn "yamllint not found in virtual environment. Install with: pip install yamllint"
    fi
    
    # Note: We don't check remote config here because we're about to overwrite it
    # The remote check happens after deployment to verify the new config works
    log "Local configuration validation completed"
}

# Backup existing files
backup_existing_files() {
    log "Backing up existing files..."
    
    # Create backup directory with timestamp
    backup_timestamp=$(date +%Y%m%d_%H%M%S)
    backup_path="$BACKUP_DIR/manual_backup_$backup_timestamp"
    
    ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "
        mkdir -p $backup_path
        
        # Backup existing files
        [ -f /config/automations.yaml ] && cp /config/automations.yaml $backup_path/
        [ -f /config/scripts.yaml ] && cp /config/scripts.yaml $backup_path/
        [ -f /config/configuration.yaml ] && cp /config/configuration.yaml $backup_path/
        [ -d /config/automations ] && cp -r /config/automations $backup_path/
        [ -d /config/scripts ] && cp -r /config/scripts $backup_path/
        
        echo \"Files backed up to: $backup_path\"
    "
}

# Deploy files
deploy_files() {
    log "Deploying files to Home Assistant..."
    
    # Copy main configuration files
    log "Copying configuration files..."
    scp -P $HA_PORT -o StrictHostKeyChecking=no automations.yaml $HA_HOST:/config/
    scp -P $HA_PORT -o StrictHostKeyChecking=no scripts.yaml $HA_HOST:/config/
    
    # Copy other configuration files if they exist
    if [ -f "configuration.yaml" ]; then
        log "Copying configuration.yaml..."
        scp -P $HA_PORT -o StrictHostKeyChecking=no configuration.yaml $HA_HOST:/config/
    fi
    
    if [ -f "groups.yaml" ]; then
        log "Copying groups.yaml..."
        scp -P $HA_PORT -o StrictHostKeyChecking=no groups.yaml $HA_HOST:/config/
    fi
    
    if [ -f "scenes.yaml" ]; then
        log "Copying scenes.yaml..."
        scp -P $HA_PORT -o StrictHostKeyChecking=no scenes.yaml $HA_HOST:/config/
    fi
    
    # Copy automation files
    if [ -d "automations" ]; then
        log "Copying automation files..."
        scp -P $HA_PORT -o StrictHostKeyChecking=no -r automations/ $HA_HOST:/config/
    fi
    
    # Copy script files
    if [ -d "scripts" ]; then
        log "Copying script files..."
        scp -P $HA_PORT -o StrictHostKeyChecking=no -r scripts/ $HA_HOST:/config/
    fi
}

# Validate deployed configuration and restore if needed
validate_and_restore_if_needed() {
    log "Validating deployed configuration..."
    
    # Check configuration using HA CLI
    log "Running ha core check on deployed configuration..."
    check_result=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha core check" 2>&1)
    
    if [ $? -eq 0 ]; then
        log "Deployed configuration validation passed"
        return 0
    else
        error "Deployed configuration validation failed: $check_result"
        log "Restoring from backup..."
        restore_from_backup
        return 1
    fi
}

# Restore from backup
restore_from_backup() {
    log "Restoring from HA CLI backup..."
    
    # Get the most recent backup
    latest_backup=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha core backup list --json | jq -r '.data.backups[0].slug'")
    
    if [ -n "$latest_backup" ] && [ "$latest_backup" != "null" ]; then
        log "Restoring from backup: $latest_backup"
        restore_result=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha core backup restore $latest_backup" 2>&1)
        
        if [ $? -eq 0 ]; then
            log "Backup restored successfully"
        else
            error "Failed to restore backup: $restore_result"
        fi
    else
        error "No backup found to restore from"
    fi
}

# Restart Home Assistant
restart_homeassistant() {
    log "Restarting Home Assistant..."
    ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha core restart"
    
    # Wait for restart to complete
    log "Waiting for Home Assistant to restart..."
    sleep 30
    
    # Check if Home Assistant is running
    log "Checking Home Assistant status..."
    status_result=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha core info" 2>&1)
    
    if [ $? -eq 0 ]; then
        log "Home Assistant is running successfully"
    else
        error "Home Assistant failed to start: $status_result"
    fi
}

# Main deployment function
main() {
    log "Starting Home Assistant deployment..."
    
    # 1. Pre-deployment checks
    check_config_changes
    
    # 2. Validate local configuration FIRST
    validate_config
    
    # 3. Create backups
    create_backup
    backup_existing_files
    
    # 4. Deploy files
    deploy_files
    
    # 5. Validate deployed configuration and restore if needed
    if validate_and_restore_if_needed; then
        # 6. Restart Home Assistant only if validation passed
        restart_homeassistant
        log "Deployment completed successfully!"
        log "Backup created: deployment_backup_$(date +%Y%m%d_%H%M%S)"
    else
        error "Deployment failed - configuration validation failed and backup restored"
        exit 1
    fi
}

# Run main function
main "$@"