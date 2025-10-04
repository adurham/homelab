# Home Assistant Quick Reference

## 🚀 **QUICK COMMANDS**

### Home Assistant CLI
```bash
# System status
ha core info

# Restart Home Assistant
ha core restart

# Check configuration
ha core check

# View logs
ha core logs

# Reload automations
ha automation reload

# List automations
ha automation list

# Enable/disable automation
ha automation enable <automation_id>
ha automation disable <automation_id>

# Trigger automation
ha automation trigger <automation_id>
```

### SSH Commands
```bash
# Connect to Home Assistant
ssh root@192.168.86.2

# Check file permissions
ls -la /config/automations/

# View configuration
cat /config/configuration.yaml

# Check logs
tail -f /config/home-assistant.log

# Restart Home Assistant
ha core restart
```

## 📁 **FILE LOCATIONS**

### Configuration Files
- **Main config**: `/config/configuration.yaml`
- **Automations**: `/config/automations/`
- **Scripts**: `/config/scripts/`
- **Python scripts**: `/config/python_scripts/`
- **Logs**: `/config/home-assistant.log`

### Local Development
- **Automations**: `homeassistant/automations/`
- **Scripts**: `homeassistant/scripts/`
- **Python scripts**: `homeassistant/python_scripts/`
- **Deployment**: `homeassistant/deployment/`
- **Entity inventory**: `homeassistant/entity_inventory/`

## 🔧 **COMMON TASKS**

### Deploy Changes
```bash
# Safe deployment
./deployment/safe_deploy.py --backup --validate --test --deploy

# Quick deployment
./deployment/minimal_deploy.sh --files-only

# Test deployment
./deployment/safe_deploy.py --validate --test
```

### Check System Health
```bash
# Check all entities
ha states list

# Check unavailable entities
ha states list --unavailable

# Check automation status
ha automation list

# Check system info
ha core info
```

### Debug Issues
```bash
# Check logs
ha core logs

# Check specific automation
ha automation logs <automation_id>

# Check entity state
ha states get <entity_id>

# Test automation
ha automation trigger <automation_id>
```

## 📋 **ENTITY REFERENCE**

### Common Entities
```yaml
# Garage doors
cover.left_garage_door
cover.middle_garage_bay_door
cover.right_garage_bay_door

# Garage lights
switch.garage_main_lights

# Garage sensors
binary_sensor.garage_door_motion
binary_sensor.garage_door_occupancy

# Pool
switch.pool_pump
sensor.pool_temperature

# Water heater
water_heater.hot_water_heater
```

### Entity States
```yaml
# Cover states
open, closed, opening, closing

# Switch states
on, off

# Binary sensor states
on, off

# Sensor states
numeric values, text values
```

## 🔄 **AUTOMATION PATTERNS**

### Basic Automation
```yaml
- id: 'example_automation'
  alias: 'Example Automation'
  description: 'What this automation does'
  triggers:
    - platform: state
      entity_id: switch.example
      to: 'on'
  conditions:
    - condition: state
      entity_id: binary_sensor.example
      state: 'on'
  action:
    - service: switch.turn_off
      target:
        entity_id: switch.example
  mode: single
```

### Motion-Based Automation
```yaml
- id: 'motion_automation'
  alias: 'Motion Automation'
  triggers:
    - platform: state
      entity_id: binary_sensor.motion
      to: 'on'
  action:
    - service: switch.turn_on
      target:
        entity_id: switch.lights
    - delay: '00:15:00'
    - service: switch.turn_off
      target:
        entity_id: switch.lights
  mode: restart
```

### Time-Based Automation
```yaml
- id: 'time_automation'
  alias: 'Time Automation'
  triggers:
    - platform: time
      at: '22:00:00'
  action:
    - service: switch.turn_off
      target:
        entity_id: switch.lights
  mode: single
```

## 🚨 **EMERGENCY PROCEDURES**

### System Won't Start
1. Check logs: `ha core logs`
2. Check config: `ha core check`
3. Restore backup
4. Restart: `ha core restart`

### Automation Not Working
1. Check automation: `ha automation list`
2. Check logs: `ha core logs`
3. Test manually: `ha automation trigger <id>`
4. Check entities: `ha states get <entity_id>`

### Entity Unavailable
1. Check entity: `ha states get <entity_id>`
2. Check device connectivity
3. Restart integration: `ha integration reload <integration>`
4. Restart Home Assistant: `ha core restart`

## 📊 **MONITORING COMMANDS**

### System Status
```bash
# Overall status
ha core info

# Disk usage
df -h

# Memory usage
free -h

# CPU usage
top
```

### Automation Status
```bash
# List all automations
ha automation list

# Check specific automation
ha automation get <automation_id>

# Test automation
ha automation trigger <automation_id>
```

### Entity Status
```bash
# List all entities
ha states list

# Check specific entity
ha states get <entity_id>

# Check entity history
ha states history <entity_id>
```

## 🔧 **DEPLOYMENT COMMANDS**

### Safe Deployment
```bash
# Full deployment
./deployment/safe_deploy.py --backup --validate --test --deploy

# Files only
./deployment/minimal_deploy.sh --files-only

# Test only
./deployment/safe_deploy.py --validate --test
```

### Backup and Restore
```bash
# Create backup
./deployment/safe_deploy.py --backup

# List backups
ls -la backup/

# Restore backup
cp backup/YYYYMMDD_HHMMSS/configuration.yaml /config/
```

## 📝 **LOGGING COMMANDS**

### View Logs
```bash
# All logs
ha core logs

# Specific level
ha core logs --level error

# Follow logs
ha core logs --follow

# Last N lines
ha core logs --lines 100
```

### Automation Logs
```bash
# All automation logs
ha automation logs

# Specific automation
ha automation logs <automation_id>

# Error logs only
ha automation logs --level error
```

## 🎯 **BEST PRACTICES**

### Before Making Changes
1. **Create backup**
2. **Test in safe environment**
3. **Validate configuration**
4. **Check entity references**
5. **Document changes**

### After Making Changes
1. **Test functionality**
2. **Check logs for errors**
3. **Monitor for 24 hours**
4. **Update documentation**
5. **Clean up temporary files**

### Regular Maintenance
1. **Check logs daily**
2. **Verify automations weekly**
3. **Clean up monthly**
4. **Update documentation**
5. **Review and improve**

---

**Remember**: This is a quick reference. For detailed information, see the specific rule files in this directory.
