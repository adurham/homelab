#!/bin/bash
# Deploy Core Configuration to Home Assistant
# Usage: ./deploy_ha.sh

HA_HOST="192.168.86.2"
HA_USER="root"
HA_PORT="2222"
CONFIG_DIR="/config"

echo "Deploying Core Config to $HA_HOST..."

# Check connectivity
if ! ssh -i $HOME/.ssh/id_ansible -q -p $HA_PORT -o BatchMode=yes -o StrictHostKeyChecking=no $HA_USER@$HA_HOST "ls $CONFIG_DIR > /dev/null"; then
    echo "Error: Cannot connect to $HA_HOST or find $CONFIG_DIR."
    echo "Make sure you have your SSH key added and the host is reachable."
    exit 1
fi

# Sync Automations Dir
echo "Syncing automations directory..."
scp -i $HOME/.ssh/id_ansible -P $HA_PORT -r homeassistant/automations/ $HA_USER@$HA_HOST:$CONFIG_DIR/

# Sync Core Files
echo "Syncing configuration files..."
# scp -i $HOME/.ssh/id_ansible -P $HA_PORT homeassistant/automations.yaml $HA_USER@$HA_HOST:$CONFIG_DIR/
scp -i $HOME/.ssh/id_ansible -P $HA_PORT homeassistant/configuration.yaml $HA_USER@$HA_HOST:$CONFIG_DIR/
scp -i $HOME/.ssh/id_ansible -P $HA_PORT homeassistant/scripts.yaml $HA_USER@$HA_HOST:$CONFIG_DIR/
scp -i $HOME/.ssh/id_ansible -P $HA_PORT homeassistant/sensors.yaml $HA_USER@$HA_HOST:$CONFIG_DIR/
scp -i $HOME/.ssh/id_ansible -P $HA_PORT homeassistant/input_datetime.yaml $HA_USER@$HA_HOST:$CONFIG_DIR/
# scp -i $HOME/.ssh/id_ansible -P $HA_PORT homeassistant/scenes.yaml $HA_USER@$HA_HOST:$CONFIG_DIR/

echo "Deployment complete!"
echo "Restarting Home Assistant Core..."
ssh -i $HOME/.ssh/id_ansible -p $HA_PORT $HA_USER@$HA_HOST "ha core restart"
echo "Done. Please wait for HA to come back online."
