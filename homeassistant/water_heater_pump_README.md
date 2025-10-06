# Water Heater Circulator Pump Automation System

## Overview
This system automatically controls a water heater circulator pump based on occupancy detection in rooms with sinks. The pump runs for 15 minutes when presence is detected, followed by a 45-minute cooldown period to prevent excessive heating.

## Components

### Automations
1. **water_heater_pump_presence_detection.yaml** - Detects occupancy in any sink room
2. **water_heater_pump_cycle_control.yaml** - Manages the 15-min ON / 45-min OFF cycle
3. **water_heater_pump_turn_off.yaml** - Turns off pump after 15 minutes
4. **water_heater_pump_daily_reset.yaml** - Resets daily statistics at midnight
5. **water_heater_pump_runtime_tracking.yaml** - Tracks daily runtime
6. **water_heater_pump_runtime_update.yaml** - Updates runtime when pump stops
7. **water_heater_pump_max_runtime_protection.yaml** - Prevents excessive usage

### Helper Entities
- `input_boolean.water_heater_pump_automation_enabled` - Manual override toggle
- `input_number.water_heater_pump_daily_runtime_hours` - Daily runtime tracking
- `counter.water_heater_pump_daily_cycles` - Daily cycle counter
- `timer.water_heater_pump_runtime` - 15-minute pump runtime timer
- `timer.water_heater_pump_cooldown` - 45-minute cooldown timer

### Scripts
- `water_heater_pump_manual_on` - Manually turn on pump
- `water_heater_pump_manual_off` - Manually turn off pump
- `water_heater_pump_reset` - Reset all timers and counters
- `water_heater_pump_test_presence` - Test presence detection

## Monitored Rooms
- Kitchen (`binary_sensor.kitchen_occupancy`)
- Half Bathroom (`binary_sensor.half_bathroom_occupancy`)
- Main Bathroom (`binary_sensor.main_bathroom_occupancy`)
- Guest Bathroom (`binary_sensor.guest_bathroom_occupancy`)

## Safety Features
- **Daily Runtime Limit**: Maximum 8 hours per day
- **Cooldown Period**: 45 minutes between cycles
- **Manual Override**: Can be disabled via `input_boolean.water_heater_pump_automation_enabled`
- **Automatic Shutdown**: Disables automation if daily limit exceeded

## Installation Steps
1. Add helper entities to `configuration.yaml`:
   ```yaml
   !include water_heater_pump_helpers.yaml
   ```

2. Add scripts to `scripts.yaml`:
   ```yaml
   !include scripts/water_heater_pump_manual_control.yaml
   ```

3. Deploy automation files to `automations/` directory

4. Restart Home Assistant

## Usage
- **Automatic**: System runs automatically when occupancy is detected
- **Manual Control**: Use scripts for manual pump control
- **Monitoring**: Check `input_number.water_heater_pump_daily_runtime_hours` for daily usage
- **Override**: Toggle `input_boolean.water_heater_pump_automation_enabled` to disable

## Logging
All pump activities are logged to Home Assistant logs with level "info" or "warning".
