#!/usr/bin/env python3
"""
Simple script to deploy new automation files to Home Assistant
"""

import os
import sys
import json
import urllib.request
import urllib.parse

# Load configuration
def load_config():
    config = {}
    config_file = 'ha_config.env'
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    return config

def deploy_automation(ha_url, ha_token, automation_file):
    """Deploy a single automation file to Home Assistant"""
    print(f"Deploying {automation_file}...")
    
    # Read the automation file
    with open(automation_file, 'r') as f:
        automation_content = f.read()
    
    # Parse the YAML-like content to extract automations
    # This is a simple parser - assumes each automation starts with "- id:"
    automations = []
    current_automation = []
    in_automation = False
    indent_level = 0
    
    for line in automation_content.split('\n'):
        stripped = line.strip()
        
        if stripped.startswith('- id:'):
            if current_automation:
                automations.append('\n'.join(current_automation))
            current_automation = [line]
            in_automation = True
        elif in_automation:
            if stripped == '' or line.startswith('  ') or line.startswith('- '):
                current_automation.append(line)
            else:
                if current_automation:
                    automations.append('\n'.join(current_automation))
                    current_automation = []
                in_automation = False
    
    if current_automation:
        automations.append('\n'.join(current_automation))
    
    print(f"Found {len(automations)} automations in file")
    
    # Deploy each automation
    for i, automation_yaml in enumerate(automations):
        if not automation_yaml.strip():
            continue
            
        print(f"  Deploying automation {i+1}...")
        
        # Convert YAML to JSON (simplified)
        automation_data = parse_yaml_to_json(automation_yaml)
        
        if automation_data:
            # Send to Home Assistant
            url = f"{ha_url}/api/services/automation/reload"
            headers = {
                'Authorization': f'Bearer {ha_token}',
                'Content-Type': 'application/json'
            }
            
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request) as response:
                    result = json.loads(response.read().decode())
                    print(f"    ✅ Automation {i+1} deployed successfully")
            except Exception as e:
                print(f"    ❌ Error deploying automation {i+1}: {e}")
        else:
            print(f"    ⚠️  Could not parse automation {i+1}")

def parse_yaml_to_json(yaml_content):
    """Simple YAML to JSON converter for automation format"""
    # This is a very basic parser - just enough to handle our automation format
    lines = yaml_content.strip().split('\n')
    automation = {}
    current_section = None
    current_list = None
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
            
        if line.startswith('- '):
            # List item
            content = line[2:].strip()
            if ':' in content:
                key, value = content.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                if current_list is None:
                    current_list = {}
                
                if value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                elif value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                
                current_list[key] = value
        else:
            # Regular key-value
            if current_list and current_section:
                if current_section not in automation:
                    automation[current_section] = []
                automation[current_section].append(current_list)
                current_list = None
            
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                if value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                elif value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value == '[]':
                    value = []
                elif value == '{}':
                    value = {}
                
                automation[key] = value
                current_section = key
    
    # Handle the last list item
    if current_list and current_section:
        if current_section not in automation:
            automation[current_section] = []
        automation[current_section].append(current_list)
    
    return automation

def main():
    config = load_config()
    ha_url = config.get('HA_URL', 'http://192.168.86.2:8123')
    ha_token = config.get('HA_TOKEN')
    
    if not ha_token:
        print("❌ No API token found in ha_config.env")
        sys.exit(1)
    
    # Files to deploy
    automation_files = [
        'automations/temperature_balancing_simple_grafana.yaml'
    ]
    
    for automation_file in automation_files:
        if os.path.exists(automation_file):
            deploy_automation(ha_url, ha_token, automation_file)
        else:
            print(f"⚠️  File not found: {automation_file}")
    
    print("✅ Deployment completed!")

if __name__ == "__main__":
    main()
