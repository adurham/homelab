#!/usr/bin/env python3

"""
Check Active Automations Script
Shows which automations are currently enabled/active
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
    'nightly_reboot_with_timer_pause',
    # Grafana-enhanced versions that are actually deployed
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

def categorize_automations(automations):
    """Categorize automations into active repo, disabled repo, and orphaned"""
    active_repo = []
    disabled_repo = []
    orphaned = []
    
    for automation in automations:
        entity_id = automation.get('entity_id', '')
        if entity_id.startswith('automation.'):
            # Get the actual automation ID from attributes if available, otherwise from entity_id
            attributes = automation.get('attributes', {})
            automation_id = attributes.get('id', entity_id.replace('automation.', ''))
            state = automation.get('state', 'unknown')
            alias = attributes.get('friendly_name', 'No alias')
            
            automation_info = {
                'id': automation_id,
                'entity_id': entity_id,
                'alias': alias,
                'state': state
            }
            
            if automation_id in REPO_AUTOMATION_IDS:
                if state == 'on':
                    active_repo.append(automation_info)
                else:
                    disabled_repo.append(automation_info)
            else:
                orphaned.append(automation_info)
    
    return active_repo, disabled_repo, orphaned

def main():
    """Main function"""
    print("📊 CHECKING ACTIVE AUTOMATIONS")
    print("=" * 50)
    
    # Validate environment
    if not HA_TOKEN:
        print("❌ HA_TOKEN environment variable not set")
        sys.exit(1)
    
    print(f"🔗 Home Assistant URL: {HA_URL}")
    print(f"📁 Repository automation IDs: {len(REPO_AUTOMATION_IDS)}")
    print("")
    
    # Get current automations
    automations = get_current_automations()
    if not automations:
        print("❌ No automations found")
        sys.exit(1)
    
    # Categorize automations
    active_repo, disabled_repo, orphaned = categorize_automations(automations)
    
    print("\n📊 AUTOMATION STATUS SUMMARY:")
    print("")
    
    print(f"✅ ACTIVE REPOSITORY AUTOMATIONS ({len(active_repo)}):")
    if active_repo:
        for automation in active_repo:
            print(f"  • {automation['id']} ({automation['alias']})")
    else:
        print("  (None)")
    
    print(f"\n🔒 DISABLED REPOSITORY AUTOMATIONS ({len(disabled_repo)}):")
    if disabled_repo:
        for automation in disabled_repo:
            print(f"  • {automation['id']} ({automation['alias']}) - {automation['state']}")
    else:
        print("  (None)")
    
    print(f"\n🗑️  ORPHANED AUTOMATIONS ({len(orphaned)}):")
    if orphaned:
        for automation in orphaned:
            print(f"  • {automation['id']} ({automation['alias']}) - {automation['state']}")
    else:
        print("  (None)")
    
    print(f"\n📈 TOTALS:")
    print(f"  • Total automations: {len(automations)}")
    print(f"  • Active repository: {len(active_repo)}")
    print(f"  • Disabled repository: {len(disabled_repo)}")
    print(f"  • Orphaned: {len(orphaned)}")
    
    if len(active_repo) > 0 and len(orphaned) == 0:
        print("\n🎉 SUCCESS! Only repository-defined automations are active!")
    elif len(orphaned) > 0:
        print(f"\n⚠️  WARNING: {len(orphaned)} orphaned automations still exist")
    else:
        print("\n💡 All automations are disabled or repository-defined")

if __name__ == "__main__":
    main()
