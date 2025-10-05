#!/usr/bin/env python3
"""
Practical Home Assistant REST API Examples
Real-world examples for common automation and monitoring tasks
"""

import os
import time
from datetime import datetime, timedelta
from hass_api_client import HomeAssistantAPI

# Load configuration from environment variables
HA_URL = os.getenv("HA_URL", "http://192.168.86.2:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "your_token_here")

def example_1_basic_monitoring():
    """Example 1: Basic entity monitoring"""
    print("🔍 Example 1: Basic Entity Monitoring")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    if not ha.is_online():
        print("❌ Home Assistant not accessible")
        return
    
    # Get all entities
    entities = ha.get_all_entities()
    if entities:
        print(f"📊 Found {len(entities)} entities")
        
        # Show some statistics
        domains = {}
        for entity in entities:
            domain = entity['entity_id'].split('.')[0]
            domains[domain] = domains.get(domain, 0) + 1
        
        print("\n📋 Entity domains:")
        for domain, count in sorted(domains.items()):
            print(f"  {domain}: {count}")
    
    # Get specific entities
    lights = ha.get_entities_by_domain("light")
    sensors = ha.get_entities_by_domain("sensor")
    
    print(f"\n💡 Lights: {len(lights)}")
    for light in lights[:5]:  # Show first 5
        print(f"  {light['entity_id']}: {light['state']}")
    
    print(f"\n🌡️  Sensors: {len(sensors)}")
    for sensor in sensors[:5]:  # Show first 5
        print(f"  {sensor['entity_id']}: {sensor['state']}")


def example_2_light_control():
    """Example 2: Light control automation"""
    print("\n💡 Example 2: Light Control")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Get all lights
    lights = ha.get_entities_by_domain("light")
    
    if not lights:
        print("No lights found")
        return
    
    print(f"Found {len(lights)} lights")
    
    # Turn off all lights
    print("\n🔌 Turning off all lights...")
    for light in lights:
        entity_id = light['entity_id']
        if light['state'] == 'on':
            if ha.turn_off_light(entity_id):
                print(f"  ✅ Turned off {entity_id}")
            else:
                print(f"  ❌ Failed to turn off {entity_id}")
    
    time.sleep(2)
    
    # Turn on first few lights
    print("\n🔆 Turning on first few lights...")
    for light in lights[:3]:  # Turn on first 3 lights
        entity_id = light['entity_id']
        if ha.turn_on_light(entity_id):
            print(f"  ✅ Turned on {entity_id}")
        else:
            print(f"  ❌ Failed to turn on {entity_id}")


def example_3_temperature_monitoring():
    """Example 3: Temperature monitoring and alerting"""
    print("\n🌡️  Example 3: Temperature Monitoring")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Find temperature sensors
    temp_sensors = []
    all_entities = ha.get_all_entities()
    
    for entity in all_entities:
        entity_id = entity['entity_id']
        if 'temperature' in entity_id.lower() or 'temp' in entity_id.lower():
            temp_sensors.append(entity)
    
    print(f"Found {len(temp_sensors)} temperature sensors:")
    
    for sensor in temp_sensors:
        entity_id = sensor['entity_id']
        state = sensor['state']
        friendly_name = sensor.get('attributes', {}).get('friendly_name', entity_id)
        
        print(f"  {friendly_name}: {state}")
        
        # Check for extreme temperatures
        try:
            temp_value = float(state)
            if temp_value > 30:
                print(f"    🔥 HOT ALERT: {temp_value}°C")
            elif temp_value < 5:
                print(f"    🧊 COLD ALERT: {temp_value}°C")
        except ValueError:
            pass  # Not a numeric temperature


def example_4_automation_management():
    """Example 4: Automation management"""
    print("\n🤖 Example 4: Automation Management")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Get all automations
    automations = ha.get_entities_by_domain("automation")
    
    print(f"Found {len(automations)} automations:")
    
    enabled_count = 0
    disabled_count = 0
    
    for automation in automations:
        entity_id = automation['entity_id']
        state = automation['state']
        friendly_name = automation.get('attributes', {}).get('friendly_name', entity_id)
        
        if state == 'on':
            enabled_count += 1
            status = "✅ Enabled"
        else:
            disabled_count += 1
            status = "❌ Disabled"
        
        print(f"  {friendly_name}: {status}")
    
    print(f"\n📊 Summary: {enabled_count} enabled, {disabled_count} disabled")


def example_5_historical_data():
    """Example 5: Historical data analysis"""
    print("\n📊 Example 5: Historical Data Analysis")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Get temperature sensors
    sensors = ha.get_entities_by_domain("sensor")
    temp_sensors = [s for s in sensors if 'temperature' in s['entity_id'].lower()]
    
    if not temp_sensors:
        print("No temperature sensors found")
        return
    
    # Get historical data for the last hour
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=1)
    
    entity_ids = [s['entity_id'] for s in temp_sensors[:3]]  # First 3 sensors
    
    print(f"Getting historical data for {len(entity_ids)} sensors...")
    
    history = ha.get_history(entity_ids, start_time, end_time, minimal=True)
    
    if history:
        print(f"Retrieved {len(history)} historical entries")
        
        # Analyze the data
        for sensor_data in history:
            if sensor_data:
                entity_id = sensor_data[0]['entity_id']
                data_points = len(sensor_data)
                print(f"  {entity_id}: {data_points} data points")
    else:
        print("No historical data available")


def example_6_custom_events():
    """Example 6: Custom event handling"""
    print("\n🎯 Example 6: Custom Events")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Fire a custom event
    event_data = {
        "source": "api_example",
        "timestamp": datetime.now().isoformat(),
        "message": "Hello from Python script!"
    }
    
    if ha.fire_event("custom_api_test", event_data):
        print("✅ Custom event fired successfully")
    else:
        print("❌ Failed to fire custom event")
    
    # Fire another event with different data
    automation_data = {
        "trigger": "manual",
        "entity": "script.example",
        "action": "started"
    }
    
    if ha.fire_event("automation_triggered", automation_data):
        print("✅ Automation trigger event fired")
    else:
        print("❌ Failed to fire automation trigger event")


def example_7_template_rendering():
    """Example 7: Template rendering"""
    print("\n🔧 Example 7: Template Rendering")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Simple templates
    templates = [
        "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}",
        "{{ states('sun.sun') }}",
        "{{ states.sensor.time | default('No time sensor') }}",
        "{{ states.light | selectattr('state', 'equalto', 'on') | list | length }} lights are on"
    ]
    
    for template in templates:
        result = ha.render_template(template)
        if result:
            print(f"Template: {template}")
            print(f"Result: {result}")
            print()


def example_8_state_change_monitoring():
    """Example 8: Real-time state change monitoring"""
    print("\n👀 Example 8: State Change Monitoring")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Find some entities to monitor
    lights = ha.get_entities_by_domain("light")
    sensors = ha.get_entities_by_domain("sensor")
    
    # Monitor first few lights and sensors
    entities_to_monitor = []
    entities_to_monitor.extend([l['entity_id'] for l in lights[:2]])
    entities_to_monitor.extend([s['entity_id'] for s in sensors[:2]])
    
    if not entities_to_monitor:
        print("No entities to monitor")
        return
    
    print(f"Monitoring {len(entities_to_monitor)} entities...")
    print("Press Ctrl+C to stop monitoring")
    
    def on_state_change(entity_id, old_state, new_state):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {entity_id}: {old_state} → {new_state}")
    
    try:
        ha.monitor_entities(entities_to_monitor, on_state_change, interval=2)
    except KeyboardInterrupt:
        print("\nMonitoring stopped")


def example_9_bulk_operations():
    """Example 9: Bulk operations"""
    print("\n⚡ Example 9: Bulk Operations")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Get all lights and switches
    lights = ha.get_entities_by_domain("light")
    switches = ha.get_entities_by_domain("switch")
    
    all_devices = lights + switches
    print(f"Found {len(all_devices)} controllable devices")
    
    # Turn off all devices
    print("\n🔌 Turning off all devices...")
    off_count = 0
    for device in all_devices:
        entity_id = device['entity_id']
        if device['state'] == 'on':
            if 'light' in entity_id:
                success = ha.turn_off_light(entity_id)
            else:
                success = ha.turn_off_switch(entity_id)
            
            if success:
                off_count += 1
    
    print(f"✅ Turned off {off_count} devices")
    
    time.sleep(1)
    
    # Turn on a few devices
    print("\n🔆 Turning on some devices...")
    on_count = 0
    for device in all_devices[:5]:  # First 5 devices
        entity_id = device['entity_id']
        if 'light' in entity_id:
            success = ha.turn_on_light(entity_id)
        else:
            success = ha.turn_on_switch(entity_id)
        
        if success:
            on_count += 1
    
    print(f"✅ Turned on {on_count} devices")


def example_10_system_management():
    """Example 10: System management"""
    print("\n⚙️  Example 10: System Management")
    print("=" * 50)
    
    ha = HomeAssistantAPI(HA_URL, HA_TOKEN)
    
    # Get system configuration
    config = ha.get_config()
    if config:
        print(f"Home Assistant Version: {config.get('version', 'Unknown')}")
        print(f"Location: {config.get('location_name', 'Unknown')}")
        print(f"Timezone: {config.get('time_zone', 'Unknown')}")
        print(f"Elevation: {config.get('elevation', 'Unknown')}m")
    
    # Get loaded components
    components = ha.get_components()
    if components:
        print(f"\n📦 Loaded Components: {len(components)}")
        print("Some components:", ", ".join(components[:10]))
    
    # Check configuration
    print("\n🔍 Checking configuration...")
    config_check = ha.check_configuration()
    if config_check:
        if config_check.get('result') == 'valid':
            print("✅ Configuration is valid")
        else:
            print("❌ Configuration has errors:")
            errors = config_check.get('errors', [])
            for error in errors:
                print(f"  - {error}")
    
    # Get services
    services = ha.get_services()
    if services:
        print(f"\n🔧 Available Services: {len(services)}")
        for service in services[:5]:
            domain = service.get('domain', 'unknown')
            service_list = service.get('services', [])
            print(f"  {domain}: {', '.join(service_list[:3])}")


def main():
    """Run all examples"""
    print("🏠 Home Assistant REST API Practical Examples")
    print("=" * 60)
    
    # Check if we have a valid token
    if HA_TOKEN == "your_token_here":
        print("❌ Please set HA_TOKEN environment variable or update the script")
        print("   Get your token from: http://192.168.86.2:8123/profile")
        return
    
    examples = [
        example_1_basic_monitoring,
        example_2_light_control,
        example_3_temperature_monitoring,
        example_4_automation_management,
        example_5_historical_data,
        example_6_custom_events,
        example_7_template_rendering,
        example_8_state_change_monitoring,
        example_9_bulk_operations,
        example_10_system_management,
    ]
    
    for i, example_func in enumerate(examples, 1):
        try:
            example_func()
            print(f"\n✅ Example {i} completed")
        except Exception as e:
            print(f"\n❌ Example {i} failed: {e}")
        
        if i < len(examples):
            input("\nPress Enter to continue to next example...")
    
    print("\n🎉 All examples completed!")


if __name__ == "__main__":
    main()
