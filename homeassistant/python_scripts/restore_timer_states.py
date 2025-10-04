"""
Restore timer states after reboot
This script restores timers to their previous state
"""

import json
import os

# Define the storage file path
storage_file = '/config/.timer_states.json'

# Load stored timer states
if not os.path.exists(storage_file):
    logger.warning("No timer states file found")
    exit()

try:
    with open(storage_file, 'r') as f:
        timer_states = json.load(f)
except (json.JSONDecodeError, IOError) as e:
    logger.error(f"Could not load timer states: {e}")
    exit()

# Restore each timer to its previous state
restored_count = 0
for entity_id, timer_data in timer_states.items():
    try:
        # Check if the timer entity exists
        if not hass.states.get(entity_id):
            logger.warning(f"Timer entity {entity_id} not found, skipping")
            continue
            
        previous_state = timer_data.get('state')
        remaining_time = timer_data.get('remaining_time', 0)
        
        if previous_state == 'active' and remaining_time > 0:
            # Start the timer with the remaining time
            hass.services.call('timer', 'start', {
                'entity_id': entity_id,
                'duration': f"00:{int(remaining_time//60):02d}:{int(remaining_time%60):02d}"
            })
            logger.info(f"Restored {entity_id} to active state with {remaining_time}s remaining")
            restored_count += 1
        elif previous_state == 'paused' and remaining_time > 0:
            # Start and immediately pause the timer
            hass.services.call('timer', 'start', {
                'entity_id': entity_id,
                'duration': f"00:{int(remaining_time//60):02d}:{int(remaining_time%60):02d}"
            })
            hass.services.call('timer', 'pause', {'entity_id': entity_id})
            logger.info(f"Restored {entity_id} to paused state with {remaining_time}s remaining")
            restored_count += 1
        else:
            logger.info(f"Skipped {entity_id} (was {previous_state} with {remaining_time}s)")
            
    except Exception as e:
        logger.error(f"Error restoring {entity_id}: {e}")

# Clean up the storage file
try:
    os.remove(storage_file)
    logger.info(f"Cleaned up timer states file after restoring {restored_count} timers")
except IOError as e:
    logger.warning(f"Could not remove timer states file: {e}")
