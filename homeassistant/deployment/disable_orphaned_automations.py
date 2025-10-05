#!/usr/bin/env python3

"""
Disable Orphaned Automations Script
Disables automations from Home Assistant that are not defined in the repository
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

# Automation IDs that should be kept (from repository)
REPO_AUTOMATION_IDS = {
    'temperature_balancing_simple_grafana',
    'hot_water_simple_grafana', 
    'garage_lights_simple_grafana',
    'garage_lights_with_grafana',
    'garage_lights_efficiency_monitor',
    'hot_water_circulation_with_grafana',
    'smart_hot_water_circulation_with_metrics',
    'hot_water_efficiency_monitor',
    'temperature_balancing_with_grafana',
    'balance_all_rooms_with_metrics',
    'balance_room_with_metrics',
    'update_temperature_metrics',
    'daily_metrics_reset',
    'temperature_balancing_corrected',
    'balance_all_rooms',
    'balance_room',
    'manual_temperature_balance',
    'occupancy_notifications',
    'hot_water_circulation_optimized',
    'smart_hot_water_circulation',
    'manual_hot_water_test',
    'weekend_hot_water_optimization',
    'garage_lights_final',
    'startup_restore_timers',
    'nightly_reboot_with_timer_pause'
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
    
    # Try different endpoints
    endpoints = [
        'config/automation/config',
        'automation',
        'states'
    ]
    
    for endpoint in endpoints:
        print(f"  Trying endpoint: {endpoint}")
        result = make_api_request(endpoint)
        if result is not None:
            if endpoint == 'states':
                # Filter for automation entities
                automations = [state for state in result if state.get('entity_id', '').startswith('automation.')]
                print(f"✅ Found {len(automations)} automation states")
                return automations
            else:
                print(f"✅ Found {len(result)} automations via {endpoint}")
                return result
    
    print("❌ Failed to fetch automations from any endpoint")
    return []

def identify_orphaned_automations(current_automations):
    """Identify automations that are not in the repository"""
    orphaned = []
    
    for automation in current_automations:
        # Handle different response formats
        if 'entity_id' in automation:
            # This is a state response - extract ID from entity_id
            entity_id = automation.get('entity_id', '')
            if entity_id.startswith('automation.'):
                automation_id = entity_id.replace('automation.', '')
            else:
                continue
        else:
            # This is a config response - use id field
            automation_id = automation.get('id', '')
        
        if automation_id not in REPO_AUTOMATION_IDS:
            orphaned.append({
                'id': automation_id,
                'entity_id': f'automation.{automation_id}',
                'attributes': automation.get('attributes', {}),
                'state': automation.get('state', 'unknown')
            })
    
    return orphaned

def disable_automation(automation_id):
    """Disable an automation by ID"""
    print(f"🔒 Disabling automation: {automation_id}")
    
    # Use the services endpoint to call automation.turn_off
    data = {
        "entity_id": f"automation.{automation_id}"
    }
    
    result = make_api_request('services/automation/turn_off', method='POST', data=data)
    
    if result is not None:
        print(f"✅ Successfully disabled: {automation_id}")
        return True
    else:
        print(f"❌ Failed to disable: {automation_id}")
        return False

def main():
    """Main cleanup function"""
    print("🔒 DISABLE ORPHANED AUTOMATIONS")
    print("=" * 50)
    
    # Validate environment
    if not HA_TOKEN:
        print("❌ HA_TOKEN environment variable not set")
        print("Please set HA_TOKEN in ha_config.env or environment")
        sys.exit(1)
    
    print(f"🔗 Home Assistant URL: {HA_URL}")
    print(f"📁 Repository automation IDs: {len(REPO_AUTOMATION_IDS)}")
    print("")
    
    # Get current automations
    current_automations = get_current_automations()
    if not current_automations:
        print("❌ No automations found or failed to fetch")
        sys.exit(1)
    
    # Identify orphaned automations
    print("\n🔍 Identifying orphaned automations...")
    orphaned = identify_orphaned_automations(current_automations)
    
    if not orphaned:
        print("✅ No orphaned automations found! All automations are defined in repository.")
        return
    
    print(f"⚠️  Found {len(orphaned)} orphaned automations:")
    print("")
    
    for automation in orphaned:
        automation_id = automation.get('id', 'Unknown')
        alias = automation.get('attributes', {}).get('friendly_name', 'No alias')
        state = automation.get('state', 'unknown')
        print(f"  • {automation_id} ({alias}) - {state}")
    
    print("")
    print("🔒 Auto-disabling orphaned automations...")
    
    disabled_count = 0
    failed_count = 0
    
    for automation in orphaned:
        automation_id = automation.get('id', '')
        if disable_automation(automation_id):
            disabled_count += 1
        else:
            failed_count += 1
    
    print("\n📊 Disable Summary:")
    print(f"  ✅ Successfully disabled: {disabled_count}")
    print(f"  ❌ Failed to disable: {failed_count}")
    print(f"  📁 Total orphaned automations: {len(orphaned)}")
    
    if failed_count == 0:
        print("\n🎉 All orphaned automations disabled successfully!")
        print("💡 Note: These automations are still in automations.yaml but are now disabled.")
        print("💡 You can manually remove them from automations.yaml if desired.")
    else:
        print(f"\n⚠️  Disable completed with {failed_count} failures")

if __name__ == "__main__":
    main()
