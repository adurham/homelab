import json
import os
from datetime import datetime
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

    # Iterate over the domains and print details
    for domain, records in data.items():
        for ip, details in records.items():
            # Get and trim the last_successful timestamp
            last_successful = details.get("last_successful")
            if last_successful:
                try:
                    # Parse and format the timestamp down to the minute
                    last_successful_dt = datetime.fromisoformat(
                        last_successful)
                    trimmed_last_successful = last_successful_dt.strftime(
                        "%Y-%m-%d %H:%M")
                except ValueError:
                    trimmed_last_successful = None  # Set to null if parsing fails
            else:
                trimmed_last_successful = None  # Set to null if timestamp is missing
            # Print domain, IP, and status using '|' as a delimiter
            tanium.results.add(f"{domain} | {ip} | {details.get(
                "successful")} | {trimmed_last_successful}")
