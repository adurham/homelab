#!/usr/bin/env python3
"""
Home Assistant REST API Client
A comprehensive Python client for interacting with Home Assistant via REST API
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union

class HomeAssistantAPI:
    """
    Home Assistant REST API Client
    
    Provides a comprehensive interface to interact with Home Assistant
    via the REST API with proper error handling and convenience methods.
    """
    
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        """
        Initialize the Home Assistant API client
        
        Args:
            base_url: Home Assistant URL (e.g., "http://192.168.86.2:8123")
            token: Long-lived access token
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.api_url = f"{self.base_url}/api"
        self.token = token
        self.timeout = timeout
        
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                     params: Optional[Dict] = None) -> Optional[Dict]:
        """
        Make a request to the Home Assistant API
        
        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint (without /api prefix)
            data: Request body data
            params: URL parameters
            
        Returns:
            Response JSON data or None if error
        """
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=self.timeout
            )
            
            if response.status_code in [200, 201]:
                try:
                    return response.json()
                except json.JSONDecodeError:
                    return {"message": response.text}
            else:
                print(f"API Error {response.status_code}: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            return None
    
    # Health and Status Methods
    
    def is_online(self) -> bool:
        """Check if Home Assistant is online and API is accessible"""
        result = self._make_request("GET", "/")
        return result is not None and "message" in result
    
    def get_config(self) -> Optional[Dict]:
        """Get Home Assistant configuration"""
        return self._make_request("GET", "/config")
    
    def get_components(self) -> Optional[List[str]]:
        """Get list of loaded components"""
        return self._make_request("GET", "/components")
    
    def get_services(self) -> Optional[List[Dict]]:
        """Get available services"""
        return self._make_request("GET", "/services")
    
    # Entity Management Methods
    
    def get_all_entities(self) -> Optional[List[Dict]]:
        """Get all entity states"""
        return self._make_request("GET", "/states")
    
    def get_entity(self, entity_id: str) -> Optional[Dict]:
        """Get specific entity state"""
        return self._make_request("GET", f"/states/{entity_id}")
    
    def get_entities_by_domain(self, domain: str) -> List[Dict]:
        """Get all entities for a specific domain"""
        entities = self.get_all_entities()
        if entities:
            return [e for e in entities if e['entity_id'].startswith(f"{domain}.")]
        return []
    
    def set_entity_state(self, entity_id: str, state: Union[str, float, int], 
                        attributes: Optional[Dict] = None) -> bool:
        """
        Set entity state and attributes
        
        Args:
            entity_id: Entity ID (e.g., "sensor.temperature")
            state: New state value
            attributes: Optional attributes dictionary
        """
        data = {"state": str(state)}
        if attributes:
            data["attributes"] = attributes
        
        result = self._make_request("POST", f"/states/{entity_id}", data)
        return result is not None
    
    def delete_entity(self, entity_id: str) -> bool:
        """Delete an entity"""
        result = self._make_request("DELETE", f"/states/{entity_id}")
        return result is not None
    
    # Service Call Methods
    
    def call_service(self, domain: str, service: str, entity_id: Optional[str] = None, 
                    **kwargs) -> bool:
        """
        Call a Home Assistant service
        
        Args:
            domain: Service domain (e.g., "light", "switch")
            service: Service name (e.g., "turn_on", "turn_off")
            entity_id: Optional entity ID to target
            **kwargs: Additional service data
        """
        data = kwargs.copy()
        if entity_id:
            data["entity_id"] = entity_id
        
        result = self._make_request("POST", f"/services/{domain}/{service}", data)
        return result is not None
    
    def turn_on_light(self, entity_id: str, **kwargs) -> bool:
        """Turn on a light with optional parameters"""
        return self.call_service("light", "turn_on", entity_id, **kwargs)
    
    def turn_off_light(self, entity_id: str) -> bool:
        """Turn off a light"""
        return self.call_service("light", "turn_off", entity_id)
    
    def turn_on_switch(self, entity_id: str) -> bool:
        """Turn on a switch"""
        return self.call_service("switch", "turn_on", entity_id)
    
    def turn_off_switch(self, entity_id: str) -> bool:
        """Turn off a switch"""
        return self.call_service("switch", "turn_off", entity_id)
    
    def restart_home_assistant(self) -> bool:
        """Restart Home Assistant"""
        return self.call_service("homeassistant", "restart")
    
    def reload_configuration(self) -> bool:
        """Reload Home Assistant configuration"""
        return self.call_service("homeassistant", "reload_config_entry")
    
    # Automation Methods
    
    def trigger_automation(self, entity_id: str) -> bool:
        """Trigger an automation"""
        return self.call_service("automation", "trigger", entity_id)
    
    def enable_automation(self, entity_id: str) -> bool:
        """Enable an automation"""
        return self.call_service("automation", "turn_on", entity_id)
    
    def disable_automation(self, entity_id: str) -> bool:
        """Disable an automation"""
        return self.call_service("automation", "turn_off", entity_id)
    
    def get_automation_state(self, entity_id: str) -> Optional[str]:
        """Get automation state (on/off)"""
        entity = self.get_entity(entity_id)
        return entity["state"] if entity else None
    
    # History Methods
    
    def get_history(self, entity_ids: List[str], start_time: Optional[datetime] = None, 
                   end_time: Optional[datetime] = None, minimal: bool = True) -> Optional[List]:
        """
        Get historical data for entities
        
        Args:
            entity_ids: List of entity IDs to get history for
            start_time: Start time (defaults to 1 day ago)
            end_time: End time (defaults to now)
            minimal: Use minimal response for faster queries
        """
        if start_time is None:
            start_time = datetime.now() - timedelta(days=1)
        
        params = {
            "filter_entity_id": ",".join(entity_ids)
        }
        
        if minimal:
            params["minimal_response"] = "1"
        
        if end_time:
            params["end_time"] = end_time.isoformat()
        
        return self._make_request("GET", f"/history/period/{start_time.isoformat()}", 
                                params=params)
    
    # Event Methods
    
    def fire_event(self, event_type: str, event_data: Optional[Dict] = None) -> bool:
        """Fire a custom event"""
        result = self._make_request("POST", f"/events/{event_type}", event_data)
        return result is not None and "message" in result
    
    # Template Methods
    
    def render_template(self, template: str) -> Optional[str]:
        """Render a Home Assistant template"""
        result = self._make_request("POST", "/template", {"template": template})
        return result if isinstance(result, str) else None
    
    # Configuration Methods
    
    def check_configuration(self) -> Optional[Dict]:
        """Check Home Assistant configuration"""
        return self._make_request("POST", "/config/core/check_config")
    
    # Utility Methods
    
    def get_entity_value(self, entity_id: str) -> Optional[Union[str, float, int]]:
        """Get just the state value of an entity"""
        entity = self.get_entity(entity_id)
        if entity:
            try:
                # Try to convert to number if possible
                state = entity["state"]
                if state.replace(".", "").replace("-", "").isdigit():
                    return float(state) if "." in state else int(state)
                return state
            except (ValueError, AttributeError):
                return entity["state"]
        return None
    
    def get_entity_attribute(self, entity_id: str, attribute: str) -> Optional[Any]:
        """Get a specific attribute of an entity"""
        entity = self.get_entity(entity_id)
        if entity and "attributes" in entity:
            return entity["attributes"].get(attribute)
        return None
    
    def find_entities(self, pattern: str) -> List[Dict]:
        """Find entities matching a pattern"""
        entities = self.get_all_entities()
        if entities:
            return [e for e in entities if pattern.lower() in e['entity_id'].lower() or 
                   pattern.lower() in e.get('attributes', {}).get('friendly_name', '').lower()]
        return []
    
    def monitor_entities(self, entity_ids: List[str], callback, interval: int = 5):
        """
        Monitor entities for state changes
        
        Args:
            entity_ids: List of entity IDs to monitor
            callback: Function to call when state changes (entity_id, old_state, new_state)
            interval: Check interval in seconds
        """
        previous_states = {}
        
        print(f"Starting monitor for entities: {entity_ids}")
        
        try:
            while True:
                current_states = {}
                
                for entity_id in entity_ids:
                    entity = self.get_entity(entity_id)
                    if entity:
                        current_states[entity_id] = entity["state"]
                
                # Check for changes
                for entity_id, current_state in current_states.items():
                    if entity_id in previous_states and previous_states[entity_id] != current_state:
                        print(f"State change: {entity_id} {previous_states[entity_id]} -> {current_state}")
                        callback(entity_id, previous_states[entity_id], current_state)
                
                previous_states = current_states
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("Monitoring stopped")


# Example usage and testing
def main():
    """Example usage of the HomeAssistantAPI class"""
    
    # Configuration - replace with your values
    HA_URL = "http://192.168.86.2:8123"
    HA_TOKEN = "your_long_lived_access_token_here"
    
    # Initialize the client
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Test connection
    if not ha.is_online():
        print("❌ Home Assistant is not accessible")
        return
    
    print("✅ Home Assistant is online")
    
    # Get some basic info
    config = ha.get_config()
    if config:
        print(f"Home Assistant version: {config.get('version', 'Unknown')}")
        print(f"Location: {config.get('location_name', 'Unknown')}")
    
    # Get all lights
    lights = ha.get_entities_by_domain("light")
    print(f"\nFound {len(lights)} lights:")
    for light in lights:
        print(f"  {light['entity_id']}: {light['state']}")
    
    # Example: Turn on a light (uncomment to test)
    # if lights:
    #     first_light = lights[0]['entity_id']
    #     print(f"\nTurning on {first_light}")
    #     if ha.turn_on_light(first_light):
    #         print("✅ Light turned on successfully")
    #     else:
    #         print("❌ Failed to turn on light")
    
    # Example: Set a sensor value (uncomment to test)
    # print("\nSetting sensor value...")
    # if ha.set_entity_state("sensor.test_temperature", 25.5, {"unit_of_measurement": "°C"}):
    #     print("✅ Sensor value set successfully")
    # else:
    #     print("❌ Failed to set sensor value")
    
    # Example: Monitor entities (uncomment to test)
    # def on_state_change(entity_id, old_state, new_state):
    #     print(f"🔔 {entity_id} changed from {old_state} to {new_state}")
    # 
    # print("\nMonitoring entities (press Ctrl+C to stop)...")
    # ha.monitor_entities(["sensor.kitchen_temperature"], on_state_change)


if __name__ == "__main__":
    main()
