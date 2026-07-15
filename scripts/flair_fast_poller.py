#!/usr/bin/env python3
"""Flair vent fast poller — polls the Flair cloud API every 15s and pushes
vent positions, duct temps, battery voltages, and motor currents to HA as
custom sensors. Bypasses the HA Flair integration's 30s poll + caching lag.

The Flair vents are battery-powered and report to the cloud on their own
schedule (every 2-5 min). We can't make them report faster, but this poller
ensures we see their data within 15s of it hitting the cloud, instead of the
HA integration's 30s poll + processing lag (which was causing 65+ min
staleness on vent positions).

Data pushed to HA as sensor.flair_fast_* entities:
  - flair_fast_{vent_id}_position: vent percent open (0-100)
  - flair_fast_{vent_id}_duct_temp: duct supply temperature (°F)
  - flair_fast_{vent_id}_voltage: battery voltage (V)
  - flair_fast_{vent_id}_motor_current: motor current (mA)

Runs as a background loop. Cron-managed or systemd.
"""
import json, urllib.request, urllib.parse, time, os, sys, logging
from pathlib import Path
from datetime import datetime, timezone

# --- Config ---
POLL_INTERVAL = 15  # seconds between Flair API polls
HA_URL = None
HA_TOKEN = None
FLAIR_CLIENT_ID = None
FLAIR_CLIENT_SECRET = None
FLAIR_TOKEN = None
FLAIR_TOKEN_EXPIRY = 0

# --- Load credentials ---
def load_creds():
    global HA_URL, HA_TOKEN, FLAIR_CLIENT_ID, FLAIR_CLIENT_SECRET
    env = Path.home() / ".hermes" / ".env"
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith("HASS_URL="): HA_URL = line.split("=",1)[1].strip().strip('"').strip("'").rstrip("/")
        elif line.startswith("HASS_TOKEN="): HA_TOKEN = line.split("=",1)[1].strip().strip('"').strip("'")
        elif line.startswith("FLAIR_CLIENT_ID="): FLAIR_CLIENT_ID = line.split("=",1)[1].strip()
        elif line.startswith("FLAIR_CLIENT_SECRET="): FLAIR_CLIENT_SECRET = line.split("=",1)[1].strip()

def get_flair_token():
    global FLAIR_TOKEN, FLAIR_TOKEN_EXPIRY
    if FLAIR_TOKEN and time.time() < FLAIR_TOKEN_EXPIRY - 60:
        return FLAIR_TOKEN
    data = urllib.parse.urlencode({
        "client_id": FLAIR_CLIENT_ID,
        "client_secret": FLAIR_CLIENT_SECRET,
        "scope": "pucks.view+pucks.edit+structures.view+structures.edit+thermostats.view+users.view+users.edit+vents.view+vents.edit",
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request("https://api.flair.co/oauth2/token", data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    FLAIR_TOKEN = resp["access_token"]
    FLAIR_TOKEN_EXPIRY = time.time() + resp.get("expires_in", 3600)
    return FLAIR_TOKEN

def fetch_vents():
    """Fetch all vents with current sensor readings from Flair API."""
    token = get_flair_token()
    req = urllib.request.Request("https://api.flair.co/api/vents?include=current-reading",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.api+json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    # Build a map of vent_id -> reading from the included section
    readings = {}
    for item in resp.get("included", []):
        if item.get("type") == "vent-sensor-readings":
            readings[item.get("relationships", {}).get("vent", {}).get("data", {}).get("id", "")] = item.get("attributes", {})
    # Combine vent attrs + reading
    vents = []
    for v in resp.get("data", []):
        vid = v.get("id", "")
        attrs = v.get("attributes", {})
        reading = readings.get(vid, {})
        vents.append({
            "id": vid,
            "name": attrs.get("name", vid[:8]),
            "position": attrs.get("percent-open"),
            "voltage": attrs.get("voltage"),
            "updated_at": attrs.get("updated-at", ""),
            "duct_temp_c": reading.get("duct-temperature-c"),
            "motor_current": reading.get("motor-current"),
            "rssi": attrs.get("current-rssi"),
        })
    return vents

def c_to_f(c):
    return c * 9/5 + 32 if c is not None else None

def push_to_ha(vents):
    """Push vent data to HA as custom sensors."""
    now = datetime.now(timezone.utc).isoformat()
    for v in vents:
        # Sanitize name for entity_id
        safe = v["name"].lower().replace(" ", "_").replace("-", "_")
        safe = "".join(c for c in safe if c.isalnum() or c == "_")
        safe = "_".join(part for part in safe.split("_") if part)  # collapse consecutive underscores
        # Position
        if v["position"] is not None:
            set_ha_state(f"sensor.flair_fast_{safe}_position", str(v["position"]),
                {"unit_of_measurement": "%", "device_class": "measurement",
                 "friendly_name": f"{v['name']} Position (fast)", "state_class": "measurement"})
        # Duct temp
        if v["duct_temp_c"] is not None:
            set_ha_state(f"sensor.flair_fast_{safe}_duct_temp", f"{c_to_f(v['duct_temp_c']):.1f}",
                {"unit_of_measurement": "°F", "device_class": "temperature",
                 "friendly_name": f"{v['name']} Duct Temp (fast)", "state_class": "measurement"})
        # Voltage
        if v["voltage"] is not None:
            set_ha_state(f"sensor.flair_fast_{safe}_voltage", str(v["voltage"]),
                {"unit_of_measurement": "V", "device_class": "voltage",
                 "friendly_name": f"{v['name']} Voltage (fast)", "state_class": "measurement"})

def set_ha_state(entity_id, state, attributes):
    """Set a state in HA via REST API."""
    body = json.dumps({"state": state, "attributes": attributes}).encode()
    req = urllib.request.Request(f"{HA_URL}/api/states/{entity_id}",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logging.warning(f"Failed to set {entity_id}: {e}")

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_creds()
    if not all([HA_URL, HA_TOKEN, FLAIR_CLIENT_ID, FLAIR_CLIENT_SECRET]):
        logging.error("Missing credentials")
        sys.exit(1)
    logging.info(f"Flair fast poller started — {POLL_INTERVAL}s interval")
    while True:
        try:
            vents = fetch_vents()
            push_to_ha(vents)
            logging.info(f"Pushed {len(vents)} vents to HA")
        except Exception as e:
            logging.error(f"Poll failed: {e}")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()