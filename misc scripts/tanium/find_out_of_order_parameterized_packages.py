import requests
import json
import re

# Config
url = "https://"  # Replace with your server
token = "token-"        # Replace with your actual session token

# Headers
common_headers = {
    "Session": f"{token}",
    "Accept": "application/json"
}

# Step 1: Get all packages that contain a parameter_definition
tanium_options = {
    "cache_filters": [
        {
            "field": "parameter_definition",
            "value": ".*",
            "operator": "RegexMatch"
        }
    ]
}
headers = {
    **common_headers,
    "tanium-options": json.dumps(tanium_options)
}

try:
    response = requests.get(f"{url}/api/v2/packages", headers=headers)
    response.raise_for_status()
    packages = response.json()["data"]

    # Step 2: Extract package IDs
    package_ids = [pkg["id"] for pkg in packages if "id" in pkg]

except Exception as e:
    print(f"Failed to get package list: {e}")
    exit(1)

# Step 3: Function to check for out-of-order parameter keys
def check_package(package_id):
    try:
        resp = requests.get(f"{url}/api/v2/packages/{package_id}", headers=common_headers)
        resp.raise_for_status()
        data = resp.json()["data"]

        command = data.get("command", "")
        parameters_json = data.get("parameter_definition", "")
        if not command or not parameters_json:
            return

        parameters = json.loads(parameters_json).get("parameters", [])
        param_keys = [p["key"] for p in parameters if p.get("key")]

        command_keys = re.findall(r'\$(\d+)', command)
        command_keys = [f"${i}" for i in sorted(map(int, command_keys))]

        if param_keys != command_keys:
            print(f"Out of order: ID={data['id']}, Name={data['name']}")

    except Exception as e:
        print(f"Error checking package {package_id}: {e}")

# Step 4: Run checks
for pid in package_ids:
    check_package(pid)
