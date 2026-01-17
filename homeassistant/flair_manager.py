import os
import requests
import time
import argparse
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv('ha_config.env')

HA_URL = os.getenv('HA_URL')
HA_TOKEN = os.getenv('HA_TOKEN')

if not HA_URL or not HA_TOKEN:
    print("Error: HA_URL or HA_TOKEN not found in ha_config.env")
    exit(1)

headers = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

class Entity:
    def __init__(self, entity_id: str, state: str, attributes: dict):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes

class Room:
    def __init__(self, name: str):
        self.name = name
        self.occupancy_sensors: List[str] = []
        self.temp_sensors: List[str] = []
        self.vents: List[str] = []
        self.current_temp: Optional[float] = None
        self.is_occupied: bool = False

    def __repr__(self):
        return f"<Room {self.name}: Occ={self.is_occupied}, Temp={self.current_temp}, Vents={len(self.vents)}>"

def get_states() -> List[dict]:
    """Get the state of all devices."""
    url = f"{HA_URL}/api/states"
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Home Assistant: {e}")
        return []

def set_vent_position(entity_id: str, position: int, dry_run: bool = False):
    """Set the position of a cover (vent)."""
    if dry_run:
        print(f"[DRY RUN] Setting {entity_id} to {position}%")
        return

    url = f"{HA_URL}/api/services/cover/set_cover_position"
    data = {"entity_id": entity_id, "position": position}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"Set {entity_id} to {position}%")
    except requests.exceptions.RequestException as e:
        print(f"Error setting vent position: {e}")

def get_thermostat_state(states: List[dict]):
    """Find the main thermostat and return target temp and mode."""
    # Heuristic: look for 'climate.' entity
    # Or use the specific sensor 'sensor.edgewater_road_current_temperature' as a hint if climate not found
    for s in states:
        if s['entity_id'].startswith('climate.'):
             # Assumption: The first climate entity is the main one.
             # Modify this if there are multiple thermostats!
             return s
    return None

def main():
    parser = argparse.ArgumentParser(description='Flair Vent Manager')
    parser.add_argument('--dry-run', action='store_true', help='Do not make actual changes')
    parser.add_argument('--interval', type=int, default=60, help='Loop interval in seconds (0 for single run)')
    args = parser.parse_args()

    while True:
        raw_states = get_states()
        if not raw_states:
            print("Failed to fetch states. Retrying in 60s...")
            if args.interval == 0: break
            time.sleep(60)
            continue

        # 1. Discover Rooms
        rooms: Dict[str, Room] = {}

        # 1. Discover Thermostats
        climate_entities = [s for s in raw_states if s['entity_id'].startswith('climate.')]
        if len(climate_entities) > 1:
             print("Found multiple thermostats:", [c['entity_id'] for c in climate_entities])

        # Select best thermostat (hardcode or first available)
        main_thermostat = next((c for c in climate_entities if c['entity_id'] == 'climate.ecobee_thermostat'), None)

        if not main_thermostat:
             # Fallback to first available that isn't offline
             main_thermostat = next((c for c in climate_entities if c['state'] not in ['unavailable', 'unknown']), None)

        if not main_thermostat and climate_entities:
            main_thermostat = climate_entities[0] # Fallback to first even if unavailable

        if not main_thermostat:
            print("Warning: No climate entity found!")
            hvac_mode = 'off'
            target_temp = 22.0
        else:
            hvac_mode = main_thermostat['state']
            attrs = main_thermostat['attributes']
            target_temp = attrs.get('temperature')
            if target_temp is None:
                if hvac_mode == 'heat_cool':
                     high = attrs.get('target_temp_high')
                     low = attrs.get('target_temp_low')
                     if high and low:
                         target_temp = (high + low) / 2

            print(f"Thermostat: {main_thermostat['entity_id']} | Mode: {hvac_mode} | Target: {target_temp}")

        # 2. Discover Rooms
        rooms: Dict[str, Room] = {}

        # Helper to get/create room
        def get_room(name_part: str) -> Room:
            # Clean up name: 'guest_bedroom_2' -> 'guest_bedroom_2'
            # Remove suffixes like _occupancy, _temperature
            if name_part not in rooms:
                rooms[name_part] = Room(name_part)
            return rooms[name_part]

        # Map entities to rooms
        for entity in raw_states:
            eid = entity['entity_id']
            # Occupancy
            if eid.startswith('binary_sensor.') and '_occupancy' in eid:
                base_name = eid.replace('binary_sensor.', '').replace('_occupancy', '')
                # Handle _2, _3 suffixes for multiple sensors in same room?
                # User's list: dining_room_occupancy, dining_room_occupancy_2
                # heuristic: strip trailing _\d+
                if base_name[-2] == '_' and base_name[-1].isdigit():
                     base_name = base_name[:-2]

                get_room(base_name).occupancy_sensors.append(eid)

            # Temperature
            elif eid.startswith('sensor.') and '_temperature' in eid:
                if 'holding_until' in eid: continue # Update logic: Skip holding_until sensors

                base_name = eid.replace('sensor.', '').replace('_temperature', '')
                if '_duct' in base_name: continue # Skip duct temps for room ambient logic

                if base_name[-2] == '_' and base_name[-1].isdigit():
                     base_name = base_name[:-2]

                get_room(base_name).temp_sensors.append(eid)

            # Vents
            elif eid.startswith('cover.') and '_vent' in eid:
                base_name = eid.replace('cover.', '').replace('_vent', '')

                # Cleanup: 'dining_room_7a28' -> 'dining_room'
                # Heuristic: Remove the hex code part if present
                # split by _ and check parts
                parts = base_name.split('_')

                # Handling suffixes like _2 first
                if parts[-1].isdigit() and len(parts[-1]) == 1: # _2
                    parts.pop()

                # Check for hex ID (usually 4 chars)
                if len(parts) > 1 and len(parts[-1]) == 4: # e.g. 7a28
                    parts.pop()

                room_name = '_'.join(parts)
                get_room(room_name).vents.append(eid)

        # 2. Update Room States
        current_time_str = time.strftime("%H:%M:%S")
        print(f"\n--- Analysis at {current_time_str} ---")

        for name, room in rooms.items():
            if not room.vents:
                continue # Skip rooms without vents

            # Calculate Occupancy (ANY sensor on)
            is_occupied = False
            for sens in room.occupancy_sensors:
                # find state
                s = next((x for x in raw_states if x['entity_id'] == sens), None)
                if s and s['state'] == 'on':
                    is_occupied = True
                    break
            room.is_occupied = is_occupied

            # Calculate Temp (Avg of sensors)
            vals = []
            for sens in room.temp_sensors:
                s = next((x for x in raw_states if x['entity_id'] == sens), None)
                if s and s['state'] not in ['unknown', 'unavailable']:
                    try:
                        vals.append(float(s['state']))
                    except ValueError:
                        pass

            if vals:
                room.current_temp = sum(vals) / len(vals)

            # Logic
            # Default action: CLOSE (deprioritize)
            desired_position = 0
            reason = "Default (Unoccupied)"

            if room.is_occupied:
                if target_temp is None:
                    reason = "Occupied, but no Target Temp (Default Open)"
                    desired_position = 100 # Fail safe: Open
                elif room.current_temp is None:
                    reason = "Occupied, but no Room Temp (Default Open)"
                    desired_position = 100 # Fail safe: Open
                else:
                    diff = room.current_temp - target_temp
                    # Hysteresis / Simple Logic (0.5 degree C deadband?)

                    if hvac_mode == 'cool':
                        if diff > 0.5: # Too hot
                            desired_position = 100
                            reason = f"Occupied, Too Hot ({room.current_temp:.1f} > {target_temp})"
                        elif diff < -0.5: # Too cold
                            desired_position = 0
                            reason = f"Occupied, Too Cold ({room.current_temp:.1f} < {target_temp})"
                        else:
                            desired_position = 50 # Balanced?
                            reason = "Occupied, Balanced"

                    elif hvac_mode == 'heat':
                        if diff < -0.5: # Too cold
                            desired_position = 100
                            reason = f"Occupied, Too Cold ({room.current_temp:.1f} < {target_temp})"
                        elif diff > 0.5: # Too hot
                            desired_position = 0
                            reason = f"Occupied, Too Hot ({room.current_temp:.1f} > {target_temp})"
                        else:
                            desired_position = 50
                            reason = "Occupied, Balanced"
                    else:
                        reason = f"Occupied, HVAC Off/Fan Only ({hvac_mode})"
                        desired_position = 100 # Open vents to allow circulation?

            print(f"Room: {name:<20} | Occ: {str(room.is_occupied):<5} | Temp: {str(room.current_temp):<5} | Action: {desired_position}% ({reason})")

            # Execute
            for vent in room.vents:
                set_vent_position(vent, desired_position, dry_run=args.dry_run)

        if args.interval == 0:
            break
        print(f"Sleeping for {args.interval}s...")
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
