# Home Assistant REST API Documentation

This directory contains comprehensive documentation and examples for using the Home Assistant REST API.

## 📚 Documentation Files

### 📖 Main Guide
- **[HOME_ASSISTANT_REST_API_GUIDE.md](HOME_ASSISTANT_REST_API_GUIDE.md)** - Complete REST API reference guide
  - Authentication setup
  - All API endpoints with examples
  - Python integration examples
  - Error handling and security best practices

### 🔧 Quick Reference
- **[API_QUICK_REFERENCE.md](API_QUICK_REFERENCE.md)** - Quick reference card for common operations
  - Essential endpoints
  - Common cURL commands
  - Python code snippets
  - Status codes reference

### 🐍 Code Examples
- **[hass_api_client.py](hass_api_client.py)** - Complete Python API client class
  - Full-featured HomeAssistantAPI class
  - All REST API methods implemented
  - Error handling and convenience methods
  - Ready-to-use production code

- **[practical_examples.py](practical_examples.py)** - Real-world usage examples
  - 10 practical examples covering common use cases
  - Entity monitoring and control
  - Historical data analysis
  - Custom events and templates
  - System management

## 🚀 Getting Started

### 1. Get Your API Token

1. Open Home Assistant web interface
2. Go to your profile: `http://YOUR_HA_IP:8123/profile`
3. Scroll to "Long-Lived Access Tokens"
4. Create a new token and copy it

### 2. Set Up Environment

```bash
# Create environment file
echo "HA_URL=http://192.168.86.2:8123" > .env
echo "HA_TOKEN=your_long_lived_access_token_here" >> .env

# Or set environment variables
export HA_URL="http://192.168.86.2:8123"
export HA_TOKEN="your_long_lived_access_token_here"
```

### 3. Test Connection

```python
from hass_api_client import HomeAssistantAPI

ha = HomeAssistantAPI("http://192.168.86.2:8123", "your_token")

if ha.is_online():
    print("✅ Connected to Home Assistant")
    print(f"Version: {ha.get_config()['version']}")
else:
    print("❌ Connection failed")
```

## 📋 Common Use Cases

### Entity Management

```python
# Get all entities
entities = ha.get_all_entities()

# Get entities by domain
lights = ha.get_entities_by_domain("light")
sensors = ha.get_entities_by_domain("sensor")

# Get specific entity state
temperature = ha.get_entity("sensor.kitchen_temperature")
```

### Device Control

```python
# Control lights
ha.turn_on_light("light.living_room", brightness=255, color_name="red")
ha.turn_off_light("light.bedroom")

# Control switches
ha.turn_on_switch("switch.garage_door")
ha.turn_off_switch("switch.outdoor_lights")
```

### Automation Management

```python
# Trigger automation
ha.trigger_automation("automation.night_mode")

# Enable/disable automation
ha.enable_automation("automation.morning_routine")
ha.disable_automation("automation.test_automation")

# Check automation status
state = ha.get_automation_state("automation.night_mode")
```

### Historical Data

```python
from datetime import datetime, timedelta

# Get last hour of data
end_time = datetime.now()
start_time = end_time - timedelta(hours=1)

history = ha.get_history(
    ["sensor.kitchen_temperature"], 
    start_time, 
    end_time, 
    minimal=True
)
```

### Custom Events

```python
# Fire custom event
ha.fire_event("custom_alert", {
    "message": "Temperature too high",
    "value": 35.5,
    "threshold": 30.0
})
```

### Template Rendering

```python
# Render template
result = ha.render_template(
    "{{ states.light | selectattr('state', 'equalto', 'on') | list | length }} lights are on"
)
```

## 🔐 Security Best Practices

### Token Management

1. **Store tokens securely**
   ```python
   import os
   from dotenv import load_dotenv
   
   load_dotenv()
   token = os.getenv("HA_TOKEN")
   ```

2. **Rotate tokens regularly**
   - Create new tokens monthly
   - Revoke old tokens immediately

3. **Use minimal permissions**
   - Only create tokens with necessary permissions
   - Avoid admin-level tokens when possible

### Network Security

- Use HTTPS when possible (requires SSL certificate)
- Restrict API access to trusted networks
- Use firewall rules to limit access

### Code Security

- Never commit tokens to version control
- Use environment variables for sensitive data
- Validate all inputs before API calls

## 🛠️ Development Setup

### Install Dependencies

```bash
pip install requests python-dotenv
```

### Project Structure

```
homeassistant/
├── docs/
│   ├── HOME_ASSISTANT_REST_API_GUIDE.md
│   ├── API_QUICK_REFERENCE.md
│   ├── hass_api_client.py
│   ├── practical_examples.py
│   └── README.md
├── .env                    # Environment variables
└── your_scripts.py        # Your custom scripts
```

### Example Project

```python
#!/usr/bin/env python3
"""
My Home Assistant Integration Script
"""

import os
from datetime import datetime
from hass_api_client import HomeAssistantAPI

# Load configuration
HA_URL = os.getenv("HA_URL", "http://192.168.86.2:8123")
HA_TOKEN = os.getenv("HA_TOKEN")

def main():
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    if not ha.is_online():
        print("❌ Home Assistant not accessible")
        return
    
    # Your automation logic here
    lights = ha.get_entities_by_domain("light")
    print(f"Found {len(lights)} lights")
    
    # Turn on all lights after sunset
    current_time = datetime.now()
    if current_time.hour >= 18:  # After 6 PM
        for light in lights:
            ha.turn_on_light(light['entity_id'])

if __name__ == "__main__":
    main()
```

## 🐛 Troubleshooting

### Common Issues

1. **401 Unauthorized**
   - Check your API token
   - Verify token hasn't expired
   - Ensure token has correct permissions

2. **Connection Refused**
   - Verify Home Assistant is running
   - Check IP address and port
   - Ensure network connectivity

3. **404 Not Found**
   - Verify entity ID exists
   - Check entity ID spelling
   - Ensure entity is not disabled

4. **Slow Performance**
   - Use minimal_response for history calls
   - Limit the number of entities queried
   - Use specific entity IDs instead of getting all entities

### Debug Mode

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# This will show detailed request/response information
ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
```

### Testing API Connectivity

```bash
# Test with cURL
curl -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     http://192.168.86.2:8123/api/

# Expected response: {"message": "API running."}
```

## 📖 Additional Resources

- [Official Home Assistant REST API Documentation](https://developers.home-assistant.io/docs/api/rest)
- [Home Assistant WebSocket API](https://developers.home-assistant.io/docs/api/websocket)
- [Home Assistant Template Documentation](https://www.home-assistant.io/docs/configuration/templating/)
- [Home Assistant Automation Documentation](https://www.home-assistant.io/docs/automation/)

## 🤝 Contributing

Feel free to improve this documentation by:
- Adding more examples
- Fixing errors or typos
- Adding new use cases
- Improving code examples

## 📄 License

This documentation is provided as-is for educational and reference purposes. Please refer to Home Assistant's official documentation for the most up-to-date information.
