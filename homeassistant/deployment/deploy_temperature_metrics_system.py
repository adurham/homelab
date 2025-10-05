#!/usr/bin/env python3
"""
Deploy Temperature Metrics System
Sets up comprehensive temperature drift, variance, and efficiency metrics for Grafana
"""

import os
import sys
import json
import requests
import time
from datetime import datetime

# Configuration
HA_URL = os.getenv('HA_URL', 'http://homeassistant.local:8123')
HA_TOKEN = os.getenv('HA_TOKEN')

if not HA_TOKEN:
    print("❌ HA_TOKEN environment variable not set")
    print("Please set it with: export HA_TOKEN='your_token_here'")
    sys.exit(1)

def deploy_automation(automation_file):
    """Deploy automation via Home Assistant API"""
    print(f"🚀 Deploying {automation_file}...")
    
    # Read automation file
    with open(automation_file, 'r') as f:
        automation_content = f.read()
    
    # Parse YAML (simple parsing for automation ID)
    automation_id = None
    for line in automation_content.split('\n'):
        if line.strip().startswith('alias:'):
            automation_id = line.split(':', 1)[1].strip().lower().replace(' ', '_').replace('-', '_')
            break
    
    if not automation_id:
        print(f"❌ Could not extract automation ID from {automation_file}")
        return False
    
    # Convert YAML to JSON (simplified conversion)
    # This is a basic conversion - for production, use proper YAML parser
    automation_json = convert_yaml_to_json(automation_content)
    
    # Deploy via API
    url = f"{HA_URL}/api/config/automation/config/{automation_id}"
    headers = {
        'Authorization': f'Bearer {HA_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.post(url, json=automation_json, headers=headers)
        if response.status_code == 200:
            print(f"✅ {automation_file} deployed successfully")
            return True
        else:
            print(f"❌ Failed to deploy {automation_file}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error deploying {automation_file}: {e}")
        return False

def convert_yaml_to_json(yaml_content):
    """Convert YAML automation to JSON format (simplified)"""
    # This is a basic conversion - for production use proper YAML parser
    lines = yaml_content.strip().split('\n')
    
    automation = {
        "alias": "",
        "description": "",
        "triggers": [],
        "conditions": [],
        "actions": [],
        "mode": "restart"
    }
    
    current_section = None
    current_trigger = None
    current_action = None
    indent_level = 0
    
    for line in lines:
        line = line.rstrip()
        if not line or line.startswith('#'):
            continue
            
        # Determine indent level
        line_indent = len(line) - len(line.lstrip())
        
        # Remove leading dashes and spaces
        clean_line = line.lstrip('- ')
        
        if ':' in clean_line and not clean_line.endswith(':'):
            key, value = clean_line.split(':', 1)
            key = key.strip()
            value = value.strip().strip('"\'')
            
            if key == 'alias':
                automation['alias'] = value
            elif key == 'description':
                automation['description'] = value
            elif key == 'mode':
                automation['mode'] = value
            elif key == 'platform':
                if current_section == 'triggers':
                    current_trigger = {'platform': value}
                    automation['triggers'].append(current_trigger)
                elif current_section == 'actions':
                    current_action = {'action': value}
                    automation['actions'].append(current_action)
            elif key == 'action':
                current_action = {'action': value}
                automation['actions'].append(current_action)
            elif key == 'service':
                if current_action:
                    current_action['action'] = value
            elif key == 'data':
                if current_action:
                    current_action['data'] = {}
            elif key == 'entity_id':
                if current_action:
                    if 'target' not in current_action:
                        current_action['target'] = {}
                    if isinstance(value, str) and ',' in value:
                        # Handle multiple entities
                        current_action['target']['entity_id'] = [e.strip() for e in value.split(',')]
                    else:
                        current_action['target']['entity_id'] = value
            elif key == 'id':
                if current_trigger:
                    current_trigger['id'] = value
            elif key == 'minutes':
                if current_trigger:
                    current_trigger['minutes'] = value.strip('"')
            elif key == 'level':
                if current_action and 'data' in current_action:
                    current_action['data']['level'] = value
            elif key == 'message':
                if current_action and 'data' in current_action:
                    current_action['data']['message'] = value
        elif clean_line.endswith(':'):
            section_name = clean_line[:-1].strip()
            if section_name == 'trigger':
                current_section = 'triggers'
            elif section_name == 'condition':
                current_section = 'conditions'
            elif section_name == 'action':
                current_section = 'actions'
            elif section_name == 'target':
                if current_action:
                    current_action['target'] = {}
            elif section_name == 'data':
                if current_action:
                    current_action['data'] = {}
    
    return automation

def enable_automation(automation_id):
    """Enable automation via API"""
    print(f"✅ Enabling {automation_id}...")
    
    url = f"{HA_URL}/api/services/automation/turn_on"
    headers = {
        'Authorization': f'Bearer {HA_TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {'entity_id': f'automation.{automation_id}'}
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            print(f"✅ {automation_id} enabled")
            return True
        else:
            print(f"❌ Failed to enable {automation_id}: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error enabling {automation_id}: {e}")
        return False

def test_automation(automation_id):
    """Test automation by triggering it"""
    print(f"🧪 Testing {automation_id}...")
    
    url = f"{HA_URL}/api/services/automation/trigger"
    headers = {
        'Authorization': f'Bearer {HA_TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {'entity_id': f'automation.{automation_id}'}
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            print(f"✅ {automation_id} triggered successfully")
            return True
        else:
            print(f"❌ Failed to trigger {automation_id}: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error triggering {automation_id}: {e}")
        return False

def check_automation_status(automation_id):
    """Check if automation is active"""
    print(f"🔍 Checking status of {automation_id}...")
    
    url = f"{HA_URL}/api/states/automation.{automation_id}"
    headers = {'Authorization': f'Bearer {HA_TOKEN}'}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            state = data.get('state', 'unknown')
            friendly_name = data.get('attributes', {}).get('friendly_name', 'No name')
            print(f"📊 {automation_id}: {state} ({friendly_name})")
            return state == 'on'
        else:
            print(f"❌ Failed to check {automation_id}: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error checking {automation_id}: {e}")
        return False

def main():
    """Main deployment function"""
    print("🚀 DEPLOYING TEMPERATURE METRICS SYSTEM")
    print("=" * 50)
    
    # Change to script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    os.chdir(project_dir)
    
    # Deploy temperature metrics calculator automation
    automation_file = "automations/temperature_metrics_calculator.yaml"
    if os.path.exists(automation_file):
        success = deploy_automation(automation_file)
        if success:
            automation_id = "temperature_metrics_calculator"
            enable_automation(automation_id)
            time.sleep(2)
            test_automation(automation_id)
            time.sleep(3)
            check_automation_status(automation_id)
    else:
        print(f"❌ Automation file not found: {automation_file}")
    
    print("\n📊 TEMPERATURE METRICS SYSTEM DEPLOYED!")
    print("=" * 50)
    print("✅ Temperature drift metrics - Every 5 minutes")
    print("✅ Room temperature variance calculations")
    print("✅ Occupancy efficiency scores")
    print("✅ Structured logging for Grafana")
    print()
    print("📋 NEXT STEPS:")
    print("1. Check Home Assistant logs for structured metrics")
    print("2. Import Grafana dashboard: grafana_dashboard_temperature_balancing.json")
    print("3. Configure InfluxDB data source in Grafana")
    print("4. Use temperature_metrics_parser.py to process logs")
    print()
    print("🔍 MONITORING:")
    print("- Check logs every 5 minutes for TEMPERATURE_METRICS entries")
    print("- Look for TEMPERATURE_VARIANCE_METRICS entries")
    print("- Monitor EFFICIENCY_METRICS for system performance")
    print()
    print("📈 GRAFANA DASHBOARDS:")
    print("- Temperature drift over time")
    print("- Room variance analysis")
    print("- Occupancy efficiency patterns")
    print("- Vent control effectiveness")

if __name__ == "__main__":
    main()
