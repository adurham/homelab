#!/usr/bin/env bash
# Retry the Midea dehumidifier config flow periodically.
# Once the Midea cloud session clears, this will succeed and create the config entry.
# Sends a notification via HA when it succeeds.
set -euo pipefail

source /Users/adam.durham/.hermes/.env 2>/dev/null || true
HASS_URL="${HASS_URL:-http://192.168.86.2:8123}"
HASS_TOKEN="${HASS_TOKEN:?need HASS_TOKEN}"

LOG_TAG="midea-retry"
log() { logger -t "$LOG_TAG" -- "$*"; echo "[$(date -Is)] $*"; >&2; }

# Get Midea credentials from 1Password
MIDEA_PASS=$(op item get lew43eybfdvuxowz6jbnbzcxwi --field password --reveal 2>/dev/null) || {
  log "ERROR: cannot get Midea password from 1Password"
  exit 1
}

# Start a config flow
FLOW=$(curl -s -X POST "$HASS_URL/api/config/config_entries/flow" \
  -H "Authorization: Bearer $HASS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"handler":"midea_dehumidifier_lan"}')
FLOW_ID=$(echo "$FLOW" | python3 -c "import json,sys; print(json.load(sys.stdin).get('flow_id',''))" 2>/dev/null)

if [ -z "$FLOW_ID" ]; then
  log "ERROR: could not start config flow"
  exit 1
fi

# Submit credentials
RESULT=$(curl -s -X POST "$HASS_URL/api/config/config_entries/flow/$FLOW_ID" \
  -H "Authorization: Bearer $HASS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"amdnative@gmail.com\",\"password\":\"$MIDEA_PASS\",\"mobile_app\":\"MSmartHome\",\"advanced_settings\":false}")

TYPE=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('type',''))" 2>/dev/null)
ERROR=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('errors',{}).get('base',''))" 2>/dev/null)

if [ "$TYPE" = "create_entry" ]; then
  log "SUCCESS! Midea dehumidifier config entry created."
  # Notify via HA
  curl -s -X POST "$HASS_URL/api/services/notify/notify" \
    -H "Authorization: Bearer $HASS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"message":"Midea dehumidifiers integrated into HA. Ready for automation.","title":"Midea Dehumidifier Setup Complete"}' >/dev/null
  exit 0
elif [ "$ERROR" = "no_cloud" ]; then
  # Still blocked by cloud session limit — silently exit, will retry next cron
  exit 0
else
  log "Unexpected result: type=$TYPE error=$ERROR"
  exit 0
fi
