import appdaemon.plugins.hass.hassapi as hass
import time

class FlairManager(hass.Hass):

    def initialize(self):
        self.log("Flair Manager Initializing...")

        # Run every 60 seconds
        self.run_every(self.check_vents, "now", 60)
        self.log("Flair Manager Initialized. Running every 60s.")

    def check_vents(self, kwargs):
        self.log("Checking vents...")

        # 0. Fetch all states
        all_states = self.get_state()

        # 1. Discover Thermostats
        # Filter for climate entities
        climate_entities = []
        for entity_id, state_obj in all_states.items():
            if entity_id.startswith("climate."):
                 # In AppDaemon get_state() returns dict with 'state' and 'attributes'
                 # But self.get_state('entity_id', attribute='all') returns the full object
                 # When getting ALL states, it maps entity_id -> {'state': ..., 'attributes': ...}
                 climate_entities.append({'entity_id': entity_id, 'state': state_obj['state'], 'attributes': state_obj.get('attributes', {})})

        if len(climate_entities) > 1:
             self.log(f"Found multiple thermostats: {[c['entity_id'] for c in climate_entities]}")

        # Select best thermostat (hardcode or first available)
        main_thermostat = next((c for c in climate_entities if c['entity_id'] == 'climate.ecobee_thermostat'), None)

        if not main_thermostat:
             # Fallback to first available that isn't offline
             main_thermostat = next((c for c in climate_entities if c['state'] not in ['unavailable', 'unknown']), None)

        if not main_thermostat and climate_entities:
            main_thermostat = climate_entities[0]

        if not main_thermostat:
            self.log("Warning: No climate entity found!")
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

            self.log(f"Thermostat: {main_thermostat['entity_id']} | Mode: {hvac_mode} | Target: {target_temp}")

        # 2. Discover Rooms
        rooms = {}

        def get_room(name):
            if name not in rooms:
                rooms[name] = {'name': name, 'occupancy_sensors': [], 'temp_sensors': [], 'vents': []}
            return rooms[name]

        for entity_id in all_states:
            # Occupancy
            if entity_id.startswith('binary_sensor.') and '_occupancy' in entity_id:
                base_name = entity_id.replace('binary_sensor.', '').replace('_occupancy', '')
                if base_name[-2] == '_' and base_name[-1].isdigit():
                     base_name = base_name[:-2]
                get_room(base_name)['occupancy_sensors'].append(entity_id)

            # Temperature
            elif entity_id.startswith('sensor.') and '_temperature' in entity_id:
                if 'holding_until' in entity_id: continue

                base_name = entity_id.replace('sensor.', '').replace('_temperature', '')
                if '_duct' in base_name: continue

                if base_name[-2] == '_' and base_name[-1].isdigit():
                     base_name = base_name[:-2]
                get_room(base_name)['temp_sensors'].append(entity_id)

            # Vents
            elif entity_id.startswith('cover.') and '_vent' in entity_id:
                base_name = entity_id.replace('cover.', '').replace('_vent', '')
                parts = base_name.split('_')
                if parts[-1].isdigit() and len(parts[-1]) == 1: parts.pop()
                if len(parts) > 1 and len(parts[-1]) == 4: parts.pop()
                room_name = '_'.join(parts)
                get_room(room_name)['vents'].append(entity_id)

        # 3. Analyze and Act
        for name, room in rooms.items():
            if not room['vents']: continue

            # Calc Occupancy
            is_occupied = False
            for sens in room['occupancy_sensors']:
                state = self.get_state(sens)
                if state == 'on':
                    is_occupied = True
                    break

            # Calc Temp
            vals = []
            for sens in room['temp_sensors']:
                state = self.get_state(sens)
                if state not in ['unknown', 'unavailable', None]:
                    try:
                        vals.append(float(state))
                    except ValueError:
                        pass

            current_temp = sum(vals) / len(vals) if vals else None

            # Logic
            desired_position = 0
            reason = "Default (Unoccupied)"

            if is_occupied:
                if target_temp is None:
                    reason = "Occupied, but no Target Temp (Default Open)"
                    desired_position = 100
                elif current_temp is None:
                    reason = "Occupied, but no Room Temp (Default Open)"
                    desired_position = 100
                else:
                    diff = current_temp - target_temp

                    if hvac_mode == 'cool':
                        if diff > 0.5:
                            desired_position = 100
                            reason = f"Occupied, Too Hot ({current_temp:.1f} > {target_temp})"
                        elif diff < -0.5:
                            desired_position = 0
                            reason = f"Occupied, Too Cold ({current_temp:.1f} < {target_temp})"
                        else:
                            desired_position = 50
                            reason = "Occupied, Balanced"

                    elif hvac_mode == 'heat':
                        if diff < -0.5:
                            desired_position = 100
                            reason = f"Occupied, Too Cold ({current_temp:.1f} < {target_temp})"
                        elif diff > 0.5:
                            desired_position = 0
                            reason = f"Occupied, Too Hot ({current_temp:.1f} > {target_temp})"
                        else:
                            desired_position = 50
                            reason = "Occupied, Balanced"
                    else:
                        reason = f"Occupied, HVAC Off/Fan Only ({hvac_mode})"
                        desired_position = 100

            self.log(f"Room: {name:<20} | Occ: {str(is_occupied):<5} | Temp: {str(current_temp):<5} | Action: {desired_position}% ({reason})")

            for vent in room['vents']:
                self.call_service("cover/set_cover_tilt_position", entity_id=vent, tilt_position=desired_position)
