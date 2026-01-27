
import os
import requests
from dotenv import load_dotenv

load_dotenv('ha_config.env')

HA_URL = os.getenv('HA_URL')
HA_TOKEN = os.getenv('HA_TOKEN')

headers = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

def get_states():
    url = f"{HA_URL}/api/states"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

states = get_states()
targets = [s['entity_id'] for s in states if ('duct' in s['entity_id'].lower() or 'temperature' in s['entity_id'].lower()) and ('vent' in s['entity_id'].lower() or 'flair' in s['entity_id'].lower() or 'game' in s['entity_id'].lower() or 'guest' in s['entity_id'].lower() or '7wq7' in s['entity_id'].lower())]
print("Found potential duct temperature entities:")
for c in sorted(targets):
    print(c)
