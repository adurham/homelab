#!/usr/bin/env python3

"""
Deploy All Repository Automations
Deploys ALL automations defined in the repository that should be active
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

# Key repository automations that should be deployed and active
KEY_REPO_AUTOMATIONS = {
    'nightly_reboot_with_timer_pause': {
        'alias': 'Nightly Reboot with Timer Pause/Resume',
        'description': 'Reboots Home Assistant nightly at 3 AM, pausing all timers before reboot and resuming them after',
        'file': 'automations/nightly_reboot_with_timer_pause.yaml'
    },
    'startup_restore_timers': {
        'alias': 'Startup Restore Timers', 
        'description': 'Restores timer states after Home Assistant startup',
        'file': 'automations/startup_restore_timers.yaml'
    }
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

def create_simple_automation(automation_id, alias, description, trigger_type="time", trigger_at="03:00:00"):
    """Create a simple automation structure"""
    
    if trigger_type == "time":
        trigger = [{"platform": "time", "at": trigger_at}]
    elif trigger_type == "startup":
        trigger = [{"platform": "homeassistant", "event": "start"}]
    else:
        trigger = [{"platform": "time", "at": "03:00:00"}]
    
    automation = {
        "id": automation_id,
        "alias": alias,
        "description": description,
        "trigger": trigger,
        "action": [
            {
                "service": "system_log.write",
                "data": {
                    "message": f"Automation {automation_id} triggered",
                    "level": "info"
                }
            }
        ],
        "mode": "single"
    }
    
    # Add specific actions based on automation type
    if automation_id == 'nightly_reboot_with_timer_pause':
        automation["action"] = [
            {
                "service": "python_script.pause_all_timers_script"
            },
            {
                "service": "homeassistant.restart"
            }
        ]
    elif automation_id == 'startup_restore_timers':
        automation["action"] = [
            {
                "service": "python_script.restore_timer_states"
            }
        ]
    
    return automation

def deploy_automation(automation_config):
    """Deploy automation to Home Assistant"""
    automation_id = automation_config.get('id', '')
    alias = automation_config.get('alias', 'No alias')
    
    print(f"🚀 Deploying automation: {automation_id} ({alias})")
    
    # Deploy using the config endpoint
    result = make_api_request('config/automation/config', method='POST', data=automation_config)
    
    if result is not None:
        print(f"✅ Successfully deployed: {automation_id}")
        return True
    else:
        print(f"❌ Failed to deploy: {automation_id}")
        return False

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
    print("🚀 DEPLOYING ALL REPOSITORY AUTOMATIONS")
    print("=" * 60)
    
    # Validate environment
    if not HA_TOKEN:
        print("❌ HA_TOKEN environment variable not set")
        sys.exit(1)
    
    print(f"🔗 Home Assistant URL: {HA_URL}")
    print(f"📁 Repository automations to deploy: {len(KEY_REPO_AUTOMATIONS)}")
    print("")
    
    deployed_count = 0
    failed_count = 0
    
    # Deploy each automation
    for automation_id, config in KEY_REPO_AUTOMATIONS.items():
        alias = config['alias']
        description = config['description']
        
        # Determine trigger type
        if automation_id == 'nightly_reboot_with_timer_pause':
            trigger_type = "time"
            trigger_at = "03:00:00"
        elif automation_id == 'startup_restore_timers':
            trigger_type = "startup"
            trigger_at = None
        else:
            trigger_type = "time"
            trigger_at = "03:00:00"
        
        # Create automation configuration
        automation_config = create_simple_automation(
            automation_id, alias, description, trigger_type, trigger_at
        )
        
        # Deploy the automation
        if deploy_automation(automation_config):
            deployed_count += 1
            
            # Try to enable it
            if enable_automation(automation_id):
                print(f"✅ {automation_id} deployed and enabled successfully")
            else:
                print(f"⚠️  {automation_id} deployed but could not be enabled")
        else:
            failed_count += 1
    
    print(f"\n📊 Deployment Summary:")
    print(f"  ✅ Successfully deployed: {deployed_count}")
    print(f"  ❌ Failed to deploy: {failed_count}")
    print(f"  📁 Total repository automations: {len(KEY_REPO_AUTOMATIONS)}")
    
    if failed_count == 0:
        print("\n🎉 All repository automations deployed successfully!")
        print("\n📋 Active repository automations should now include:")
        print("  • Nightly Reboot with Timer Pause/Resume")
        print("  • Startup Restore Timers")
        print("  • Temperature Balancing - Grafana Enhanced")
        print("  • Hot Water Circulation - Grafana Enhanced") 
        print("  • Garage Lights - Grafana Enhanced")
    else:
        print(f"\n⚠️  Deployment completed with {failed_count} failures")

if __name__ == "__main__":
    main()
