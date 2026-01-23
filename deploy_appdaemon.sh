#!/bin/bash
# Deploy AppDaemon App to Home Assistant
# Usage: ./deploy_ha.sh

HA_HOST="homeassistant.local"
HA_USER="root"
HA_PORT="2222"
APPS_DIR="/addon_configs/a0d7b954_appdaemon/apps" # Verified path via find command

echo "Deploying to $HA_HOST..."

# Check connectivity & Create Dir
if ! ssh -q -p $HA_PORT -o BatchMode=yes -o StrictHostKeyChecking=no $HA_USER@$HA_HOST "mkdir -p $APPS_DIR"; then
    echo "Error: Cannot connect to $HA_HOST or create directory."
    echo "Make sure you have your SSH key added and the host is reachable."
    exit 1
fi

# Copy files
# Copy files
echo "Copying apps/*.py..."
scp -P $HA_PORT homeassistant/apps/*.py $HA_USER@$HA_HOST:$APPS_DIR/

echo "Copying apps/apps.yaml..."
scp -P $HA_PORT homeassistant/apps/apps.yaml $HA_USER@$HA_HOST:$APPS_DIR/apps.yaml

echo "Deployment complete! Check AppDaemon logs in Home Assistant for startup status."
