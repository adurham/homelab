#!/usr/bin/env python3
"""
Parse Home Assistant automations.yaml and create individual files for each automation
"""

import yaml
import os
import re
from pathlib import Path

def sanitize_filename(name):
    """Convert automation alias to a safe filename"""
    # Remove special characters and replace spaces with underscores
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[-\s]+', '_', name)
    return name.lower()

def categorize_automation(alias):
    """Categorize automation based on its alias"""
    alias_lower = alias.lower()
    
    if any(word in alias_lower for word in ['light', 'lamp', 'bulb', 'sconce']):
        return 'lighting'
    elif any(word in alias_lower for word in ['pool', 'pump']):
        return 'pool'
    elif any(word in alias_lower for word in ['vacuum', 'clean']):
        return 'cleaning'
    elif any(word in alias_lower for word in ['garage', 'door']):
        return 'garage'
    elif any(word in alias_lower for word in ['water', 'heater', 'hot', 'recirculation']):
        return 'plumbing'
    elif any(word in alias_lower for word in ['system', 'auto', 'season']):
        return 'system'
    elif any(word in alias_lower for word in ['hue', 'sync', 'box']):
        return 'entertainment'
    elif any(word in alias_lower for word in ['floodlight', 'motion', 'outdoor']):
        return 'security'
    else:
        return 'general'

def create_automation_file(automation, output_dir):
    """Create individual YAML file for an automation"""
    
    # Get automation details
    alias = automation.get('alias', f"automation_{automation.get('id', 'unknown')}")
    automation_id = automation.get('id', 'unknown')
    
    # Create safe filename
    filename = f"{sanitize_filename(alias)}.yaml"
    
    # Determine category
    category = categorize_automation(alias)
    
    # Create category directory
    category_dir = output_dir / category
    category_dir.mkdir(exist_ok=True)
    
    # Full file path
    file_path = category_dir / filename
    
    # Create YAML content
    yaml_content = {
        'id': automation_id,
        'alias': alias,
        'description': automation.get('description', ''),
        'trigger': automation.get('triggers', []),
        'condition': automation.get('conditions', []),
        'action': automation.get('actions', []),
        'mode': automation.get('mode', 'single')
    }
    
    # Remove empty fields
    yaml_content = {k: v for k, v in yaml_content.items() if v}
    
    # Write file
    with open(file_path, 'w') as f:
        f.write(f"# {alias}\n")
        f.write(f"# ID: {automation_id}\n")
        f.write(f"# Category: {category}\n")
        f.write(f"# Description: {automation.get('description', 'No description')}\n\n")
        
        # Convert to YAML format
        yaml.dump([yaml_content], f, default_flow_style=False, sort_keys=False, indent=2)
    
    return file_path, category

def main():
    # Paths
    input_file = Path('automations.yaml')
    output_dir = Path('individual_automations')
    
    if not input_file.exists():
        print(f"❌ Input file {input_file} not found")
        return
    
    # Create output directory
    output_dir.mkdir(exist_ok=True)
    
    # Parse automations.yaml
    print(f"📖 Reading {input_file}...")
    with open(input_file, 'r') as f:
        automations = yaml.safe_load(f)
    
    if not isinstance(automations, list):
        print("❌ Invalid automations.yaml format")
        return
    
    print(f"🔍 Found {len(automations)} automations")
    
    # Process each automation
    categories = {}
    for automation in automations:
        alias = automation.get('alias', f"automation_{automation.get('id', 'unknown')}")
        print(f"📝 Processing: {alias}")
        
        file_path, category = create_automation_file(automation, output_dir)
        
        if category not in categories:
            categories[category] = []
        categories[category].append(alias)
        
        print(f"   ✅ Created: {file_path}")
    
    # Create summary
    print(f"\n📊 Summary:")
    for category, automations in categories.items():
        print(f"   {category}: {len(automations)} automations")
        for automation in automations:
            print(f"     - {automation}")
    
    # Create index file
    create_index_file(categories, output_dir)
    
    print(f"\n🎉 Successfully created {len(automations)} automation files in {output_dir}")

def create_index_file(categories, output_dir):
    """Create an index file listing all automations by category"""
    index_path = output_dir / 'README.md'
    
    with open(index_path, 'w') as f:
        f.write("# Home Assistant Automations\n\n")
        f.write("This directory contains individual automation files organized by category.\n\n")
        
        for category, automations in categories.items():
            f.write(f"## {category.title()}\n\n")
            for automation in automations:
                f.write(f"- {automation}\n")
            f.write("\n")

if __name__ == '__main__':
    main()
