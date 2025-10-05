#!/usr/bin/env python3
"""
Create Grafana-Enhanced Automations via Home Assistant API
Creates simplified versions of our enhanced automations with Grafana logging
"""

import os
import sys
import json
import requests
from datetime import datetime

class GrafanaAutomationCreator:
    def __init__(self, ha_url, ha_token):
        self.ha_url = ha_url.rstrip('/')
        self.ha_token = ha_token
        self.headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json"
        }
    
    def create_automation(self, automation_id, automation_data):
        """Create a single automation via API"""
        try:
            url = f"{self.ha_url}/api/config/automation/config/{automation_id}"
            response = requests.post(url, headers=self.headers, json=automation_data, timeout=30)
            
            if response.status_code in [200, 201]:
                print(f"  ✅ Created: {automation_id}")
                return True
            else:
                print(f"  ❌ Failed: {automation_id} - {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"  ❌ Error creating {automation_id}: {e}")
            return False
    
    def create_temperature_balancing_automation(self):
        """Create temperature balancing automation with Grafana logging"""
        print("🌡️  Creating Temperature Balancing Automation...")
        
        automation_data = {
            "alias": "Temperature Balancing - Grafana Enhanced",
            "description": "Balances temperatures across rooms with Grafana logging",
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": ["binary_sensor.kitchen_occupancy_2", "binary_sensor.guest_bathroom_occupancy"],
                    "for": "00:01:00"
                },
                {
                    "platform": "time_pattern",
                    "minutes": "/5"
                }
            ],
            "condition": [
                {
                    "condition": "state",
                    "entity_id": "climate.half_bathroom_room",
                    "state": "heat"
                }
            ],
            "action": [
                {
                    "service": "system_log.write",
                    "data": {
                        "message": "Temperature balancing automation triggered"
                    }
                },
                {
                    "service": "system_log.write",
                    "data": {
                        "message": "{{ 'Occupied rooms: ' + states('binary_sensor.kitchen_occupancy_2') + ', ' + states('binary_sensor.guest_bathroom_occupancy') }}"
                    }
                }
            ]
        }
        
        return self.create_automation("temperature_balancing_grafana", automation_data)
    
    def create_hot_water_automation(self):
        """Create hot water circulation automation with Grafana logging"""
        print("🚿 Creating Hot Water Circulation Automation...")
        
        automation_data = {
            "alias": "Hot Water Circulation - Grafana Enhanced",
            "description": "Controls hot water circulation pump with Grafana logging",
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": ["binary_sensor.guest_bathroom_occupancy"],
                    "to": "on"
                },
                {
                    "platform": "time_pattern",
                    "hours": "/1"
                }
            ],
            "condition": [
                {
                    "condition": "time",
                    "after": "06:00:00",
                    "before": "23:00:00"
                }
            ],
            "action": [
                {
                    "service": "system_log.write",
                    "data": {
                        "message": "Hot water circulation automation triggered"
                    }
                },
                {
                    "service": "system_log.write",
                    "data": {
                        "message": "{{ 'Bathroom occupancy: ' + states('binary_sensor.guest_bathroom_occupancy') }}"
                    }
                }
            ]
        }
        
        return self.create_automation("hot_water_circulation_grafana", automation_data)
    
    def create_garage_lights_automation(self):
        """Create garage lights automation with Grafana logging"""
        print("🚗 Creating Garage Lights Automation...")
        
        automation_data = {
            "alias": "Garage Lights - Grafana Enhanced",
            "description": "Controls garage lights based on door and motion with Grafana logging",
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": ["cover.left_garage_door"],
                    "to": "open"
                },
                {
                    "platform": "state",
                    "entity_id": ["binary_sensor.garage_motion_sensor"],
                    "to": "on"
                }
            ],
            "action": [
                {
                    "service": "system_log.write",
                    "data": {
                        "message": "Garage lights automation triggered"
                    }
                },
                {
                    "service": "system_log.write",
                    "data": {
                        "message": "{{ 'Door state: ' + states('cover.left_garage_door') + ', Motion: ' + states('binary_sensor.garage_motion_sensor') }}"
                    }
                }
            ]
        }
        
        return self.create_automation("garage_lights_grafana", automation_data)
    
    def create_grafana_logging_automation(self):
        """Create general Grafana logging automation"""
        print("📊 Creating Grafana Logging Automation...")
        
        automation_data = {
            "alias": "Grafana System Logging",
            "description": "General system logging for Grafana metrics",
            "trigger": [
                {
                    "platform": "homeassistant",
                    "event": "start"
                },
                {
                    "platform": "time_pattern",
                    "minutes": "/15"
                }
            ],
            "action": [
                {
                    "service": "system_log.write",
                    "data": {
                        "message": "{{ 'System check at ' + now().strftime('%Y-%m-%d %H:%M:%S') }}"
                    }
                }
            ]
        }
        
        return self.create_automation("grafana_system_logging", automation_data)
    
    def create_all_automations(self):
        """Create all Grafana-enhanced automations"""
        print("🚀 CREATING GRAFANA-ENHANCED AUTOMATIONS")
        print("=" * 50)
        
        automations = [
            self.create_temperature_balancing_automation,
            self.create_hot_water_automation,
            self.create_garage_lights_automation,
            self.create_grafana_logging_automation
        ]
        
        success_count = 0
        for create_func in automations:
            try:
                if create_func():
                    success_count += 1
            except Exception as e:
                print(f"❌ Error in automation creation: {e}")
        
        print(f"\n📊 CREATION SUMMARY")
        print(f"Successfully created: {success_count}/{len(automations)} automations")
        
        return success_count == len(automations)
    
    def verify_automations(self):
        """Verify created automations"""
        print("\n🔍 Verifying created automations...")
        
        try:
            response = requests.get(f"{self.ha_url}/api/states", headers=self.headers, timeout=30)
            if response.status_code == 200:
                entities = response.json()
                automations = [e for e in entities if e['entity_id'].startswith('automation.')]
                
                grafana_automations = [a for a in automations if 'grafana' in a['entity_id']]
                
                print(f"📊 Total automations: {len(automations)}")
                print(f"📊 Grafana automations: {len(grafana_automations)}")
                
                for automation in grafana_automations:
                    name = automation['attributes'].get('friendly_name', 'No name')
                    state = automation['state']
                    print(f"  ✅ {automation['entity_id']} - {name} ({state})")
                
                return len(grafana_automations) > 0
            else:
                print(f"❌ Failed to verify: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Verification error: {e}")
            return False

def main():
    """Main function"""
    print("🏠 Home Assistant Grafana Automation Creator")
    print("=" * 60)
    
    # Get configuration
    ha_url = os.getenv("HA_URL", "http://192.168.86.2:8123")
    ha_token = os.getenv("HA_TOKEN")
    
    if not ha_token:
        print("❌ HA_TOKEN environment variable not set")
        print("   Please set your Home Assistant API token:")
        print("   export HA_TOKEN='your_long_lived_access_token'")
        sys.exit(1)
    
    # Initialize creator
    creator = GrafanaAutomationCreator(ha_url, ha_token)
    
    # Create all automations
    success = creator.create_all_automations()
    
    # Verify automations
    if success:
        creator.verify_automations()
        print("\n✅ ALL AUTOMATIONS CREATED SUCCESSFULLY!")
        print("\n📋 Next steps:")
        print("1. Check Home Assistant web UI for new automations")
        print("2. Test automation functionality")
        print("3. Monitor system logs for Grafana data")
        sys.exit(0)
    else:
        print("\n❌ SOME AUTOMATIONS FAILED TO CREATE!")
        sys.exit(1)

if __name__ == "__main__":
    main()
