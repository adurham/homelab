# Home Assistant REST API Quick Reference

## 🔐 Authentication

```bash
Authorization: Bearer YOUR_TOKEN_HERE
```

## 📋 Essential Endpoints

### Health Check
```bash
curl -H "Authorization: Bearer TOKEN" \
     http://IP:8123/api/
```

### Get All Entities
```bash
curl -H "Authorization: Bearer TOKEN" \
     http://IP:8123/api/states
```

### Get Specific Entity
```bash
curl -H "Authorization: Bearer TOKEN" \
     http://IP:8123/api/states/entity.id
```

### Set Entity State
```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"state": "new_value"}' \
     http://IP:8123/api/states/entity.id
```

## 🔧 Service Calls

### Turn On Light
```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"entity_id": "light.room"}' \
     http://IP:8123/api/services/light/turn_on
```

### Turn Off Switch
```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"entity_id": "switch.device"}' \
     http://IP:8123/api/services/switch/turn_off
```

### Restart Home Assistant
```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://IP:8123/api/services/homeassistant/restart
```

## 📊 History

### Get Historical Data
```bash
curl -H "Authorization: Bearer TOKEN" \
     "http://IP:8123/api/history/period/START_TIME?filter_entity_id=entity.id"
```

## 🎯 Events

### Fire Custom Event
```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"key": "value"}' \
     http://IP:8123/api/events/event_type
```

## 🔍 Templates

### Render Template
```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"template": "{{ states(\"entity.id\") }}"}' \
     http://IP:8123/api/template
```

## 🐍 Python Quick Examples

```python
import requests

HA_URL = "http://IP:8123"
HA_TOKEN = "your_token"
headers = {"Authorization": f"Bearer {HA_TOKEN}"}

# Get entity state
response = requests.get(f"{HA_URL}/api/states/entity.id", headers=headers)
print(response.json()["state"])

# Turn on light
requests.post(f"{HA_URL}/api/services/light/turn_on", 
              headers=headers, 
              json={"entity_id": "light.room"})

# Set sensor value
requests.post(f"{HA_URL}/api/states/sensor.temp", 
              headers=headers, 
              json={"state": "25.5"})
```

## 📝 Common Entity Types

- `light.*` - Lights
- `switch.*` - Switches  
- `sensor.*` - Sensors
- `binary_sensor.*` - Binary sensors
- `automation.*` - Automations
- `script.*` - Scripts
- `climate.*` - Climate devices
- `cover.*` - Covers (blinds, garage doors)

## 🚨 Status Codes

- **200/201**: Success
- **400**: Bad Request
- **401**: Unauthorized
- **404**: Not Found
- **405**: Method Not Allowed
