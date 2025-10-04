#!/bin/bash
# Home Assistant Configuration Deployment Script
# Simple deployment script for Home Assistant Green box

set -e

# Configuration
HA_HOST="homeassistant.local"
HA_URL="http://homeassistant.local:8123"
SSH_USER="homeassistant"
HA_TOKEN=""
SOURCE_DIR="$(dirname "$0")/.."
DEPLOY_METHOD=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
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

show_help() {
    cat << EOF
Home Assistant Configuration Deployment Script

Usage: $0 [OPTIONS]

Options:
    --ssh-user USER     SSH username for deployment (default: homeassistant)
    --token TOKEN       Home Assistant API token
    --host HOST         Home Assistant hostname (default: homeassistant.local)
    --method METHOD     Deployment method: ssh, api, or ansible (default: auto-detect)
    --test-only         Only test connection, don't deploy
    --help              Show this help message

Examples:
    # Deploy via SSH (uses homeassistant user by default)
    $0

    # Deploy via SSH with custom user
    $0 --ssh-user homeassistant

    # Deploy via API
    $0 --token your_long_lived_token

    # Deploy via Ansible
    $0 --method ansible

    # Test connection only
    $0 --test-only

EOF
}

test_connection() {
    log_info "Testing connection to Home Assistant..."
    
    if command -v curl >/dev/null 2>&1; then
        if curl -s --connect-timeout 5 "$HA_URL/api/" >/dev/null; then
            log_success "Home Assistant is accessible at $HA_URL"
            return 0
        fi
    fi
    
    log_error "Cannot connect to Home Assistant at $HA_URL"
    return 1
}

deploy_via_ssh() {
    log_info "Deploying via SSH to $SSH_USER@$HA_HOST"
    
    # Test SSH connection
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_USER@$HA_HOST" "echo 'SSH connection successful'" >/dev/null 2>&1; then
        log_error "SSH connection failed. Please check your SSH setup."
        return 1
    fi
    
    log_success "SSH connection successful"
    
    # Create directories
    ssh "$SSH_USER@$HA_HOST" "mkdir -p /config/{automations,scripts,python_scripts}"
    
    # Deploy files
    log_info "Deploying Python scripts..."
    scp "$SOURCE_DIR/python_scripts"/*.py "$SSH_USER@$HA_HOST:/config/python_scripts/" 2>/dev/null || true
    
    log_info "Deploying automations..."
    scp "$SOURCE_DIR/automations"/*.yaml "$SSH_USER@$HA_HOST:/config/automations/" 2>/dev/null || true
    
    log_info "Deploying scripts..."
    scp "$SOURCE_DIR/scripts"/*.yaml "$SSH_USER@$HA_HOST:/config/scripts/" 2>/dev/null || true
    
    log_info "Updating configuration..."
    scp "$SOURCE_DIR/configuration.yaml" "$SSH_USER@$HA_HOST:/config/configuration.yaml" 2>/dev/null || true
    
    log_info "Restarting Home Assistant..."
    ssh "$SSH_USER@$HA_HOST" "ha core restart"
    
    log_success "Deployment completed via SSH"
}

deploy_via_api() {
    log_info "Deploying via Home Assistant API"
    
    if [ -z "$HA_TOKEN" ]; then
        log_error "API token is required for API deployment"
        return 1
    fi
    
    # Use Python script for API deployment
    if command -v python3 >/dev/null 2>&1; then
        python3 "$(dirname "$0")/deploy_to_ha.py" --token "$HA_TOKEN" --ha-url "$HA_URL" --source-dir "$SOURCE_DIR"
    else
        log_error "Python 3 is required for API deployment"
        return 1
    fi
}

deploy_via_ansible() {
    log_info "Deploying via Ansible"
    
    if ! command -v ansible-playbook >/dev/null 2>&1; then
        log_error "Ansible is required for Ansible deployment"
        return 1
    fi
    
    cd "$(dirname "$0")"
    ansible-playbook -i inventory.yml deploy_homeassistant.yml
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --ssh-user)
            SSH_USER="$2"
            DEPLOY_METHOD="ssh"
            shift 2
            ;;
        --token)
            HA_TOKEN="$2"
            DEPLOY_METHOD="api"
            shift 2
            ;;
        --host)
            HA_HOST="$2"
            HA_URL="http://$2:8123"
            shift 2
            ;;
        --method)
            DEPLOY_METHOD="$2"
            shift 2
            ;;
        --test-only)
            TEST_ONLY=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Auto-detect deployment method if not specified
if [ -z "$DEPLOY_METHOD" ]; then
    if [ -n "$SSH_USER" ]; then
        DEPLOY_METHOD="ssh"
    elif [ -n "$HA_TOKEN" ]; then
        DEPLOY_METHOD="api"
    elif command -v ansible-playbook >/dev/null 2>&1; then
        DEPLOY_METHOD="ansible"
    else
        log_error "No deployment method specified and none could be auto-detected"
        log_info "Please specify --ssh-user, --token, or --method"
        exit 1
    fi
fi

# Test connection
if ! test_connection; then
    exit 1
fi

if [ "$TEST_ONLY" = true ]; then
    log_success "Connection test passed"
    exit 0
fi

# Deploy based on method
case $DEPLOY_METHOD in
    ssh)
        if [ -z "$SSH_USER" ]; then
            log_error "SSH user is required for SSH deployment"
            exit 1
        fi
        deploy_via_ssh
        ;;
    api)
        deploy_via_api
        ;;
    ansible)
        deploy_via_ansible
        ;;
    *)
        log_error "Unknown deployment method: $DEPLOY_METHOD"
        exit 1
        ;;
esac

log_success "Deployment completed successfully!"
log_info "You can now access Home Assistant at $HA_URL"
