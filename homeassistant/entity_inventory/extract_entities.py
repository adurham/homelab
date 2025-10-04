#!/usr/bin/env python3
"""
Extract all Home Assistant entities and devices
Creates comprehensive documentation of your Home Assistant setup
"""

import json
import requests
import sys
from datetime import datetime
from collections import defaultdict

class HAEntityExtractor:
    def __init__(self, ha_url, token):
        self.ha_url = ha_url.rstrip('/')
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        })
    
    def get_entities(self):
        """Get all entities from Home Assistant"""
        try:
            response = self.session.get(f'{self.ha_url}/api/states')
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Failed to get entities: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Error getting entities: {e}")
            return None
    
    def get_devices(self):
        """Get all devices from Home Assistant"""
        try:
            response = self.session.get(f'{self.ha_url}/api/config/device_registry')
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Failed to get devices: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Error getting devices: {e}")
            return None
    
    def get_areas(self):
        """Get all areas from Home Assistant"""
        try:
            response = self.session.get(f'{self.ha_url}/api/config/area_registry')
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Failed to get areas: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Error getting areas: {e}")
            return None
    
    def categorize_entities(self, entities):
        """Categorize entities by domain and type"""
        categories = defaultdict(list)
        
        for entity in entities:
            entity_id = entity['entity_id']
            domain = entity_id.split('.')[0]
            
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
            
            categories[category].append({
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
            })
        
        return categories
    
    def create_entity_documentation(self, entities, devices, areas):
        """Create comprehensive documentation"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Categorize entities
        categories = self.categorize_entities(entities)
        
        # Create summary
        summary = {
            'timestamp': timestamp,
            'total_entities': len(entities),
            'total_devices': len(devices) if devices else 0,
            'total_areas': len(areas) if areas else 0,
            'categories': {cat: len(items) for cat, items in categories.items()},
            'domains': defaultdict(int)
        }
        
        # Count domains
        for entity in entities:
            domain = entity['entity_id'].split('.')[0]
            summary['domains'][domain] += 1
        
        # Create detailed documentation
        doc_content = f"""# Home Assistant Entity Inventory

Generated on: {timestamp}

## Summary

- **Total Entities**: {summary['total_entities']}
- **Total Devices**: {summary['total_devices']}
- **Total Areas**: {summary['total_areas']}

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
        for domain, count in sorted(summary['domains'].items()):
            doc_content += f"- **{domain}**: {count} entities\n"
        
        # Add areas if available
        if areas:
            doc_content += "\n## Areas\n\n"
            for area in areas:
                doc_content += f"- **{area.get('name', 'Unknown')}** (ID: {area.get('area_id', 'unknown')})\n"
        
        # Add devices if available
        if devices:
            doc_content += "\n## Devices\n\n"
            for device in devices:
                doc_content += f"- **{device.get('name', 'Unknown')}** (ID: {device.get('id', 'unknown')})\n"
                if device.get('manufacturer'):
                    doc_content += f"  - Manufacturer: {device['manufacturer']}\n"
                if device.get('model'):
                    doc_content += f"  - Model: {device['model']}\n"
                if device.get('area_id'):
                    doc_content += f"  - Area: {device['area_id']}\n"
                doc_content += "\n"
        
        return doc_content, summary
    
    def save_json_data(self, entities, devices, areas, summary):
        """Save raw data as JSON for programmatic use"""
        data = {
            'timestamp': summary['timestamp'],
            'summary': summary,
            'entities': entities,
            'devices': devices or [],
            'areas': areas or []
        }
        
        with open('entity_inventory.json', 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print("✅ Raw data saved to entity_inventory.json")
    
    def extract_all(self):
        """Extract all entities, devices, and areas"""
        print("🔍 Extracting Home Assistant entities...")
        
        # Get data
        entities = self.get_entities()
        if not entities:
            return False
        
        devices = self.get_devices()
        areas = self.get_areas()
        
        print(f"✅ Found {len(entities)} entities")
        if devices:
            print(f"✅ Found {len(devices)} devices")
        if areas:
            print(f"✅ Found {len(areas)} areas")
        
        # Create documentation
        doc_content, summary = self.create_entity_documentation(entities, devices, areas)
        
        # Save documentation
        with open('entity_inventory.md', 'w') as f:
            f.write(doc_content)
        
        # Save JSON data
        self.save_json_data(entities, devices, areas, summary)
        
        print("✅ Entity inventory created successfully!")
        print("📄 Documentation: entity_inventory.md")
        print("📊 Raw data: entity_inventory.json")
        
        return True

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract Home Assistant entities')
    parser.add_argument('--ha-url', default='http://192.168.86.2:8123', help='Home Assistant URL')
    parser.add_argument('--token', required=True, help='Home Assistant API token')
    
    args = parser.parse_args()
    
    extractor = HAEntityExtractor(args.ha_url, args.token)
    success = extractor.extract_all()
    
    if not success:
        print("❌ Entity extraction failed")
        sys.exit(1)

if __name__ == '__main__':
    main()
