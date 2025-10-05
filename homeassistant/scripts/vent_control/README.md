# Vent Control Scripts

This directory contains the scripts for the vent control system.

## Files

- `control_all_room_vents.yaml` - Main script that controls all room vents
- `control_room_vent.yaml` - Individual room vent control logic

## Script Hierarchy

```
control_all_room_vents
├── control_room_vent (Kitchen)
├── control_room_vent (Living Room - Vent 1)
├── control_room_vent (Living Room - Vent 2)
├── control_room_vent (Main Bedroom - Vent 1)
├── control_room_vent (Main Bedroom - Vent 2)
├── control_room_vent (Main Bedroom - Vent 3)
├── control_room_vent (Guest Bedroom 2)
├── control_room_vent (Main Bathroom)
├── control_room_vent (Laundry Room)
├── control_room_vent (Hallway)
└── control_room_vent (Dining Room)
```

## Parameters

### control_all_room_vents
- `target_temp`: Target temperature from Ecobee
- `hvac_mode`: HVAC mode from Ecobee

### control_room_vent
- `room_entity`: Climate entity for the room
- `room_name`: Human-readable room name
- `occupancy_sensor`: Occupancy sensor for the room
- `vent_entity`: Vent cover entity
- `target_temp`: Target temperature from Ecobee
- `hvac_mode`: HVAC mode from Ecobee

## Logic Flow

1. **Check occupancy** - Is the room occupied?
2. **Get temperature** - Current room temperature
3. **Calculate difference** - How far from target?
4. **Apply logic**:
   - **Occupied**: Set to exact target, open vent 100%
   - **Unoccupied + Cold**: Gentle heating, half-open vent
   - **Unoccupied + Hot**: Gentle cooling, half-open vent
   - **Unoccupied + OK**: Close vent to save energy
5. **Wait for API** - Account for Flair API latency
6. **Verify** - Check vent position was set correctly
