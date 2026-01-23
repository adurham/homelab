import json
import sys

def extract_entities(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)

    keywords = ['emporia', 'ecobee', 'flair', 'climate', 'power', 'energy', 'temperature', 'humidity']

    found_entities = []
    for entity in data:
        entity_id = entity.get('entity_id', '')
        attributes = entity.get('attributes', {})
        friendly_name = attributes.get('friendly_name', '')

        # Check if any keyword matches entity_id
        if any(k in entity_id.lower() for k in keywords):
            found_entities.append({
                'id': entity_id,
                'state': entity.get('state'),
                'unit': attributes.get('unit_of_measurement'),
                'name': friendly_name
            })

    # Sort and print
    for e in sorted(found_entities, key=lambda x: x['id']):
        print(f"{e['id']} | {e['state']} | {e['unit']} | {e['name']}")

if __name__ == "__main__":
    extract_entities('/Users/adam.durham/repos/homelab/homeassistant/ha_states.json')
