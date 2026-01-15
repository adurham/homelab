#!/bin/bash
# configure_cluster.sh
# Automates the Tanium Cluster creation using the Appliance CLI.
# Usage: ./configure_cluster.sh

# Configuration
TS_01_IP="172.16.0.51"
TS_02_IP="172.16.0.52"
TMS_01_IP="172.16.0.53"
TMS_02_IP="172.16.0.54"
# Users
USER="tanadmin"
PASS="Tanium1" # Note: In production, consider using ssh keys or sshpass prompt

# Color codes
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}Starting Tanium Cluster Configuration...${NC}"

# Prerequisites Check: sshpass
if ! command -v sshpass &> /dev/null; then
    echo "sshpass is required but not installed. Please install it (brew install sshpass)."
    exit 1
fi

# Function to run command on TS-01
run_cli() {
    sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$USER@$TS_01_IP" "$1"
}

# 1. Create Array on TS-01
echo -e "${GREEN}[1/4] Creating Array on ts-01...${NC}"
run_cli "create array 'TaniumCluster' $TS_01_IP"

# 2. Add Members
echo -e "${GREEN}[2/4] Adding Array Members...${NC}"
echo "Adding ts-02 ($TS_02_IP)..."
run_cli "add array member $TS_02_IP"

echo "Adding tms-01 ($TMS_01_IP)..."
run_cli "add array member $TMS_01_IP"

echo "Adding tms-02 ($TMS_02_IP)..."
run_cli "add array member $TMS_02_IP"

# 3. Assign Roles
echo -e "${GREEN}[3/4] Assigning Roles...${NC}"
# We construct the JSON payload for role assignment directly
# This requires knowing the exact format. Based on standard behaviors:
# Role 2 = Tanium Server, Role 3 = Module Server
# We used 'array assign roles apply' with input redirection in the plan.
# Here we will try to build it dynamically or use the interactive mode if possible,
# but CLI automation usually requires a file.
# Since we can't easily upload a file via this script without SCP,
# we'll assume we can pipe it.

ROLES_JSON_CONTENT='[
  {
    "id": 2,
    "members": [
      "'$TS_01_IP'",
      "'$TS_02_IP'"
    ]
  },
  {
    "id": 3,
    "members": [
      "'$TMS_01_IP'",
      "'$TMS_02_IP'"
    ]
  }
]'

echo "Applying Roles Configuration..."
echo "$ROLES_JSON_CONTENT" | sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$USER@$TS_01_IP" "array assign roles apply"

# 4. Verification
echo -e "${GREEN}[4/4] Verifying Cluster Status...${NC}"
run_cli "show system-status"

echo -e "${GREEN}Configuration Complete!${NC}"
