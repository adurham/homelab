# Home Assistant Configuration Management

This directory contains the configuration files and deployment scripts for the Home Assistant setup.

## 🚀 Quick Start

### 1. Initial Setup
```bash
# Copy the example configuration file
cp ha_config.env.example ha_config.env

# Edit ha_config.env with your actual Home Assistant credentials
# Get your token from: http://homeassistant.local:8123/profile

# Run the setup script to create virtual environment and install dependencies
./setup_venv.sh
```

### 2. Deploy Configuration
```bash
# Deploy all configuration files to Home Assistant
./deploy_homeassistant.sh
```

## 📁 Directory Structure

```
homeassistant/
├── automations.yaml          # Main automation include file
├── scripts.yaml             # Main script include file
├── configuration.yaml       # Main HA configuration
├── automations/             # Automation files
│   └── vent_control/
│       ├── smart_vent_control_system.yaml
│       ├── manual_vent_control.yaml
│       └── README.md
├── scripts/                 # Script files
│   └── vent_control/
│       ├── control_all_room_vents.yaml
│       ├── control_room_vent.yaml
│       └── README.md
├── venv/                    # Python virtual environment (gitignored)
├── requirements.txt         # Python dependencies
├── .yamllint               # YAML linting configuration
├── .gitignore              # Git ignore rules
├── ha_config.env.example   # Example configuration file
├── deploy_homeassistant.sh  # Deployment script
├── setup_venv.sh           # Setup script
└── README.md               # This file
```

## 🔧 Current Systems

### Vent Control System
- **Purpose**: Intelligent vent control based on occupancy and temperature
- **Coverage**: 8 rooms with 10 total vents
- **Logic**: Occupied rooms get priority, unoccupied rooms can drift ±3°F
- **Automation**: `automations/vent_control/smart_vent_control_system.yaml`
- **Scripts**: `scripts/vent_control/control_all_room_vents.yaml`, `scripts/vent_control/control_room_vent.yaml`

### Basement Climate Control
- **Purpose**: Maintain basement temperature around 70°F using HomeKit sensor data
- **Virtual Thermostat**: Create via UI (see `create_basement_climate_helper.sh` for instructions) - shows on dashboards, voice assistant compatible
- **Sensor**: `sensor.7wq7_temperature` (Basement Temperature)
- **Setpoint Helpers**: `input_number.basement_virtual_setpoint`, `input_select.basement_virtual_mode`
- **Actuation**: Template switches drive `climate.basement_heatpump_basement_office_ac` in heat/cool with max output and vertical swing
- **Automation**: `automations/basement_virtual_thermostat.yaml` orchestrates heating/cooling logic
- **Setup**: After deployment, run `./create_basement_climate_helper.sh` for UI setup instructions
- **Configuration**: See `configuration.yaml` `template` (switches), `input_number`, and `input_select` sections

## 🛡️ Security Features

### Deployment Safety
- **Change Detection**: Aborts if `configuration.yaml` modified externally
- **Backup System**: Creates HA CLI backup + file backups with rotation
- **Validation**: Multiple validation layers (yamllint + ha core check)
- **Auto-Restore**: Automatically restores backup if deployment fails
- **Error Handling**: Comprehensive error checking and reporting

### File Security
- **Sensitive files**: `ha_config.env` and `secrets.yaml` are gitignored
- **Example configs**: `ha_config.env.example` and `secrets.yaml.example` provided for setup
- **Virtual environment**: `venv/` directory is gitignored
- **Secrets management**: Home Assistant uses `secrets.yaml` for sensitive configuration values

## 🔄 Deployment Process

### What the deployment script does:
1. **Safety Checks**: Verifies `configuration.yaml` hasn't been modified externally
2. **Local Validation**: Runs `yamllint` on local files
3. **Backup Creation**: Creates HA CLI backup + file backups with rotation
4. **Deploy Files**: Copies files safely to Home Assistant
5. **Remote Validation**: Runs `ha core check` on deployed configuration
6. **Auto-Restore**: If validation fails, automatically restores from backup
7. **Restart**: Only restarts Home Assistant if validation passed
8. **Verification**: Confirms Home Assistant is running

## 📋 Requirements

- Python 3.x
- SSH access to Home Assistant box
- Home Assistant CLI (`ha`) installed on target system
- Long-lived access token for Home Assistant API

## 🔧 Configuration

### Environment Setup
1. Copy `ha_config.env.example` to `ha_config.env`
2. Edit `ha_config.env` with your Home Assistant credentials
3. Copy `secrets.yaml.example` to `secrets.yaml`
4. Edit `secrets.yaml` with your InfluxDB credentials and other secrets
5. Run `./setup_venv.sh` to install dependencies



### Adding New Systems
1. Create new directories in `automations/` and `scripts/`
2. Add your automation and script files
3. Deploy with `./deploy_homeassistant.sh`

## 🚨 Troubleshooting

### Deployment Fails
- Check `ha_config.env` has correct credentials
- Verify SSH access to Home Assistant box
- Run `./setup_venv.sh` if virtual environment issues

### Configuration Issues
- Check logs: `ssh -p 2222 root@homeassistant.local "ha core log"`
- Validate config: `ssh -p 2222 root@homeassistant.local "ha core check"`
- Restore backup: `ssh -p 2222 root@homeassistant.local "ha core backup restore <backup_name>"`

## 📚 Documentation

- **Vent Control**: See `automations/vent_control/README.md` and `scripts/vent_control/README.md`
- **Deployment**: See `deploy_homeassistant.sh` for detailed deployment logic
- **YAML Linting**: See `.yamllint` for linting rules