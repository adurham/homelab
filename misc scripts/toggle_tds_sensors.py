import http.client
import json
import ssl
import os
import argparse

# Function to load environment variables from a file
def load_env_vars(filename):
    env_vars = {}
    with open(filename) as file:
        for line in file:
            line = line.strip()
            if line and '=' in line:  # Ensure the line is not empty and contains '='
                name, value = line.split('=', 1)
                env_vars[name] = value
    return env_vars

# Load environment variables from config.env file
env_vars = load_env_vars('config.env')

# URL details
host = env_vars.get("HOST")
api_token = env_vars.get("API_TOKEN")

# Endpoints
get_endpoint = "/plugin/products/core-data/v1/harvest"
post_endpoint = "/plugin/products/core-data/v1/harvest"

# List of sensors to exclude
exception_sensors = [
    # Required Sensors
    "Computer Name", 
    "Computer ID", 
    "Endpoint Fingerprint",
    # DEC Sensors 
    "Tanium Client IP Address", 
    "OS Platform", 
    "Direct Connect - Connection Configuration",
    # Deploy Module Sensors
    "Deploy - Mean Time to Deploy",
    "Deploy - Is Supported",
    "Deploy - All Deployment Activities",
    "Deploy - All Software Packages Applicability Details",
    "Deploy - Has Recent Scan Results",
    "Deploy - Software Package Action History",
    # Deploy Sensors
    "Deploy - Software Packages",
    "Deploy - Software Packages Gallery Applicability",
    "Deploy - Is Process Running",
    "Deploy - Coverage Status Details",
    "Deploy - Coverage Status",
    "Deploy - All Deployments Errors",
    "Deploy - Deployments",
    "Deploy - Self Service Activity",
    "Deploy - Maintenance Window Enforcements",
]

# Create an SSL context that ignores certificate verification
context = ssl._create_unverified_context()

# Function to create a new connection
def create_connection():
    return http.client.HTTPSConnection(host, context=context)

# Headers including the API token
headers = {
    "session": f"{api_token}",
    "Content-Type": "application/json"
}

# Function to make a GET request
def get_config():
    conn = create_connection()
    conn.request("GET", get_endpoint, headers=headers)
    response = conn.getresponse()
    if response.status == 200:
        data = response.read().decode('utf-8')
        conn.close()
        return json.loads(data)
    else:
        print(f"Failed to fetch data. Status code: {response.status}")
        conn.close()
        return None

# Function to check if 'requested_by' contains 'required:group'
def contains_required_group(requested_by):
    return any("required:group" in request for request in requested_by)

# Function to make a POST request to disable or enable sensors
def post_sensors(sensors, action):
    conn = create_connection()
    sensor_list = []
    for sensor in sensors:
        parameters = sensor.get("parameters", {})
        sensor_list.append({"name": sensor["name"], "parameters": parameters})
    
    post_body = {
        "action_source": "insomnia-api-test",
        "action": action,
        "sensors": sensor_list
    }
    post_body_json = json.dumps(post_body)
    print(f"POST request body for {action}:", post_body_json)
    conn.request("POST", post_endpoint, body=post_body_json, headers=headers)
    post_response = conn.getresponse()
    if post_response.status == 200:
        print(f"POST request to {action} sensors successful.")
    else:
        post_response_data = post_response.read().decode('utf-8')
        print(f"Failed to send POST request to {action} sensors. Status code: {post_response.status}")
        print("Response:", post_response_data)
    conn.close()

# Main function to handle enabling or disabling sensors
def manage_sensors(re_enable):
    config_data = get_config()
    if config_data:
        sensors = [item for item in config_data.get('config', []) if item.get('type') == 'sensor']
        
        if re_enable:
            # Re-enable sensors that were disabled by "insomnia-api-test"
            sensors_to_enable = [sensor for sensor in sensors if "insomnia-api-test" in sensor.get("disabled_by", [])]
            post_sensors(sensors_to_enable, "Enable")
        else:
            # Disable sensors that are not in the exception list and do not contain 'required:group'
            sensors_to_disable = [
                sensor for sensor in sensors
                if sensor["name"] not in exception_sensors and not contains_required_group(sensor.get("requested_by", []))
            ]
            post_sensors(sensors_to_disable, "Disable")

        # Perform a new GET request to verify the remaining sensors
        new_config_data = get_config()
        if new_config_data:
            remaining_sensors = [item for item in new_config_data.get('config', []) if item.get('type') == 'sensor']
            remaining_sensor_names = [sensor["name"] for sensor in remaining_sensors]
            
            # Verify only the sensors in the exception list are left
            for sensor in exception_sensors:
                if sensor in remaining_sensor_names:
                    print(f"Sensor {sensor} is still present in the config list.")
                else:
                    print(f"Sensor {sensor} is missing from the config list.")

            # Also check for sensors containing 'required:group'
            for sensor in remaining_sensors:
                if contains_required_group(sensor.get("requested_by", [])):
                    print(f"Sensor {sensor['name']} contains 'required:group' and is still present in the config list.")

# Parse command-line arguments
def main():
    parser = argparse.ArgumentParser(description="Enable or disable TDS sensors.")
    parser.add_argument('--enable', action='store_true', help="Enable the sensors")
    parser.add_argument('--disable', action='store_true', help="Disable the sensors")

    args = parser.parse_args()

    if args.enable:
        manage_sensors(re_enable=True)
    elif args.disable:
        manage_sensors(re_enable=False)
    else:
        print("Please specify --enable or --disable")

if __name__ == "__main__":
    main()
