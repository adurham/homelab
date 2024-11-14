import json
from datetime import datetime, timedelta
import os
import tanium

# Initialize base path from Tanium client
base_path = tanium.client.common.get_client_dir()

# Construct RESULTS_FILE with base_path
RESULTS_FILE = os.path.join(base_path, "Tools", "tls_results.json")

# Check if the file exists
if not os.path.exists(RESULTS_FILE):
    tanium.results.add(f"TSE-Error: RESULTS_FILE not found.")
else:
    # Read the JSON data from the file
    with open(RESULTS_FILE, 'r') as file:
        data = json.load(file)

    # Get the current time and the cutoff time for one week ago
    now = datetime.now()
    one_week_ago = now - timedelta(weeks=1)

    # Flag to track if any domain meets the criteria
    found_success = False

    # Iterate over the domains and check conditions
    for domain, records in data.items():
        for ip, details in records.items():
            # Ensure 'last_successful' exists and is a valid string
            last_successful = details.get("last_successful")
            if isinstance(last_successful, str):
                try:
                    # Parse the timestamp
                    last_successful_dt = datetime.fromisoformat(
                        last_successful)
                    # Check the conditions
                    if details.get("successful") and last_successful_dt >= one_week_ago:
                        found_success = True
                        break  # Exit the inner loop as we found a match for this domain
                except ValueError:
                    tanium.results.add(
                        f"TSE-Error: Invalid timestamp format for domain '{domain}', IP '{ip}'")

    print(found_success)
    tanium.results.add(found_success)
