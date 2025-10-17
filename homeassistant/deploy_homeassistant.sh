#!/bin/bash

# Enhanced Home Assistant Deployment Script
# Includes backup, validation, and safety checks

set -e  # Exit on any error

# Configuration
HA_HOST="root@homeassistant.local"
HA_PORT="2222"
BACKUP_DIR="/config/backups"
MAX_BACKUPS=10
BACKUP_TIMEOUT=300  # 5 minutes timeout for backup creation
SKIP_HA_BACKUP=false  # Set to true to skip HA backup creation (faster deployment)
SKIP_CONFIG_CHECK=false  # Set to true to skip configuration.yaml change check (for development)

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
    if [ "$SKIP_CONFIG_CHECK" = "true" ]; then
        warn "Skipping configuration.yaml change check (SKIP_CONFIG_CHECK=true)"
        return 0
    fi
    
    log "Checking for external changes to configuration.yaml..."
    
    if [ -f "configuration.yaml" ]; then
        # Calculate hash of local configuration.yaml
        local_hash=$(sha256sum "configuration.yaml" | awk '{print $1}')
        
        # Get hash of remote configuration.yaml
        remote_hash=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "sha256sum /config/configuration.yaml 2>/dev/null | awk '{print \$1}'" || echo "")
        
        # Get hash of git HEAD version
        git_head_hash=$(git ls-tree HEAD configuration.yaml 2>/dev/null | awk '{print $3}' || echo "")
        if [ -n "$git_head_hash" ]; then
            git_head_sha256=$(git show "$git_head_hash" 2>/dev/null | sha256sum | awk '{print $1}' || echo "")
        else
            git_head_sha256=""
        fi
        
        # Check if local file matches git HEAD (no uncommitted changes)
        if [ "$local_hash" = "$git_head_sha256" ]; then
            # No local changes - safe to check for external modifications
            if [ -n "$remote_hash" ] && [ "$remote_hash" != "$git_head_sha256" ]; then
                error "configuration.yaml has been modified externally on the server. Aborting deployment to prevent overwriting changes."
            fi
        else
            # Local file has uncommitted changes - just warn but allow deployment
            if [ -n "$remote_hash" ] && [ "$remote_hash" != "$local_hash" ] && [ "$remote_hash" != "$git_head_sha256" ]; then
                warn "Remote configuration.yaml differs from both local and git HEAD. Proceeding with deployment of local version."
            fi
        fi
        
        log "configuration.yaml is safe to deploy"
    fi
}

# Create backup using HA CLI
create_backup() {
    log "Creating Home Assistant backup..."
    
    # Create backup using HA CLI with timeout
    backup_name="deployment_backup_$(date +%Y%m%d_%H%M%S)"
    log "Starting backup creation: $backup_name (timeout: ${BACKUP_TIMEOUT}s)"
    
    # Use timeout to prevent hanging indefinitely
    if command -v gtimeout >/dev/null 2>&1; then
        # macOS with GNU coreutils
        TIMEOUT_CMD="gtimeout"
    elif command -v timeout >/dev/null 2>&1; then
        # Linux or macOS with timeout
        TIMEOUT_CMD="timeout"
    else
        # Fallback: run without timeout but with warning
        warn "No timeout command available. Backup may hang indefinitely."
        TIMEOUT_CMD=""
    fi
    
    if [ -n "$TIMEOUT_CMD" ]; then
        backup_result=$($TIMEOUT_CMD $BACKUP_TIMEOUT ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha backup new --name $backup_name" 2>&1)
        backup_exit_code=$?
        
        if [ $backup_exit_code -eq 124 ]; then
            error "Backup creation timed out after ${BACKUP_TIMEOUT}s. Continuing with file backup only..."
            return 1
        elif [ $backup_exit_code -ne 0 ]; then
            error "Failed to create backup: $backup_result"
            return 1
        else
            log "Backup created successfully: $backup_name"
        fi
    else
        # Fallback without timeout
        backup_result=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha backup new --name $backup_name" 2>&1)
        if [ $? -eq 0 ]; then
            log "Backup created successfully: $backup_name"
        else
            error "Failed to create backup: $backup_result"
            return 1
        fi
    fi
    
    # Manage backup rotation
    log "Managing backup rotation..."
    ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "
        # Get list of backups, sorted by date (newest first)
        backups=\$(ha backups list --raw-json | jq -r '.data.backups[] | .slug' | sort -r)
        backup_count=\$(echo \"\$backups\" | wc -l)
        
        # Remove old backups if we exceed MAX_BACKUPS
        if [ \$backup_count -gt $MAX_BACKUPS ]; then
            echo \"Removing old backups...\"
            echo \"\$backups\" | tail -n +\$((MAX_BACKUPS + 1)) | while read backup; do
                echo \"Removing backup: \$backup\"
                ha backup remove \$backup
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
    
    # Use shorter timeout for file operations (30 seconds should be plenty)
    file_backup_timeout=30
    
    if [ -n "$TIMEOUT_CMD" ]; then
        backup_result=$($TIMEOUT_CMD $file_backup_timeout ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "
            mkdir -p $backup_path
            
            # Backup existing files
            [ -f /config/automations.yaml ] && cp /config/automations.yaml $backup_path/
            [ -f /config/scripts.yaml ] && cp /config/scripts.yaml $backup_path/
            [ -f /config/scenes.yaml ] && cp /config/scenes.yaml $backup_path/
            [ -f /config/configuration.yaml ] && cp /config/configuration.yaml $backup_path/
            [ -d /config/automations ] && cp -r /config/automations $backup_path/
            [ -d /config/scripts ] && cp -r /config/scripts $backup_path/
            [ -d /config/scenes ] && cp -r /config/scenes $backup_path/
            
            echo \"Files backed up to: $backup_path\"
        " 2>&1)
        
        if [ $? -eq 124 ]; then
            error "File backup timed out after ${file_backup_timeout}s"
            return 1
        elif [ $? -ne 0 ]; then
            error "File backup failed: $backup_result"
            return 1
        else
            log "File backup completed: $backup_result"
        fi
    else
        # Fallback without timeout
        backup_result=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "
            mkdir -p $backup_path
            
            # Backup existing files
            [ -f /config/automations.yaml ] && cp /config/automations.yaml $backup_path/
            [ -f /config/scripts.yaml ] && cp /config/scripts.yaml $backup_path/
            [ -f /config/scenes.yaml ] && cp /config/scenes.yaml $backup_path/
            [ -f /config/configuration.yaml ] && cp /config/configuration.yaml $backup_path/
            [ -d /config/automations ] && cp -r /config/automations $backup_path/
            [ -d /config/scripts ] && cp -r /config/scripts $backup_path/
            [ -d /config/scenes ] && cp -r /config/scenes $backup_path/
            
            echo \"Files backed up to: $backup_path\"
        " 2>&1)
        
        if [ $? -eq 0 ]; then
            log "File backup completed: $backup_result"
        else
            error "File backup failed: $backup_result"
            return 1
        fi
    fi
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
    
    # Copy scene files
    if [ -d "scenes" ]; then
        log "Copying scene files..."
        scp -P $HA_PORT -o StrictHostKeyChecking=no -r scenes/ $HA_HOST:/config/
    fi
    
    # Copy helper files
    if [ -d "helpers" ]; then
        log "Copying helper files..."
        scp -P $HA_PORT -o StrictHostKeyChecking=no -r helpers/ $HA_HOST:/config/
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
    latest_backup=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha backups list --raw-json | jq -r '.data.backups[0].slug'")
    
    if [ -n "$latest_backup" ] && [ "$latest_backup" != "null" ]; then
        log "Restoring from backup: $latest_backup"
        restore_result=$(ssh -p $HA_PORT -o StrictHostKeyChecking=no $HA_HOST "ha backup restore $latest_backup" 2>&1)
        
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
    
    # 3. Create backups (continue even if HA backup fails)
    log "Creating backups..."
    if [ "$SKIP_HA_BACKUP" = "true" ]; then
        warn "Skipping HA backup creation (SKIP_HA_BACKUP=true)"
    else
        if create_backup; then
            log "HA backup created successfully"
        else
            warn "HA backup failed, continuing with file backup only"
        fi
    fi
    
    # Always create file backups regardless of HA backup status
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

# Help function
show_help() {
    echo "Home Assistant Deployment Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --skip-ha-backup      Skip Home Assistant backup creation (faster deployment)"
    echo "  --skip-config-check   Skip configuration.yaml change check (for development)"
    echo "  --backup-timeout N    Set backup timeout in seconds (default: 300)"
    echo "  --help                Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  SKIP_HA_BACKUP      Set to 'true' to skip HA backup creation"
    echo "  SKIP_CONFIG_CHECK   Set to 'true' to skip configuration.yaml change check"
    echo "  BACKUP_TIMEOUT      Set backup timeout in seconds"
    echo ""
    echo "Examples:"
    echo "  $0                           # Normal deployment with full backup"
    echo "  $0 --skip-ha-backup          # Skip HA backup for faster deployment"
    echo "  $0 --skip-config-check       # Skip config check for development"
    echo "  $0 --backup-timeout 600      # Set 10 minute backup timeout"
    echo ""
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-ha-backup)
            SKIP_HA_BACKUP=true
            shift
            ;;
        --skip-config-check)
            SKIP_CONFIG_CHECK=true
            shift
            ;;
        --backup-timeout)
            BACKUP_TIMEOUT="$2"
            shift 2
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Run main function
main "$@"