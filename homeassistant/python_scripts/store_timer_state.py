"""
Store timer state before pausing for later restoration
This script stores the current state of a timer entity
"""

import json
import os

# Get the entity ID and state from the service call
entity_id = data.get('entity_id')
current_state = data.get('state')

if not entity_id or not current_state:
    logger.error("Missing entity_id or state parameter")
    exit()

# Define the storage file path
storage_file = '/config/.timer_states.json'

# Load existing timer states
timer_states = {}
if os.path.exists(storage_file):
    try:
        with open(storage_file, 'r') as f:
            timer_states = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not load existing timer states: {e}")
        timer_states = {}

# Store the current timer state
timer_states[entity_id] = {
    'state': current_state,
    'remaining_time': hass.states.get(entity_id).attributes.get('remaining', 0)
}

# Save the updated states
try:
    with open(storage_file, 'w') as f:
        json.dump(timer_states, f, indent=2)
    logger.info(f"Stored state for {entity_id}: {current_state}")
except IOError as e:
    logger.error(f"Could not save timer states: {e}")
