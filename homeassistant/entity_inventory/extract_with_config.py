#!/usr/bin/env python3
"""
Extract Home Assistant entities using configuration file
"""

import urllib.request
import urllib.error
import json
import os
from datetime import datetime
from collections import defaultdict

def load_config():
    """Load configuration from ha_config.env file"""
    config = {}
    config_file = '../ha_config.env'  # Look in parent directory
    
    if not os.path.exists(config_file):
        print(f"❌ Configuration file {config_file} not found")
        print("Please create the file and add your API token")
        return None
    
    with open(config_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip()
    
    if 'HA_TOKEN' not in config or config['HA_TOKEN'] == 'YOUR_API_TOKEN_HERE':
        print("❌ Please update ha_config.env with your actual API token")
        print("Get your token from: http://192.168.86.2:8123/profile")
        return None
    
    return config

def extract_entities_with_config():
    """Extract entities using configuration file"""
    config = load_config()
    if not config:
        return False
    
    ha_url = config.get('HA_URL', 'http://192.168.86.2:8123')
    token = config['HA_TOKEN']
    
    print("🔍 Extracting entities from Home Assistant...")
    print(f"📡 Connecting to: {ha_url}")
    
    try:
        request = urllib.request.Request(f"{ha_url}/api/states")
        request.add_header('Content-Type', 'application/json')
        request.add_header('Authorization', f'Bearer {token}')
        
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status == 200:
                entities = json.loads(response.read().decode())
                print(f"✅ Found {len(entities)} entities")
            else:
                print(f"❌ Failed to get entities: HTTP {response.status}")
                return False
                
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error: {e.code} - {e.reason}")
        if e.code == 401:
            print("💡 Invalid or expired token. Please check your API token in ha_config.env")
        return False
    except Exception as e:
        print(f"❌ Error connecting to Home Assistant: {e}")
        return False
    
    # Categorize entities
    categories = defaultdict(list)
    domain_counts = defaultdict(int)
    
    for entity in entities:
        entity_id = entity['entity_id']
        domain = entity_id.split('.')[0] if '.' in entity_id else 'unknown'
        
        # Count domains
        domain_counts[domain] += 1
        
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
        
        # Get entity details
        entity_info = {
            'entity_id': entity_id,
            'name': entity.get('attributes', {}).get('friendly_name', entity_id),
            'state': entity['state'],
            'domain': domain,
            'device_class': entity.get('attributes', {}).get('device_class', ''),
            'unit_of_measurement': entity.get('attributes', {}).get('unit_of_measurement', ''),
            'icon': entity.get('attributes', {}).get('icon', ''),
            'area': entity.get('attributes', {}).get('area', ''),
            'last_changed': entity.get('last_changed', ''),
            'last_updated': entity.get('last_updated', '')
        }
        
        categories[category].append(entity_info)
    
    # Create documentation
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    doc_content = f"""# Home Assistant Entity Inventory

Generated on: {timestamp}

## Summary

- **Total Entities**: {len(entities)}
- **Total Domains**: {len(domain_counts)}

## Entity Categories

"""
    
    for category, items in sorted(categories.items()):
        doc_content += f"### {category.title()} ({len(items)} entities)\n\n"
        
        for item in sorted(items, key=lambda x: x['entity_id']):
            doc_content += f"- **{item['name']}** (`{item['entity_id']}`)\n"
            doc_content += f"  - State: {item['state']}\n"
            if item['device_class']:
                doc_content += f"  - Device Class: {item['device_class']}\n"
            if item['unit_of_measurement']:
                doc_content += f"  - Unit: {item['unit_of_measurement']}\n"
            if item['area']:
                doc_content += f"  - Area: {item['area']}\n"
            if item['icon']:
                doc_content += f"  - Icon: {item['icon']}\n"
            doc_content += "\n"
    
    # Add domain summary
    doc_content += "## Domain Summary\n\n"
    for domain, count in sorted(domain_counts.items()):
        doc_content += f"- **{domain}**: {count} entities\n"
    
    # Add top entities by domain
    doc_content += "\n## Top Entities by Domain\n\n"
    for domain, count in sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        domain_entities = [e for e in entities if e['entity_id'].startswith(f"{domain}.")]
        doc_content += f"### {domain.title()} ({count} entities)\n"
        for entity in domain_entities[:5]:  # Show first 5
            name = entity.get('attributes', {}).get('friendly_name', entity['entity_id'])
            doc_content += f"- {name} (`{entity['entity_id']}`) - {entity['state']}\n"
        if len(domain_entities) > 5:
            doc_content += f"- ... and {len(domain_entities) - 5} more\n"
        doc_content += "\n"
    
    # Save documentation
    with open('entity_inventory.md', 'w') as f:
        f.write(doc_content)
    
    # Save JSON data
    data = {
        'timestamp': timestamp,
        'total_entities': len(entities),
        'total_domains': len(domain_counts),
        'categories': {cat: len(items) for cat, items in categories.items()},
        'domains': dict(domain_counts),
        'entities': entities
    }
    
    with open('entity_inventory.json', 'w') as f:
        json.dump(data, f, indent=2, default=str)
    
    print("✅ Entity inventory created successfully!")
    print("📄 Documentation: entity_inventory.md")
    print("📊 Raw data: entity_inventory.json")
    
    # Print summary
    print(f"\n📊 Summary:")
    print(f"   Total entities: {len(entities)}")
    print(f"   Categories: {len(categories)}")
    print(f"   Domains: {len(domain_counts)}")
    
    print(f"\n🔝 Top domains:")
    for domain, count in sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"   {domain}: {count} entities")
    
    return True

def main():
    success = extract_entities_with_config()
    
    if not success:
        print("❌ Entity extraction failed")
        exit(1)

if __name__ == '__main__':
    main()
