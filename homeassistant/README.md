# Home Assistant Nightly Reboot with Timer Pause/Resume

This setup provides a nightly reboot automation for Home Assistant that intelligently pauses all running timers before the reboot and resumes them with their remaining time after the system restarts.

## Features

- **Nightly Reboot**: Automatically reboots Home Assistant at 3:00 AM daily
- **Timer Preservation**: Pauses all active timers before reboot and resumes them with correct remaining time
- **State Storage**: Uses file-based storage to persist timer states across reboots
- **Comprehensive Logging**: Detailed logging for troubleshooting and monitoring
- **Error Handling**: Robust error handling for edge cases

## Files Structure

```
homeassistant/
├── automations/
│   ├── nightly_reboot_with_timer_pause.yaml    # Main reboot automation
│   └── startup_restore_timers.yaml             # Startup timer restoration
├── python_scripts/
│   ├── pause_all_timers_script.py              # Pause all timers with state storage
│   ├── store_timer_state.py                    # Individual timer state storage
│   └── restore_timer_states.py                 # Restore timer states after reboot
├── scripts/
│   ├── pause_all_timers.yaml                   # Script wrapper for pausing
│   └── resume_all_timers.yaml                  # Script wrapper for resuming
├── configuration.yaml                          # HA configuration additions
└── README.md                                   # This file
```

## Installation

### 1. Copy Files to Home Assistant

Copy all files to your Home Assistant configuration directory:

```bash
# Copy automations
cp automations/*.yaml /config/automations/

# Copy python scripts
cp python_scripts/*.py /config/python_scripts/

# Copy scripts
cp scripts/*.yaml /config/scripts/

# Update configuration.yaml
# Add the contents of configuration.yaml to your existing /config/configuration.yaml
```

### 2. Update Configuration

Add these lines to your `/config/configuration.yaml`:

```yaml
# Input helpers for timer state management
input_text:
  timer_states:
    name: "Timer States Storage"
    initial: "{}"
    max: 10000

# Python script configuration
python_script:

# Automation configuration
automation: !include automations/

# Script configuration  
script: !include scripts/
```

### 3. Restart Home Assistant

After copying the files and updating configuration:

1. Go to **Settings** → **System** → **Restart**
2. Wait for Home Assistant to restart
3. Check the logs for any errors

## How It Works

### Nightly Reboot Process

1. **Trigger**: Automation runs at 3:00 AM daily
2. **Pause Phase**: 
   - Finds all timer entities
   - Stores their current state and remaining time
   - Pauses all active timers
   - Saves state to `/config/.timer_states.json`
3. **Reboot**: Restarts Home Assistant
4. **Resume Phase** (on startup):
   - Waits 30 seconds for system to be ready
   - Reads stored timer states
   - Restarts timers with correct remaining time
   - Cleans up state file

### Timer State Storage

The system stores timer information in JSON format:

```json
{
  "timer.kitchen": {
    "state": "active",
    "remaining_time": 300,
    "friendly_name": "Kitchen Timer"
  },
  "timer.bedroom": {
    "state": "paused", 
    "remaining_time": 180,
    "friendly_name": "Bedroom Timer"
  }
}
```

## Customization

### Change Reboot Time

Edit `nightly_reboot_with_timer_pause.yaml`:

```yaml
trigger:
  - platform: time
    at: '02:30:00'  # Change to desired time
```

### Add Conditions

Add conditions to prevent reboots during certain times:

```yaml
condition:
  - condition: time
    weekday:
      - mon
      - tue
      - wed
      - thu
      - fri
  - condition: state
    entity_id: binary_sensor.away_mode
    state: 'off'
```

### Exclude Specific Timers

Modify `pause_all_timers_script.py` to exclude certain timers:

```python
# Add exclusion list
excluded_timers = ['timer.always_running', 'timer.system_timer']

# Skip excluded timers
if entity_id in excluded_timers:
    continue
```

## Troubleshooting

### Check Logs

Monitor the logs for automation execution:

1. Go to **Settings** → **System** → **Logs**
2. Filter by "Nightly Reboot" or "Timer"
3. Look for any error messages

### Manual Testing

Test the pause/resume functionality manually:

1. Start a timer
2. Go to **Developer Tools** → **Services**
3. Call `python_script.pause_all_timers_script`
4. Check that timer is paused and state is stored
5. Call `python_script.restore_timer_states`
6. Verify timer resumes with correct time

### Common Issues

**Timers not resuming**: Check that `/config/.timer_states.json` exists and contains valid data

**Python script errors**: Ensure `python_script:` is in your configuration.yaml

**Automation not triggering**: Verify the automation is enabled in **Settings** → **Automations & Scenes**

## Safety Features

- **Graceful Error Handling**: Scripts continue even if individual timers fail
- **State Validation**: Checks timer existence before attempting operations
- **Logging**: Comprehensive logging for debugging
- **File Cleanup**: Removes state file after successful restoration
- **Startup Delay**: Waits for system to be ready before restoring timers

## Requirements

- Home Assistant with Python Scripts enabled
- Timer entities in your Home Assistant setup
- File system access for state storage

## Support

For issues or questions:
1. Check the Home Assistant logs
2. Verify all files are in the correct locations
3. Ensure Python Scripts are enabled
4. Test individual components manually
