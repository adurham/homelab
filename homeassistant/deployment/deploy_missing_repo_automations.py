#!/usr/bin/env python3

"""
Deploy Missing Repository Automations
Deploys the repository-defined automations that should be active but aren't yet deployed
"""

import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
import yaml

# Configuration
HA_URL = os.getenv('HA_URL', 'http://homeassistant.local:8123')
HA_TOKEN = os.getenv('HA_TOKEN')

# Repository automation IDs that should be deployed and active
REPO_AUTOMATIONS_TO_DEPLOY = {
    'nightly_reboot_with_timer_pause',
    'startup_restore_timers'
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

def load_automation_file(file_path):
    """Load automation from YAML file"""
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Failed to load {file_path}: {e}")
        return None

def deploy_automation(automation_data):
    """Deploy automation to Home Assistant"""
    automation_id = automation_data.get('id', '')
    alias = automation_data.get('alias', 'No alias')
    
    print(f"🚀 Deploying automation: {automation_id} ({alias})")
    
    # Use the config/automation/config endpoint to create the automation
    result = make_api_request('config/automation/config', method='POST', data=automation_data)
    
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
    print("🚀 DEPLOYING MISSING REPOSITORY AUTOMATIONS")
    print("=" * 60)
    
    # Validate environment
    if not HA_TOKEN:
        print("❌ HA_TOKEN environment variable not set")
        sys.exit(1)
    
    print(f"🔗 Home Assistant URL: {HA_URL}")
    print(f"📁 Repository automations to deploy: {len(REPO_AUTOMATIONS_TO_DEPLOY)}")
    print("")
    
    # Find automation files
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    automations_dir = os.path.join(repo_dir, 'automations')
    
    if not os.path.exists(automations_dir):
        print(f"❌ Automations directory not found: {automations_dir}")
        sys.exit(1)
    
    deployed_count = 0
    failed_count = 0
    
    for automation_id in REPO_AUTOMATIONS_TO_DEPLOY:
        print(f"\n🔍 Looking for automation: {automation_id}")
        
        # Find the automation file
        automation_file = None
        for file_name in os.listdir(automations_dir):
            if file_name.endswith('.yaml'):
                file_path = os.path.join(automations_dir, file_name)
                automation_data = load_automation_file(file_path)
                
                if automation_data and isinstance(automation_data, list):
                    # Handle list of automations
                    for automation in automation_data:
                        if automation.get('id') == automation_id:
                            automation_file = automation
                            break
                elif automation_data and automation_data.get('id') == automation_id:
                    automation_file = automation_data
                    break
        
        if not automation_file:
            print(f"❌ Automation {automation_id} not found in repository files")
            failed_count += 1
            continue
        
        # Deploy the automation
        if deploy_automation(automation_file):
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
    print(f"  📁 Total repository automations: {len(REPO_AUTOMATIONS_TO_DEPLOY)}")
    
    if failed_count == 0:
        print("\n🎉 All repository automations deployed successfully!")
    else:
        print(f"\n⚠️  Deployment completed with {failed_count} failures")

if __name__ == "__main__":
    main()
