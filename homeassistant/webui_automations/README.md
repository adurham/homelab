# Home Assistant Web UI Automations

This directory contains all automations that were created through the Home Assistant web UI, organized into individual files for better version control and management.

## 📁 Directory Structure

```
webui_automations/
├── automations.yaml                    # Original combined automations file
├── simple_parse.py                     # Script to parse automations.yaml
├── deploy_individual_automations.py    # Script to deploy individual automations
├── individual_automations/             # Individual automation files organized by category
│   ├── lighting/                       # Lighting-related automations
│   ├── pool/                          # Pool and pump automations
│   ├── cleaning/                      # Vacuum and cleaning automations
│   ├── plumbing/                      # Water heater and plumbing automations
│   ├── garage/                        # Garage-related automations
│   ├── system/                        # System and seasonal automations
│   ├── entertainment/                 # Entertainment system automations
│   ├── security/                      # Security and outdoor lighting automations
│   └── general/                       # General purpose automations
└── README.md                          # This file
```

## 🔍 Current Automations

### Lighting (6 automations)
- **Midnight lights off** - Turns off porch, stairs, and cat room lights at midnight
- **Turn Off Lights - 30 mins Before Sunrise** - Automated light control based on sunrise
- **Turn On Lights - 30 mins Before Sunset** - Automated light control based on sunset
- **Hue Sync Box - Revert to Natural Light** - Reverts to natural lighting when Hue sync stops
- **Garage Lights - Occupancy Control** - Smart garage lighting with occupancy detection
- **Backyard floodlight** - Motion-activated outdoor floodlight with 15-minute timeout

### Pool (3 automations)
- **Pool Pump - On After Sunset** - Runs pool pump for 6 hours after sunset during pool season
- **System - Auto Pool Season ON** - Automatically enables pool season on May 1st
- **System - Auto Pool Season OFF** - Automatically disables pool season on October 1st

### Cleaning (2 automations)
- **Vacuum - Upstairs Daily Cleaning** - Daily vacuuming of upstairs at 11:00 AM
- **Vacuum - Downstairs High-Traffic Cleaning** - Multiple daily vacuuming sessions

### Plumbing (1 automation)
- **Smart Hot Water Recirculation Control** - On-demand hot water circulation with occupancy detection

## 🚀 Usage

### View Individual Automations
Each automation is stored in its own YAML file within the appropriate category directory. You can:
- Edit individual automations without affecting others
- Track changes with version control
- Share specific automations
- Organize automations by function

### Deploy Individual Automations
To deploy all individual automations back to Home Assistant:

```bash
cd /Users/adam.durham/repos/homelab/homeassistant/webui_automations
python3 deploy_individual_automations.py
```

This will:
1. Create a backup of your current `automations.yaml`
2. Deploy all individual automation files to `/config/automations/`
3. Update `configuration.yaml` to use the automation directory
4. Restart Home Assistant

### Deploy Specific Categories
To deploy only specific categories, you can manually copy files:

```bash
# Deploy only lighting automations
scp individual_automations/lighting/*.yaml root@192.168.86.2:/config/automations/

# Deploy only pool automations
scp individual_automations/pool/*.yaml root@192.168.86.2:/config/automations/
```

### Add New Automations
When you create new automations in the Home Assistant web UI:

1. **Extract the new automation**:
   ```bash
   # Pull updated automations.yaml
   scp root@192.168.86.2:/config/automations.yaml ./
   
   # Parse and create individual files
   python3 simple_parse.py
   ```

2. **Edit individual files** as needed

3. **Deploy back to Home Assistant**:
   ```bash
   python3 deploy_individual_automations.py
   ```

## 🔧 Automation Details

### Lighting Automations
- **Smart Scheduling**: Automations use sunrise/sunset triggers for natural lighting control
- **Occupancy Detection**: Garage lights use occupancy sensors for efficient operation
- **Scene Integration**: Hue Sync Box automation integrates with natural light scenes

### Pool Automations
- **Seasonal Control**: Automatic pool season management based on dates
- **Weather Awareness**: Pool pump considers temperature conditions
- **Efficient Operation**: 6-hour runtime after sunset during pool season

### Cleaning Automations
- **Scheduled Cleaning**: Upstairs cleaned daily at 11:00 AM
- **High-Traffic Areas**: Downstairs cleaned 5 times daily at optimal times
- **Smart Timing**: Avoids feeding times and high-activity periods

### Plumbing Automations
- **On-Demand Heating**: Hot water circulation triggered by occupancy
- **Smart Logic**: Different behavior for day/night operation
- **Cooldown Protection**: Prevents excessive pump cycling

## 🛠️ Maintenance

### Regular Tasks
1. **Backup automations** before making changes
2. **Test individual automations** after modifications
3. **Monitor logs** for automation execution issues
4. **Update automation files** when making web UI changes

### Troubleshooting
- Check Home Assistant logs for automation errors
- Verify entity IDs are correct in automation files
- Ensure all required integrations are installed
- Test automation triggers manually

### Version Control
- Each automation file can be tracked independently
- Use git to track changes to individual automations
- Create branches for testing new automation logic
- Tag releases for stable automation configurations

## 📝 Notes

- All automation IDs are preserved from the original web UI creation
- Descriptions and metadata are maintained in individual files
- Category organization is based on automation aliases and functionality
- Files use consistent naming conventions for easy identification

## 🔗 Related Files

- `/config/automations.yaml` - Combined automation file (backup)
- `/config/automations/` - Individual automation files (deployed)
- `/config/configuration.yaml` - Home Assistant main configuration
