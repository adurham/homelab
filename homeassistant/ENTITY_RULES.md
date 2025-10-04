# Home Assistant Entity Rules

## 🏷️ **ENTITY NAMING CONVENTIONS**

### Device Class Standards
- **Covers**: `cover.{location}_{type}_door`
  - ✅ `cover.left_garage_door`
  - ✅ `cover.middle_garage_bay_door`
  - ❌ `cover.garage1`

- **Switches**: `switch.{location}_{function}_lights`
  - ✅ `switch.garage_main_lights`
  - ✅ `switch.front_porch_sconces`
  - ❌ `switch.light1`

- **Sensors**: `sensor.{location}_{measurement}`
  - ✅ `sensor.garage_temperature`
  - ✅ `sensor.living_room_humidity`
  - ❌ `sensor.temp1`

- **Binary Sensors**: `binary_sensor.{location}_{type}`
  - ✅ `binary_sensor.garage_door_motion`
  - ✅ `binary_sensor.garage_door_occupancy`
  - ❌ `binary_sensor.motion1`

### Location Hierarchy
```
{room}_{area}_{specific}
garage_main_lights
garage_door_motion
living_room_ceiling_fan
kitchen_under_cabinet_lights
```

## 🔍 **ENTITY VALIDATION RULES**

### Before Using Any Entity
1. **Check existence** in entity registry
2. **Validate state** is not 'unavailable'
3. **Verify device_class** matches expected type
4. **Confirm friendly_name** is descriptive
5. **Test state changes** work as expected

### Required Entity Checks
```yaml
# Always validate before use
- condition: state
  entity_id: switch.garage_main_lights
  state: 'on'
  for:
    seconds: 5
```

### Entity State Validation
```yaml
# Check entity is available
- condition: state
  entity_id: binary_sensor.garage_door_motion
  state: 'on'
  for:
    seconds: 1
```

## 📋 **ENTITY INVENTORY RULES**

### Required Entity Information
Every entity must have:
- **entity_id**: Unique identifier
- **friendly_name**: Human-readable name
- **device_class**: Appropriate classification
- **state**: Current state value
- **attributes**: Relevant attributes
- **last_changed**: Timestamp of last change
- **last_updated**: Timestamp of last update

### Entity Categories
- **Lighting**: All light-related entities
- **Cover**: Doors, windows, blinds
- **Climate**: Temperature, humidity, HVAC
- **Security**: Motion, occupancy, door sensors
- **Appliances**: Pool, water heater, etc.
- **System**: Home Assistant core entities

## 🚫 **FORBIDDEN ENTITY PATTERNS**

### Never Use These
- ❌ **Hardcoded entity IDs** in templates
- ❌ **Unvalidated entity references**
- ❌ **Deprecated entity types**
- ❌ **Non-existent entities**
- ❌ **Entities with 'unavailable' state**

### Anti-Patterns
- ❌ **Generic names** like `sensor1`, `switch2`
- ❌ **Inconsistent naming** across similar entities
- ❌ **Missing device_class** for sensors
- ❌ **Unclear friendly_name** descriptions
- ❌ **Mixed naming conventions** in same area

## 🔧 **ENTITY USAGE PATTERNS**

### Safe Entity Access
```yaml
# Always check availability first
- condition: state
  entity_id: switch.garage_main_lights
  state: 'on'
  for:
    seconds: 1

# Then use the entity
- service: switch.turn_off
  target:
    entity_id: switch.garage_main_lights
```

### Entity State Monitoring
```yaml
# Monitor state changes
- platform: state
  entity_id: cover.left_garage_door
  to: 'open'
  for:
    seconds: 5
```

### Entity Grouping
```yaml
# Group related entities
- platform: state
  entity_id:
    - cover.left_garage_door
    - cover.middle_garage_bay_door
    - cover.right_garage_bay_door
  to: 'open'
```

## 📊 **ENTITY AUDIT REQUIREMENTS**

### Regular Audits
- **Weekly**: Check for new entities
- **Monthly**: Validate all entity references
- **Quarterly**: Review naming conventions
- **Annually**: Clean up unused entities

### Audit Checklist
- [ ] All entities have descriptive names
- [ ] All entities have appropriate device_class
- [ ] All entity references are valid
- [ ] No hardcoded entity IDs
- [ ] Consistent naming conventions
- [ ] No deprecated entity types

## 🚨 **ENTITY ERROR HANDLING**

### Common Entity Errors
- **Entity not found**: Check entity_id spelling
- **Entity unavailable**: Check device connectivity
- **State not changing**: Check automation logic
- **Wrong device_class**: Update entity configuration
- **Missing attributes**: Check integration setup

### Error Recovery
```yaml
# Handle entity errors gracefully
- choose:
  - conditions:
      - condition: state
        entity_id: switch.garage_main_lights
        state: 'unavailable'
    sequence:
      - service: system_log.write
        data:
          message: 'Garage lights entity unavailable'
          level: error
  - conditions:
      - condition: state
        entity_id: switch.garage_main_lights
        state: 'on'
    sequence:
      - service: switch.turn_off
        target:
          entity_id: switch.garage_main_lights
```

## 📝 **ENTITY DOCUMENTATION**

### Required Documentation
- **Entity purpose**: What it controls
- **Integration source**: Which integration provides it
- **State values**: What states it can have
- **Attributes**: What attributes are available
- **Dependencies**: What it depends on

### Entity Documentation Template
```markdown
## Entity: switch.garage_main_lights

**Purpose**: Controls the main lighting in the garage
**Integration**: Z-Wave
**States**: on, off
**Attributes**: 
  - brightness: 0-255
  - color_temp: 153-500
**Dependencies**: Z-Wave controller, garage light switch
**Usage**: Turn on/off garage lights based on motion and door state
```

## 🔄 **ENTITY LIFECYCLE**

### Entity Creation
1. **Identify** the device/integration
2. **Choose** appropriate naming convention
3. **Configure** device_class and attributes
4. **Test** entity functionality
5. **Document** entity purpose and usage

### Entity Updates
1. **Backup** current configuration
2. **Update** entity configuration
3. **Test** all automations using the entity
4. **Update** documentation
5. **Deploy** changes safely

### Entity Removal
1. **Identify** all automations using the entity
2. **Update** or remove affected automations
3. **Remove** entity from configuration
4. **Test** system without the entity
5. **Update** documentation

## 🎯 **ENTITY BEST PRACTICES**

### Naming
- **Be descriptive**: `garage_main_lights` not `light1`
- **Be consistent**: Use same pattern for similar entities
- **Be hierarchical**: `room_area_specific`
- **Be future-proof**: Consider expansion needs

### Usage
- **Always validate**: Check entity exists and is available
- **Handle errors**: Gracefully handle unavailable entities
- **Monitor changes**: Track entity state changes
- **Group logically**: Group related entities together

### Maintenance
- **Regular audits**: Check entity inventory regularly
- **Update documentation**: Keep entity docs current
- **Clean up unused**: Remove entities no longer needed
- **Monitor performance**: Track entity response times

---

**Remember**: Entities are the foundation of your Home Assistant system. Proper naming, validation, and usage are critical for reliable automation.
