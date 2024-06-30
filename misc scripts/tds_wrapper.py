import http.client
import json
import ssl
import os
import subprocess
import time
import sys
from datetime import datetime, timezone

# File to store the last execution time
LAST_RUN_TIME_FILE = 'last_run_time.txt'

# Maximum wait time in seconds (5 minutes)
MAX_WAIT_TIME = 300

# Polling interval in seconds
POLL_INTERVAL = 30

# Function to load environment variables from a file


def load_env_vars(filename):
    """Loads environment variables from a file.

    Args:
        filename (str): The path to the environment file.

    Returns:
        dict: A dictionary containing the environment variables.

    Raises:
        FileNotFoundError: If the environment file is not found.
        SystemExit: If there's an error loading environment variables.
    """

    env_vars = {}
    try:
        with open(filename) as file:
            for line in file:
                line = line.strip()
                if line and '=' in line:
                    name, value = line.split('=', 1)
                    env_vars[name] = value
        return env_vars
    except FileNotFoundError:
        print(f"Error: Environment file '{filename}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading environment variables: {e}")
        sys.exit(1)


# Load environment variables from config.env file
env_vars = load_env_vars('config.env')

# URL details
host = env_vars.get("HOST")
api_token = env_vars.get("API_TOKEN")

# Endpoint
status_endpoint = "/plugin/products/core-data/v1/status"

# Create an SSL context that ignores certificate verification
context = ssl._create_unverified_context()

# Function to create a new connection


def create_connection():
    """Creates an HTTPS connection to the Tanium server."""
    return http.client.HTTPSConnection(host, context=context)


# Headers including the API token
headers = {
    "session": f"{api_token}",
    "Content-Type": "application/json"
}

# Function to make a GET request to the status endpoint


def get_status():
    """Fetches the status data from the Tanium server.

    Returns:
        dict: The JSON response data, or None if there's an error.
    """

    conn = create_connection()
    try:
        conn.request("GET", status_endpoint, headers=headers)
        response = conn.getresponse()
        if response.status == 200:
            data = response.read().decode('utf-8')
            return json.loads(data)
        else:
            print(f"Error fetching status data: Status code: {
                  response.status}")
            return None
    except Exception as e:
        print(f"Error fetching status data: {e}")
        return None
    finally:
        conn.close()

# Function to parse the JSON response for the 'next' scheduled time


def parse_next_scheduled_time(data):
    """Parses the 'next' scheduled time for the 'harvest' process from the JSON response.

    Args:
        data (dict): The JSON response data.

    Returns:
        datetime: The next scheduled harvest time as a datetime object, or None if not found or invalid.
    """

    next_scheduled_time = None

    next_time_str = data.get('harvest', {}).get(
        'next')  # Get 'next' from the 'harvest' section
    if next_time_str:
        try:
            # Manually handle the 'Z' for UTC and truncate fractional seconds
            if next_time_str.endswith('Z'):
                next_time_str = next_time_str[:-1] + ' +00:00'

            # Truncate fractional seconds to 6 digits (keeping the space if present)
            parts = next_time_str.split('.')
            if len(parts) > 1:
                fractional_part = parts[1][:6]
                next_time_str = parts[0] + '.' + fractional_part + ' +00:00'

            # Parse the timestamp
            next_time = datetime.strptime(
                next_time_str, '%Y-%m-%dT%H:%M:%S.%f %z')

            if not next_scheduled_time or next_time < next_scheduled_time:
                next_scheduled_time = next_time
        except ValueError as e:
            print(f"Error: Invalid 'next' time format: {next_time_str} - {e}")

    return next_scheduled_time


# Function to execute an external script with arguments
def execute_script_with_args(script_name, args):
    """Executes an external Python script with arguments.

    Args:
        script_name (str): The name of the script to execute.
        args (list): A list of arguments to pass to the script.

    Returns:
        subprocess.CompletedProcess: The result of the script execution.
    """

    # Get the Python path from an environment variable
    # Default to 'python3' if not set
    python_path = os.environ.get('CUSTOM_PYTHON_PATH', 'python3')

    command = [python_path, script_name] + args
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        return result
    except FileNotFoundError:
        print(f"Error: Script '{script_name}' not found.")
        return None
    except Exception as e:
        print(f"Error executing script: {e}")
        return None

# Main function


def main():
    """Main function to orchestrate the sensor toggling logic."""

    # Fetch and parse the status to get the next scheduled harvest time
    status_data = get_status()
    if status_data is None:
        print("Error: Could not fetch status data.")
        sys.exit(1)

    initial_next_scheduled_time = parse_next_scheduled_time(status_data)
    if initial_next_scheduled_time is None:
        print("Error: Could not determine the next scheduled harvest time.")
        sys.exit(1)

    print(f"The next scheduled harvest is at {initial_next_scheduled_time}.")
    current_time = datetime.now(timezone.utc)
    time_to_wait = (initial_next_scheduled_time - current_time).total_seconds()

    # Step 1: Enable sensors immediately
    print("Enabling sensors...")
    enable_result = execute_script_with_args(
        "toggle_tds_sensors.py", ["--enable"])
    if enable_result is None or enable_result.returncode != 0:
        print(f"Error: Failed to enable sensors: {
              enable_result.stderr if enable_result else ''}")
        sys.exit(1)
    print("Sensors enabled successfully.")

    if time_to_wait > 0:
        print(f"Waiting for {
              time_to_wait} seconds until the next scheduled harvest.")
        time.sleep(time_to_wait)

    # Step 2: Loop to check if the "next" time has changed, indicating the harvest has started
    start_time = time.time()
    while (time.time() - start_time) < MAX_WAIT_TIME:
        status_data = get_status()
        if status_data is None:
            print(
                "Error: Could not fetch status data to verify if the harvest has started.")
            time.sleep(POLL_INTERVAL)
            continue

        new_next_scheduled_time = parse_next_scheduled_time(status_data)
        if new_next_scheduled_time != initial_next_scheduled_time:
            print("Harvest has started. Disabling sensors...")

            # Step 3: Disable sensors
            disable_result = execute_script_with_args(
                "toggle_tds_sensors.py", ["--disable"])
            if disable_result is None or disable_result.returncode != 0:
                print(f"Error: Failed to disable sensors: {
                      disable_result.stderr if disable_result else ''}")
                sys.exit(1)
            print("Sensors disabled successfully.")
            return  # Exit the script successfully

        time.sleep(POLL_INTERVAL)

    print(f"Warning: The next scheduled time did not change within {
          MAX_WAIT_TIME} seconds.")


if __name__ == "__main__":
    main()
