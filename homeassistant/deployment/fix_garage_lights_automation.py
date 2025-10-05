#!/usr/bin/env python3

"""
Fix Garage Lights Automation
Replaces the broken garage lights automation with the proper one from repository
"""

import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error

# Configuration
HA_URL = os.getenv('HA_URL', 'http://homeassistant.local:8123')
HA_TOKEN = os.getenv('HA_TOKEN')

def make_api_request(endpoint, method='GET', data=None):
    """Make API request to Home Assistant"""
    url = f"{HA_URL}/api/{endpoint}"
    
    headers = {
        'Authorization': f'Bearer {HA_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    request_data = None
    if data:
        request_data = json.dumps(data).encode('utf-8')
    
    req = urllib.request.Request(url, data=request_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                return json.loads(response.read().decode('utf-8'))
            else:
                print(f"❌ API request failed: {response.status}")
                return None
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error: {e.code} - {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"❌ URL Error: {e.reason}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return None

def create_proper_garage_lights_automation():
    """Create the proper garage lights automation"""
    
    automation = {
        "id": "garage_lights_final",
        "alias": "Garage Lights - Multi-Door Motion Control",
        "description": "Turns lights on when any garage door opens (if not already on), turns off 15 minutes after last motion",
        "triggers": [
            {
                "platform": "state",
                "entity_id": [
                    "cover.left_garage_door",
                    "cover.middle_garage_bay_door", 
                    "cover.right_garage_bay_door"
                ],
                "to": "open",
                "id": "garage_door_opened"
            },
            {
                "platform": "state",
                "entity_id": "binary_sensor.garage_door_motion",
                "to": "on",
                "id": "motion_detected"
            }
        ],
        "action": [
            {
                "choose": [
                    {
                        "conditions": [
                            {
                                "condition": "trigger",
                                "id": "garage_door_opened"
                            },
                            {
                                "condition": "state",
                                "entity_id": "switch.garage_main_lights",
                                "state": "off"
                            }
                        ],
                        "sequence": [
                            {
                                "service": "switch.turn_on",
                                "target": {
                                    "entity_id": "switch.garage_main_lights"
                                }
                            },
                            {
                                "service": "system_log.write",
                                "data": {
                                    "message": "Garage lights turned on - door opened (was off)",
                                    "level": "info"
                                }
                            }
                        ]
                    },
                    {
                        "conditions": [
                            {
                                "condition": "trigger",
                                "id": "garage_door_opened"
                            },
                            {
                                "condition": "state",
                                "entity_id": "switch.garage_main_lights",
                                "state": "on"
                            }
                        ],
                        "sequence": [
                            {
                                "service": "system_log.write",
                                "data": {
                                    "message": "Garage door opened but lights already on - no action needed",
                                    "level": "info"
                                }
                            }
                        ]
                    },
                    {
                        "conditions": [
                            {
                                "condition": "trigger",
                                "id": "motion_detected"
                            }
                        ],
                        "sequence": [
                            {
                                "service": "system_log.write",
                                "data": {
                                    "message": "Garage motion detected - resetting 15-minute timer",
                                    "level": "info"
                                }
                            }
                        ]
                    }
                ]
            },
            {
                "delay": "00:15:00"
            },
            {
                "condition": "state",
                "entity_id": "binary_sensor.garage_door_motion",
                "state": "off",
                "for": {
                    "minutes": 1
                }
            },
            {
                "service": "switch.turn_off",
                "target": {
                    "entity_id": "switch.garage_main_lights"
                }
            },
            {
                "service": "system_log.write",
                "data": {
                    "message": "Garage lights turned off - 15 minutes after last motion",
                    "level": "info"
                }
            }
        ],
        "mode": "restart"
    }
    
    return automation

def main():
    """Main function"""
    print("🔧 FIXING GARAGE LIGHTS AUTOMATION")
    print("=" * 50)
    
    # Validate environment
    if not HA_TOKEN:
        print("❌ HA_TOKEN environment variable not set")
        sys.exit(1)
    
    print(f"🔗 Home Assistant URL: {HA_URL}")
    print("")
    
    # Create the proper automation
    print("🔨 Creating proper garage lights automation...")
    automation = create_proper_garage_lights_automation()
    
    # Deploy the automation
    print(f"🚀 Deploying automation: {automation['id']} ({automation['alias']})")
    
    result = make_api_request('config/automation/config', method='POST', data=automation)
    
    if result is not None:
        print(f"✅ Successfully deployed: {automation['id']}")
        
        # Try to enable it
        print(f"✅ Enabling automation: {automation['id']}")
        
        enable_data = {
            "entity_id": f"automation.{automation['id']}"
        }
        
        enable_result = make_api_request('services/automation/turn_on', method='POST', data=enable_data)
        
        if enable_result is not None:
            print(f"✅ Successfully enabled: {automation['id']}")
            print("\n🎉 Garage lights automation fixed and deployed!")
            print("💡 The automation will now:")
            print("  • Turn on lights when any garage door opens (if not already on)")
            print("  • Turn off lights 15 minutes after last motion detection")
            print("  • Handle all 3 garage doors properly")
        else:
            print(f"⚠️  Automation deployed but could not be enabled")
    else:
        print(f"❌ Failed to deploy: {automation['id']}")

if __name__ == "__main__":
    main()
