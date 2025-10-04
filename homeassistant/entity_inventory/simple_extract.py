#!/usr/bin/env python3
"""
Simple entity extraction using HTTP requests to Home Assistant API
"""

import requests
import json
from datetime import datetime
from collections import defaultdict

def extract_entities_simple():
    """Extract entities using simple HTTP requests"""
    ha_url = "http://192.168.86.2:8123"
    
    print("🔍 Extracting entities from Home Assistant...")
    
    # Try to get entities without authentication first
    try:
        response = requests.get(f"{ha_url}/api/states", timeout=10)
        
        if response.status_code == 200:
            entities = response.json()
            print(f"✅ Found {len(entities)} entities")
        elif response.status_code == 401:
            print("❌ Authentication required. Please provide an API token.")
            print("💡 You can get a token from: http://192.168.86.2:8123/profile")
            return False
        else:
            print(f"❌ Failed to get entities: HTTP {response.status_code}")
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
    success = extract_entities_simple()
    
    if not success:
        print("❌ Entity extraction failed")
        exit(1)

if __name__ == '__main__':
    main()
