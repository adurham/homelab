"""
Comprehensive timer pause script
This script finds all timer entities, stores their state, and pauses them
"""

import json
import os

# Define the storage file path
storage_file = '/config/.timer_states.json'

# Get all timer entities
timer_entities = [entity for entity in hass.states.entity_ids() if entity.startswith('timer.')]

if not timer_entities:
    logger.info("No timer entities found")
    exit()

# Initialize storage dictionary
timer_states = {}

# Process each timer
paused_count = 0
for entity_id in timer_entities:
    try:
        timer_state = hass.states.get(entity_id)
        if not timer_state:
            continue
            
        current_state = timer_state.state
        remaining_time = timer_state.attributes.get('remaining', 0)
        
        # Only process active or paused timers
        if current_state in ['active', 'paused']:
            # Store the timer state
            timer_states[entity_id] = {
                'state': current_state,
                'remaining_time': remaining_time,
                'friendly_name': timer_state.attributes.get('friendly_name', entity_id)
            }
            
            # Pause the timer if it's active
            if current_state == 'active':
                hass.services.call('timer', 'pause', {'entity_id': entity_id})
                paused_count += 1
                logger.info(f"Paused timer {entity_id} ({timer_state.attributes.get('friendly_name', '')}) with {remaining_time}s remaining")
            else:
                logger.info(f"Timer {entity_id} was already paused")
                
    except Exception as e:
        logger.error(f"Error processing timer {entity_id}: {e}")

# Save the timer states to file
if timer_states:
    try:
        with open(storage_file, 'w') as f:
            json.dump(timer_states, f, indent=2)
        logger.info(f"Stored states for {len(timer_states)} timers, paused {paused_count} active timers")
    except IOError as e:
        logger.error(f"Could not save timer states: {e}")
else:
    logger.info("No timers to pause")
