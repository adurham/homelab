# Grafana Integration for Home Assistant Automations

This directory contains scripts to automatically import and set up Grafana dashboards for Home Assistant automation monitoring.

## 🚀 Quick Start

### Option 1: Complete Setup (Recommended)
```bash
# Run the complete Grafana integration setup
./setup_grafana_integration.sh
```

### Option 2: Dashboard Import Only
```bash
# Import just the dashboard
./import_grafana_dashboard.sh
```

### Option 3: Python Script (Advanced)
```bash
# Use the Python script for more control
python3 import_grafana_dashboard.py
```

## 📋 Prerequisites

### 1. Grafana Installation
- **Home Assistant Addon**: Install Grafana addon from Home Assistant Supervisor
- **Manual Installation**: Install Grafana on your network (port 3000)
- **Docker**: Run Grafana in a container

### 2. InfluxDB Installation
- **Home Assistant Addon**: Install InfluxDB addon from Home Assistant Supervisor
- **Database**: Create `homeassistant` database in InfluxDB

### 3. Home Assistant Configuration
- **API Token**: Valid Home Assistant API token
- **Grafana Logging**: Input numbers and sensors configured for metrics

## 🔧 Configuration

### Environment Variables
Set these environment variables before running the scripts:

```bash
# Grafana Configuration
export GRAFANA_URL="http://192.168.86.2:3000"  # or your Grafana URL
export GRAFANA_USER="admin"                     # Grafana username
export GRAFANA_PASSWORD="admin"                 # Grafana password (change default!)

# Home Assistant Configuration
export HA_URL="http://192.168.86.2:8123"       # Home Assistant URL
export HA_TOKEN="your_long_lived_access_token"  # Home Assistant API token
```

### Default Values
If not set, the scripts use these defaults:
- **Grafana URL**: `http://192.168.86.2:3000`
- **Grafana User**: `admin`
- **Grafana Password**: `admin`
- **Home Assistant URL**: `http://192.168.86.2:8123`

## 📊 Dashboard Features

The imported dashboard includes:

### Temperature Balancing Metrics
- **Occupied Rooms Count**: Number of currently occupied rooms
- **Temperature Variance**: Temperature differences between rooms
- **Efficiency Score**: Overall temperature balancing performance

### Hot Water Circulation Metrics
- **Pump Cycles Today**: Number of pump cycles
- **Water Temperature**: Current water temperature
- **Efficiency Score**: Hot water circulation efficiency

### Garage Lights Metrics
- **Door Opens Today**: Number of garage door openings
- **Light On Time**: Total time lights were on
- **Efficiency Score**: Garage lighting efficiency

### System Metrics
- **Automation Triggers**: Number of automation triggers
- **System Performance**: Overall system health

## 🛠️ Scripts Overview

### `setup_grafana_integration.sh`
**Complete setup script** that:
- Tests Grafana connectivity
- Tests Home Assistant connectivity
- Checks InfluxDB addon status
- Imports the dashboard
- Provides next steps

### `import_grafana_dashboard.sh`
**Simple dashboard import** using curl commands:
- Tests Grafana connection
- Authenticates with Grafana
- Imports dashboard JSON
- Provides dashboard URL

### `import_grafana_dashboard.py`
**Advanced Python script** with:
- Comprehensive error handling
- API key management
- Datasource verification
- Detailed logging

## 🔍 Troubleshooting

### Common Issues

#### Grafana Not Accessible
```
❌ Cannot connect to Grafana at http://192.168.86.2:3000
```
**Solutions:**
1. Check Grafana addon is installed and started
2. Verify the URL is correct
3. Check network connectivity
4. Try alternative URLs:
   - `http://192.168.86.2:8123/grafana` (Home Assistant addon)
   - `http://homeassistant.local:3000`

#### Authentication Failed
```
❌ Failed to get API key. Please check credentials.
```
**Solutions:**
1. Check Grafana username and password
2. Set environment variables:
   ```bash
   export GRAFANA_USER="your_username"
   export GRAFANA_PASSWORD="your_password"
   ```
3. Try default credentials: `admin` / `admin`

#### Dashboard Import Failed
```
❌ Dashboard import failed (HTTP 400)
```
**Solutions:**
1. Check dashboard JSON file exists and is valid
2. Verify Grafana permissions
3. Check if dashboard with same name already exists
4. Try manual import in Grafana UI

#### No Data in Dashboard
```
Dashboard shows "No data"
```
**Solutions:**
1. Verify InfluxDB datasource is configured
2. Check Home Assistant is sending data to InfluxDB
3. Verify input_number and sensor entities exist
4. Check automation logging is working

### Manual Setup Steps

If automated setup fails, you can set up manually:

#### 1. Configure InfluxDB Datasource
1. Open Grafana → Configuration → Data Sources
2. Add InfluxDB datasource
3. **URL**: `http://a0d7b954-influxdb:8086`
4. **Database**: `homeassistant`
5. **User**: `homeassistant`
6. **Password**: `homeassistant`
7. Save & Test

#### 2. Import Dashboard
1. Open Grafana → + → Import
2. Upload `grafana_dashboard.json`
3. Select InfluxDB datasource
4. Import

#### 3. Verify Home Assistant Configuration
Ensure your `configuration.yaml` includes:
```yaml
# Grafana Logging Configuration
input_number:
  occupied_rooms_count:
    name: "Occupied Rooms Count"
    initial: 0
    min: 0
    max: 20
    step: 1
    unit_of_measurement: "rooms"

# ... (see configuration_grafana_logging.yaml for full config)

influxdb:
  host: a0d7b954-influxdb
  port: 8086
  database: homeassistant
  username: homeassistant
  password: homeassistant
```

## 📈 Usage

### Viewing Metrics
1. Open Grafana: `http://192.168.86.2:3000`
2. Navigate to "Home Assistant Automation Performance" dashboard
3. Select time range and refresh interval
4. Monitor automation performance metrics

### Customizing Dashboard
1. Edit dashboard in Grafana
2. Modify panels, queries, or visualizations
3. Save changes
4. Export updated dashboard JSON if needed

### Adding New Metrics
1. Add new input_number or sensor entities in Home Assistant
2. Update automation logging to include new metrics
3. Add new panels to Grafana dashboard
4. Configure InfluxDB queries for new data

## 🔒 Security Notes

- **Change default Grafana password** from `admin`
- **Use environment variables** for credentials
- **Restrict network access** to Grafana if needed
- **Regular backups** of dashboard configurations

## 📚 Related Files

- `grafana_dashboard.json` - Dashboard configuration
- `configuration_grafana_logging.yaml` - Home Assistant logging config
- `create_grafana_automations_simple.py` - Automation deployment
- `RULES.md` - Development rules and guidelines

## 🆘 Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review Home Assistant and Grafana logs
3. Verify network connectivity and credentials
4. Try manual setup steps
5. Check Home Assistant community forums

---

**Happy monitoring!** 📊✨
