# Home Assistant REST API Guide

## Overview

Home Assistant provides a comprehensive RESTful API on the same port as the web frontend (default port 8123). This guide covers how to use the REST API for automation, monitoring, and integration purposes.

**Base URL**: `http://IP_ADDRESS:8123/api/`

## 🔐 Authentication

All API calls require authentication using a Long-Lived Access Token in the Authorization header:

```http
Authorization: Bearer YOUR_TOKEN_HERE
```

### Getting an Access Token

1. Log into Home Assistant web interface
2. Go to your profile: `http://IP_ADDRESS:8123/profile`
3. Scroll to "Long-Lived Access Tokens"
4. Create a new token and copy it carefully
5. Store it securely (e.g., in environment variables)

### Example Authentication Headers

```bash
# cURL
-H "Authorization: Bearer YOUR_TOKEN_HERE"

# Python requests
headers = {"Authorization": "Bearer YOUR_TOKEN_HERE"}
```

## 📋 Core API Endpoints

### 1. Health Check

**GET** `/api/`

Check if the API is running.

```bash
curl -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8123/api/
```

**Response:**
```json
{
  "message": "API running."
}
```

### 2. Configuration

**GET** `/api/config`

Get current Home Assistant configuration.

```bash
curl -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8123/api/config
```

**Response:**
```json
{
  "components": ["sensor.cpuspeed", "frontend", "config.core"],
  "config_dir": "/home/ha/.homeassistant",
  "elevation": 510,
  "latitude": 45.8781529,
  "location_name": "Home",
  "longitude": 8.458853651,
  "time_zone": "Europe/Zurich",
  "unit_system": {
    "length": "km",
    "mass": "g", 
    "temperature": "°C",
    "volume": "L"
  },
  "version": "0.56.2"
}
```

### 3. Components

**GET** `/api/components`

Get list of currently loaded components.

```bash
curl -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8123/api/components
```

### 4. Events

**GET** `/api/events`

Get array of event objects with listener counts.

```bash
curl -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8123/api/events
```

**Response:**
```json
[
  {
    "event": "state_changed",
    "listener_count": 5
  },
  {
    "event": "time_changed", 
    "listener_count": 2
  }
]
```

### 5. Services

**GET** `/api/services`

Get available services organized by domain.

```bash
curl -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8123/api/services
```

**Response:**
```json
[
  {
    "domain": "light",
    "services": ["turn_on", "turn_off", "toggle"]
  },
  {
    "domain": "switch",
    "services": ["turn_on", "turn_off", "toggle"]
  }
]
```

## 🏠 Entity Management

### Get All States

**GET** `/api/states`

Get all entity states.

```bash
curl -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8123/api/states
```

### Get Specific Entity State

**GET** `/api/states/<entity_id>`

Get state of a specific entity.

```bash
curl -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8123/api/states/sensor.kitchen_temperature
```

**Response:**
```json
{
  "attributes": {
    "friendly_name": "Kitchen Temperature",
    "unit_of_measurement": "°C"
  },
  "entity_id": "sensor.kitchen_temperature",
  "last_changed": "2024-01-15T10:30:00+00:00",
  "last_updated": "2024-01-15T10:30:00+00:00",
  "state": "22.5"
}
```

### Set Entity State

**POST** `/api/states/<entity_id>`

Set the state of an entity.

```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"state": "25", "attributes": {"unit_of_measurement": "°C"}}' \
     http://localhost:8123/api/states/sensor.kitchen_temperature
```

### Delete Entity

**DELETE** `/api/states/<entity_id>`

Delete an entity.

```bash
curl -X DELETE \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8123/api/states/sensor.kitchen_temperature
```

## 🔧 Service Calls

### Call Service

**POST** `/api/services/<domain>/<service>`

Call a Home Assistant service.

```bash
# Turn on a light
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"entity_id": "light.study_light"}' \
     http://localhost:8123/api/services/light/turn_on

# Turn off a switch
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"entity_id": "switch.christmas_lights"}' \
     http://localhost:8123/api/services/switch/turn_off
```

**Response:**
```json
[
  {
    "attributes": {},
    "entity_id": "light.study_light",
    "last_changed": "2024-01-15T10:30:00+00:00",
    "state": "on"
  }
]
```

### Service with Response Data

Add `?return_response` to get service response data:

```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"entity_id": "weather.forecast_home", "type": "daily"}' \
     http://localhost:8123/api/services/weather/get_forecasts?return_response
```

## 📊 History and Logs

### Get Historical Data

**GET** `/api/history/period/<timestamp>`

Get historical state changes. The timestamp is optional and defaults to 1 day ago.

**Required Parameters:**
- `filter_entity_id=<entity_ids>` - Comma-separated entity IDs

**Optional Parameters:**
- `end_time=<timestamp>` - End time (defaults to 1 day)
- `minimal_response` - Faster response with less data
- `no_attributes` - Skip attributes for speed
- `significant_changes_only` - Only significant changes

```bash
curl -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     "http://localhost:8123/api/history/period/2024-01-15T00:00:00+00:00?filter_entity_id=sensor.kitchen_temperature"
```

## 🎯 Event Handling

### Fire Event

**POST** `/api/events/<event_type>`

Fire a custom event.

```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"next_rising": "2024-01-16T07:30:00+00:00"}' \
     http://localhost:8123/api/events/sunrise_alert
```

**Response:**
```json
{
  "message": "Event sunrise_alert fired."
}
```

## 🔍 Template Rendering

### Render Template

**POST** `/api/template`

Render Home Assistant templates.

```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"template": "Paulus is at {{ states(\"device_tracker.paulus\") }}!"}' \
     http://localhost:8123/api/template
```

**Response:**
```
Paulus is at work!
```

## ⚙️ Configuration Management

### Check Configuration

**POST** `/api/config/core/check_config`

Validate configuration.yaml (requires config integration).

```bash
curl -X POST \
     -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8123/api/config/core/check_config
```

**Success Response:**
```json
{
  "errors": null,
  "result": "valid"
}
```

**Error Response:**
```json
{
  "errors": "Integration not found: frontend:",
  "result": "invalid"
}
```

## 🐍 Python Examples

### Basic Setup

```python
import requests
import json

# Configuration
HA_URL = "http://192.168.86.2:8123"
HA_TOKEN = "your_long_lived_access_token_here"

headers = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json"
}

# Test connection
response = requests.get(f"{HA_URL}/api/", headers=headers)
print(response.json())
```

### Get All Entities

```python
def get_all_entities():
    response = requests.get(f"{HA_URL}/api/states", headers=headers)
    if response.status_code == 200:
        entities = response.json()
        for entity in entities:
            print(f"{entity['entity_id']}: {entity['state']}")
    else:
        print(f"Error: {response.status_code}")

get_all_entities()
```

### Control Lights

```python
def turn_on_light(entity_id):
    data = {"entity_id": entity_id}
    response = requests.post(
        f"{HA_URL}/api/services/light/turn_on",
        headers=headers,
        json=data
    )
    return response.status_code == 200

# Usage
turn_on_light("light.living_room")
```

### Set Entity State

```python
def set_sensor_value(entity_id, value, unit=None):
    data = {"state": str(value)}
    if unit:
        data["attributes"] = {"unit_of_measurement": unit}
    
    response = requests.post(
        f"{HA_URL}/api/states/{entity_id}",
        headers=headers,
        json=data
    )
    return response.status_code in [200, 201]

# Usage
set_sensor_value("sensor.kitchen_temperature", 25.5, "°C")
```

### Get Historical Data

```python
import datetime

def get_historical_data(entity_ids, start_time=None, end_time=None):
    if start_time is None:
        start_time = datetime.datetime.now() - datetime.timedelta(days=1)
    
    params = {
        "filter_entity_id": ",".join(entity_ids),
        "minimal_response": "1"
    }
    
    if end_time:
        params["end_time"] = end_time.isoformat()
    
    response = requests.get(
        f"{HA_URL}/api/history/period/{start_time.isoformat()}",
        headers=headers,
        params=params
    )
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.status_code}")
        return None

# Usage
data = get_historical_data(["sensor.kitchen_temperature"])
```

### Fire Custom Event

```python
def fire_event(event_type, event_data=None):
    data = event_data or {}
    response = requests.post(
        f"{HA_URL}/api/events/{event_type}",
        headers=headers,
        json=data
    )
    return response.status_code == 200

# Usage
fire_event("custom_automation_trigger", {
    "source": "api_call",
    "timestamp": datetime.datetime.now().isoformat()
})
```

## 🔄 Automation Integration

### Create Automation via API

While you can't directly create automations via REST API, you can:

1. **Trigger existing automations** by firing events
2. **Call automation services** to control them
3. **Monitor automation states**

```python
def trigger_automation(automation_entity_id):
    # Enable automation if needed
    data = {"entity_id": automation_entity_id}
    requests.post(f"{HA_URL}/api/services/automation/turn_on", headers=headers, json=data)
    
    # Trigger the automation
    fire_event("automation_triggered", {"automation": automation_entity_id})

def get_automation_status():
    response = requests.get(f"{HA_URL}/api/states", headers=headers)
    if response.status_code == 200:
        entities = response.json()
        automations = [e for e in entities if e['entity_id'].startswith('automation.')]
        for automation in automations:
            print(f"{automation['entity_id']}: {automation['state']}")
```

## 🚨 Error Handling

### HTTP Status Codes

- **200/201**: Success
- **400**: Bad Request
- **401**: Unauthorized (check your token)
- **404**: Not Found
- **405**: Method Not Allowed

### Python Error Handling

```python
def safe_api_call(url, method="GET", data=None):
    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        
        if response.status_code in [200, 201]:
            return response.json()
        else:
            print(f"API Error {response.status_code}: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None

# Usage
result = safe_api_call(f"{HA_URL}/api/states/sensor.kitchen_temperature")
```

## 🔐 Security Best Practices

### Token Management

1. **Store tokens securely** - Use environment variables or secure config files
2. **Rotate tokens regularly** - Create new tokens and revoke old ones
3. **Use minimal permissions** - Only create tokens with necessary permissions
4. **Never commit tokens** - Add token files to `.gitignore`

### Environment Variables

```bash
# .env file
HA_URL=http://192.168.86.2:8123
HA_TOKEN=your_long_lived_access_token_here
```

```python
import os
from dotenv import load_dotenv

load_dotenv()

HA_URL = os.getenv("HA_URL")
HA_TOKEN = os.getenv("HA_TOKEN")
```

## 📚 Common Use Cases

### 1. Home Assistant Integration Script

```python
class HomeAssistantAPI:
    def __init__(self, url, token):
        self.url = url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def get_entity_state(self, entity_id):
        response = requests.get(
            f"{self.url}/api/states/{entity_id}",
            headers=self.headers
        )
        return response.json() if response.status_code == 200 else None
    
    def call_service(self, domain, service, entity_id=None, **kwargs):
        data = kwargs
        if entity_id:
            data["entity_id"] = entity_id
        
        response = requests.post(
            f"{self.url}/api/services/{domain}/{service}",
            headers=self.headers,
            json=data
        )
        return response.status_code in [200, 201]
    
    def get_entities_by_domain(self, domain):
        response = requests.get(f"{self.url}/api/states", headers=self.headers)
        if response.status_code == 200:
            entities = response.json()
            return [e for e in entities if e['entity_id'].startswith(f"{domain}.")]
        return []

# Usage
ha = HomeAssistantAPI("http://192.168.86.2:8123", "your_token")

# Get all lights
lights = ha.get_entities_by_domain("light")
for light in lights:
    print(f"{light['entity_id']}: {light['state']}")

# Turn on a light
ha.call_service("light", "turn_on", "light.living_room")
```

### 2. Monitoring Script

```python
def monitor_entities(entity_ids, callback=None):
    """Monitor specific entities for state changes"""
    previous_states = {}
    
    while True:
        response = requests.get(f"{HA_URL}/api/states", headers=headers)
        if response.status_code == 200:
            entities = response.json()
            current_states = {e['entity_id']: e['state'] for e in entities 
                            if e['entity_id'] in entity_ids}
            
            for entity_id, current_state in current_states.items():
                if entity_id in previous_states and previous_states[entity_id] != current_state:
                    print(f"{entity_id} changed from {previous_states[entity_id]} to {current_state}")
                    if callback:
                        callback(entity_id, previous_states[entity_id], current_state)
            
            previous_states = current_states
        
        time.sleep(5)  # Check every 5 seconds

# Usage
def on_state_change(entity_id, old_state, new_state):
    print(f"State change detected: {entity_id}")

monitor_entities(["sensor.kitchen_temperature", "light.living_room"], on_state_change)
```

## 📖 References

- [Official Home Assistant REST API Documentation](https://developers.home-assistant.io/docs/api/rest)
- [Home Assistant WebSocket API](https://developers.home-assistant.io/docs/api/websocket)
- [Home Assistant Template Documentation](https://www.home-assistant.io/docs/configuration/templating/)

## 🔧 Troubleshooting

### Common Issues

1. **401 Unauthorized**: Check your API token
2. **404 Not Found**: Verify entity ID exists
3. **Connection refused**: Check Home Assistant is running and accessible
4. **Slow responses**: Use minimal_response parameter for history calls

### Debug Mode

```python
import logging

logging.basicConfig(level=logging.DEBUG)

# This will show detailed request/response information
response = requests.get(f"{HA_URL}/api/states", headers=headers)
```

---

**Note**: This guide covers the most commonly used REST API endpoints. For the complete API reference, see the [official documentation](https://developers.home-assistant.io/docs/api/rest).
