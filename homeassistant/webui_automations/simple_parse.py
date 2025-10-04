#!/usr/bin/env python3
"""
Simple parser to extract individual automations from automations.yaml
No external dependencies required
"""

import re
import os
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

def extract_automations(content):
    """Extract individual automations from YAML content"""
    automations = []
    
    # Split by automation blocks (starting with - id:)
    blocks = re.split(r'\n(?=- id:)', content)
    
    for block in blocks:
        if not block.strip():
            continue
            
        # Extract automation details
        id_match = re.search(r'- id: [\'"]?([^\'"\s]+)[\'"]?', block)
        alias_match = re.search(r'alias: (.+)', block)
        desc_match = re.search(r'description: (.+)', block)
        
        if id_match and alias_match:
            automation = {
                'id': id_match.group(1),
                'alias': alias_match.group(1).strip(),
                'description': desc_match.group(1).strip() if desc_match else '',
                'content': block.strip()
            }
            automations.append(automation)
    
    return automations

def create_automation_file(automation, output_dir):
    """Create individual YAML file for an automation"""
    
    alias = automation['alias']
    automation_id = automation['id']
    
    # Create safe filename
    filename = f"{sanitize_filename(alias)}.yaml"
    
    # Determine category
    category = categorize_automation(alias)
    
    # Create category directory
    category_dir = output_dir / category
    category_dir.mkdir(exist_ok=True)
    
    # Full file path
    file_path = category_dir / filename
    
    # Create file content
    with open(file_path, 'w') as f:
        f.write(f"# {alias}\n")
        f.write(f"# ID: {automation_id}\n")
        f.write(f"# Category: {category}\n")
        if automation['description']:
            f.write(f"# Description: {automation['description']}\n")
        f.write("\n")
        f.write(automation['content'])
    
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
    
    # Read automations.yaml
    print(f"📖 Reading {input_file}...")
    with open(input_file, 'r') as f:
        content = f.read()
    
    # Extract automations
    automations = extract_automations(content)
    print(f"🔍 Found {len(automations)} automations")
    
    # Process each automation
    categories = {}
    for automation in automations:
        alias = automation['alias']
        print(f"📝 Processing: {alias}")
        
        file_path, category = create_automation_file(automation, output_dir)
        
        if category not in categories:
            categories[category] = []
        categories[category].append(alias)
        
        print(f"   ✅ Created: {file_path}")
    
    # Create summary
    print(f"\n📊 Summary:")
    for category, automation_list in categories.items():
        print(f"   {category}: {len(automation_list)} automations")
        for automation in automation_list:
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
        f.write("## Categories\n\n")
        
        for category, automations in categories.items():
            f.write(f"### {category.title()}\n\n")
            for automation in automations:
                f.write(f"- {automation}\n")
            f.write("\n")
        
        f.write("## Usage\n\n")
        f.write("Each automation is stored in its own YAML file within the appropriate category directory.\n")
        f.write("You can edit individual automations without affecting others.\n\n")
        f.write("To deploy all automations back to Home Assistant, use the deployment script.\n")

if __name__ == '__main__':
    main()
