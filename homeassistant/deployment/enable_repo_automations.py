#!/usr/bin/env python3

"""
Enable Repository Automations Script
Enables the repository-defined automations that should be active
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

# Repository automation IDs that should be enabled
REPO_AUTOMATION_IDS = {
    'temperature_balancing_grafana',
    'hot_water_circulation_grafana',
    'garage_lights_grafana'
}

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

def get_current_automations():
    """Get all current automations from Home Assistant"""
    print("📋 Fetching current automations from Home Assistant...")
    
    result = make_api_request('states')
    if result is not None:
        # Filter for automation entities
        automations = [state for state in result if state.get('entity_id', '').startswith('automation.')]
        print(f"✅ Found {len(automations)} automation states")
        return automations
    
    print("❌ Failed to fetch automations")
    return []

def find_repo_automations(automations):
    """Find repository-defined automations"""
    repo_automations = []
    
    for automation in automations:
        entity_id = automation.get('entity_id', '')
        if entity_id.startswith('automation.'):
            attributes = automation.get('attributes', {})
            automation_id = attributes.get('id', entity_id.replace('automation.', ''))
            
            if automation_id in REPO_AUTOMATION_IDS:
                repo_automations.append({
                    'id': automation_id,
                    'entity_id': entity_id,
                    'alias': attributes.get('friendly_name', 'No alias'),
                    'state': automation.get('state', 'unknown')
                })
    
    return repo_automations

def enable_automation(automation_id):
    """Enable an automation by ID"""
    print(f"✅ Enabling automation: {automation_id}")
    
    # Use the services endpoint to call automation.turn_on
    data = {
        "entity_id": f"automation.{automation_id}"
    }
    
    result = make_api_request('services/automation/turn_on', method='POST', data=data)
    
    if result is not None:
        print(f"✅ Successfully enabled: {automation_id}")
        return True
    else:
        print(f"❌ Failed to enable: {automation_id}")
        return False

def main():
    """Main function"""
    print("✅ ENABLING REPOSITORY AUTOMATIONS")
    print("=" * 50)
    
    # Validate environment
    if not HA_TOKEN:
        print("❌ HA_TOKEN environment variable not set")
        sys.exit(1)
    
    print(f"🔗 Home Assistant URL: {HA_URL}")
    print(f"📁 Repository automation IDs to enable: {len(REPO_AUTOMATION_IDS)}")
    print("")
    
    # Get current automations
    automations = get_current_automations()
    if not automations:
        print("❌ No automations found")
        sys.exit(1)
    
    # Find repository automations
    repo_automations = find_repo_automations(automations)
    
    if not repo_automations:
        print("❌ No repository automations found")
        sys.exit(1)
    
    print(f"📋 Found {len(repo_automations)} repository automations:")
    print("")
    
    for automation in repo_automations:
        print(f"  • {automation['id']} ({automation['alias']}) - {automation['state']}")
    
    print("")
    print("✅ Auto-enabling repository automations...")
    
    enabled_count = 0
    failed_count = 0
    
    for automation in repo_automations:
        automation_id = automation['id']
        if enable_automation(automation_id):
            enabled_count += 1
        else:
            failed_count += 1
    
    print("\n📊 Enable Summary:")
    print(f"  ✅ Successfully enabled: {enabled_count}")
    print(f"  ❌ Failed to enable: {failed_count}")
    print(f"  📁 Total repository automations: {len(repo_automations)}")
    
    if failed_count == 0:
        print("\n🎉 All repository automations enabled successfully!")
        print("💡 Your Home Assistant now only has repository-defined automations active.")
    else:
        print(f"\n⚠️  Enable completed with {failed_count} failures")

if __name__ == "__main__":
    main()
