#!/usr/bin/env python3
"""
Extract Home Assistant entities via SSH
Alternative method that doesn't require API token
"""

import subprocess
import json
import re
from datetime import datetime
from collections import defaultdict

def run_ssh_command(command, ha_host="192.168.86.2", ssh_user="root"):
    """Run SSH command and return output"""
    try:
        result = subprocess.run([
            'ssh', f'{ssh_user}@{ha_host}', command
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"❌ SSH command failed: {result.stderr}")
            return None
    except Exception as e:
        print(f"❌ SSH error: {e}")
        return None

def extract_entities_via_ssh():
    """Extract entities using Home Assistant CLI"""
    print("🔍 Extracting entities via SSH...")
    
    # Get entities using ha core info and other commands
    print("📊 Getting system information...")
    
    # Get Home Assistant version and info
    ha_info = run_ssh_command("ha core info")
    if ha_info:
        print(f"Home Assistant Info:\n{ha_info}")
    
    # Get entity states using ha states list
    print("📋 Getting entity states...")
    entities_output = run_ssh_command("ha states list")
    
    if not entities_output:
        print("❌ Failed to get entity states")
        return False
    
    # Parse entities from the output
    entities = []
    lines = entities_output.split('\n')
    
    for line in lines:
        if '=' in line and '.' in line:
            # Parse entity_id = state format
            parts = line.split('=', 1)
            if len(parts) == 2:
                entity_id = parts[0].strip()
                state = parts[1].strip()
                
                # Skip system entities we don't need
                if any(skip in entity_id for skip in ['sun.', 'moon.', 'zone.', 'group.']):
                    continue
                
                entities.append({
                    'entity_id': entity_id,
                    'state': state,
                    'domain': entity_id.split('.')[0] if '.' in entity_id else 'unknown'
                })
    
    print(f"✅ Found {len(entities)} entities")
    
    # Categorize entities
    categories = defaultdict(list)
    
    for entity in entities:
        entity_id = entity['entity_id']
        domain = entity['domain']
        
        # Create category based on domain
        if domain in ['light', 'switch', 'binary_sensor']:
            category = 'lighting'
        elif domain in ['sensor', 'weather']:
            category = 'sensors'
        elif domain in ['camera', 'alarm_control_panel']:
            category = 'security'
        elif domain in ['climate', 'fan', 'humidifier']:
            category = 'climate'
        elif domain in ['media_player', 'remote']:
            category = 'entertainment'
        elif domain in ['vacuum', 'lock']:
            category = 'home_automation'
        elif domain in ['timer', 'input_boolean', 'input_text', 'input_number']:
            category = 'utilities'
        elif domain in ['automation', 'script', 'scene']:
            category = 'automation'
        elif domain in ['person', 'device_tracker']:
            category = 'presence'
        else:
            category = 'other'
        
        categories[category].append(entity)
    
    # Create documentation
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    doc_content = f"""# Home Assistant Entity Inventory

Generated on: {timestamp}

## Summary

- **Total Entities**: {len(entities)}

## Entity Categories

"""
    
    for category, items in sorted(categories.items()):
        doc_content += f"### {category.title()} ({len(items)} entities)\n\n"
        
        for item in sorted(items, key=lambda x: x['entity_id']):
            doc_content += f"- **{item['entity_id']}**\n"
            doc_content += f"  - State: {item['state']}\n"
            doc_content += f"  - Domain: {item['domain']}\n\n"
    
    # Add domain summary
    domain_counts = defaultdict(int)
    for entity in entities:
        domain_counts[entity['domain']] += 1
    
    doc_content += "## Domain Summary\n\n"
    for domain, count in sorted(domain_counts.items()):
        doc_content += f"- **{domain}**: {count} entities\n"
    
    # Save documentation
    with open('entity_inventory.md', 'w') as f:
        f.write(doc_content)
    
    # Save JSON data
    data = {
        'timestamp': timestamp,
        'total_entities': len(entities),
        'categories': {cat: len(items) for cat, items in categories.items()},
        'domains': dict(domain_counts),
        'entities': entities
    }
    
    with open('entity_inventory.json', 'w') as f:
        json.dump(data, f, indent=2)
    
    print("✅ Entity inventory created successfully!")
    print("📄 Documentation: entity_inventory.md")
    print("📊 Raw data: entity_inventory.json")
    
    return True

def main():
    success = extract_entities_via_ssh()
    
    if not success:
        print("❌ Entity extraction failed")
        exit(1)

if __name__ == '__main__':
    main()
