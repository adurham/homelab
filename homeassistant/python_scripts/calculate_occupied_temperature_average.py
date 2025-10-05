#!/usr/bin/env python3
"""
Calculate Occupied Room Temperature Average
Calculates the average temperature of occupied rooms for temperature balancing
"""

import json

# Room mapping - occupancy sensors to climate entities
ROOM_MAPPING = {
    'binary_sensor.kitchen_occupancy': 'climate.kitchen_room_3',
    'binary_sensor.kitchen_occupancy_2': 'climate.kitchen_room_3',
    'binary_sensor.living_room_occupancy': 'climate.living_room_room_3',
    'binary_sensor.main_bedroom_occupancy': 'climate.main_bedroom_room_2',
    'binary_sensor.guest_bedroom_1_occupancy': 'climate.guest_bedroom_1_room',
    'binary_sensor.guest_bedroom_2_occupancy': 'climate.guest_bedroom_2_room_2',
    'binary_sensor.main_bathroom_occupancy': 'climate.main_bathroom_room_2',
    'binary_sensor.guest_bathroom_occupancy': 'climate.guest_bathroom_room_2',
    'binary_sensor.half_bathroom_occupancy': 'climate.half_bathroom_room',
    'binary_sensor.dining_room_occupancy': 'climate.dining_room_room_2',
    'binary_sensor.game_room_occupancy': 'climate.game_room_room',
    'binary_sensor.cat_room_occupancy': 'climate.cat_room_room',
    'binary_sensor.laundry_room_occupancy': 'climate.laundry_room_room_2',
    'binary_sensor.hallway_occupancy': 'climate.hallway_room_3',
    'binary_sensor.edgewater_road_occupancy': 'climate.edgewater_road_structure'
}

def calculate_occupied_temperature_average():
    """Calculate average temperature of occupied rooms"""
    occupied_temperatures = []
    occupied_rooms = []
    
    # Check each room for occupancy
    for occupancy_sensor, climate_entity in ROOM_MAPPING.items():
        try:
            # Check if room is occupied
            occupancy_state = hass.states.get(occupancy_sensor)
            if occupancy_state and occupancy_state.state == 'on':
                # Get room temperature
                climate_state = hass.states.get(climate_entity)
                if climate_state:
                    current_temp = climate_state.attributes.get('current_temperature')
                    if current_temp is not None:
                        occupied_temperatures.append(float(current_temp))
                        occupied_rooms.append(climate_entity)
                        logger.info(f"Room {climate_entity} is occupied at {current_temp}°F")
        except Exception as e:
            logger.error(f"Error checking {occupancy_sensor}: {e}")
    
    # Calculate average
    if occupied_temperatures:
        average_temp = sum(occupied_temperatures) / len(occupied_temperatures)
        logger.info(f"Occupied rooms: {len(occupied_rooms)}")
        logger.info(f"Average occupied temperature: {average_temp:.1f}°F")
        logger.info(f"Occupied rooms: {', '.join(occupied_rooms)}")
        
        # Store in input_text for use by other automations
        hass.services.call(
            'input_text', 'set_value',
            {
                'entity_id': 'input_text.occupied_temperature_average',
                'value': str(round(average_temp, 1))
            }
        )
        
        return average_temp
    else:
        # No occupied rooms - use ecobee setpoint as fallback
        ecobee_state = hass.states.get('climate.ecobee_thermostat')
        if ecobee_state:
            target_temp = ecobee_state.attributes.get('temperature')
            if target_temp is not None:
                logger.info(f"No occupied rooms - using ecobee setpoint: {target_temp}°F")
                hass.services.call(
                    'input_text', 'set_value',
                    {
                        'entity_id': 'input_text.occupied_temperature_average',
                        'value': str(target_temp)
                    }
                )
                return float(target_temp)
        
        # Fallback to 72°F
        logger.warning("No occupied rooms and no ecobee setpoint - using 72°F")
        hass.services.call(
            'input_text', 'set_value',
            {
                'entity_id': 'input_text.occupied_temperature_average',
                'value': '72.0'
            }
        )
        return 72.0

# Run the calculation
result = calculate_occupied_temperature_average()
logger.info(f"Temperature balancing calculation complete: {result:.1f}°F")
