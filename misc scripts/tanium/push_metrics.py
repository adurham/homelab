import os
import time
import json
import requests
import logging
from datetime import datetime

# Custom function to load environment variables from a file
def load_env_vars(filename):
    env_vars = {}
    with open(filename) as file:
        for line in file:
            line = line.strip()
            if line and '=' in line:  # Ensure the line is not empty and contains '='
                name, value = line.split('=', 1)
                env_vars[name] = value
    return env_vars

# Load environment variables from tanium_creds.env file
env_vars = load_env_vars('tanium_creds.env')
for key, value in env_vars.items():
    os.environ[key] = value

# Set logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variables
FQDN = os.uname()[1]
METRICS_URL = f"https://{FQDN}/metrics"
VM_URL = "http://172.16.1.16:8428/api/v1/import/prometheus"
TOKEN_VALIDATE_URL = f"https://{FQDN}/api/v2/api_tokens"
TPAN_ACCOUNT = "AMD-Enterprises"
TPAN_ENVIRONMENT = "Prod"
DEBUG = os.getenv("DEBUG")

# Static labels
LABELS = {
    "tpan_account": TPAN_ACCOUNT,
    "tpan_environment": TPAN_ENVIRONMENT,
    "tpan_server": FQDN,
    "job": "tanium_server",
    "instance": "taniumserver1.tanium.local"
}

def log(message):
    logging.info(message)

def update_env_file(new_token_response):
    with open('/home/tandev/auth_token.json', 'w') as f:
        json.dump(new_token_response, f)

def validate_and_renew_token(session_token, token_id):
    headers = {'session': session_token}
    response = requests.get(f"{TOKEN_VALIDATE_URL}/{token_id}", headers=headers, verify=False)
    if response.status_code != 200:
        log(f"Error: Failed to validate token. Response: {response.text}")
        raise Exception("Token validation failed")

    expiry = response.json().get('data').get('expiration')
    if not expiry:
        log(f"Error: Token validation response did not contain an expiration date. Response: {response.text}")
        raise Exception("No expiration in token validation")

    expiry_timestamp = int(time.mktime(time.strptime(expiry, '%Y-%m-%dT%H:%M:%S')))
    current_timestamp = int(time.time())
    time_remaining = expiry_timestamp - current_timestamp

    if time_remaining < 3600:
        renew_payload = {"token_string": session_token}
        renew_response = requests.patch(TOKEN_VALIDATE_URL, headers=headers, json=renew_payload, verify=False)
        if renew_response.status_code != 200:
            log(f"Error: Failed to renew token. Response: {renew_response.text}")
            raise Exception("Token renewal failed")

        new_token = renew_response.json().get('data').get('token_string')
        if not new_token:
            log(f"Failed to renew auth token. Renew response: {renew_response.text}")
            raise Exception("No new token obtained")

        update_env_file(renew_response.json())
        return new_token, renew_response.json().get('data').get('id')

    return session_token, token_id

def inject_labels(metrics, labels):
    output = []
    timestamp = datetime.utcnow().isoformat()  # Use datetime to add a timestamp

    for line in metrics.splitlines():
        if line.startswith('#'):
            output.append(line)
        else:
            segments = line.split(' ')
            metric_name_and_labels = segments[0]
            metric_value = segments[1]
            existing_labels_start = metric_name_and_labels.find('{')
            existing_labels_end = metric_name_and_labels.find('}')
            if existing_labels_start != -1 and existing_labels_end != -1:
                metric_name = metric_name_and_labels[:existing_labels_start]
                existing_labels = metric_name_and_labels[existing_labels_start + 1:existing_labels_end]
                label_map = dict(label.split('=') for label in existing_labels.split(',')) if existing_labels else {}
            else:
                metric_name = metric_name_and_labels
                label_map = {}

            label_map.update(labels)
            new_labels = ','.join([f'{k}="{v}"' for k, v in label_map.items()])
            output.append(f'{metric_name}{{{new_labels}}} {metric_value} {timestamp}')

    return "\n".join(output)

def push_metrics(metrics):
    headers = {'Content-Type': 'text/plain'}
    response = requests.post(VM_URL, headers=headers, data=metrics, verify=False)
    
    if response.status_code != 200:
        log(f"Failed to push metrics to VictoriaMetrics. HTTP response code: {response.status_code}")
        raise Exception("Metrics push failed")

    log("Metrics pushed successfully.")

def main():
    try:
        # Read token information from the auth_token.json file
        with open('/home/tandev/auth_token.json', 'r') as f:
            auth_token_info = json.load(f)
        
        session_token = auth_token_info.get('data', {}).get('token_string')
        token_id = auth_token_info.get('data', {}).get('id')
        
        if not session_token or not token_id:
            log("Token information is missing in auth_token.json")
            raise Exception("Missing token information")

        # Validate and renew the session token if necessary
        session_token, token_id = validate_and_renew_token(session_token, token_id)

        # Scrape metrics
        log(f"Scraping metrics from {METRICS_URL}...")
        start_time = time.time()
        headers = {'session': session_token}
        response = requests.get(METRICS_URL, headers=headers, verify=False)
        end_time = time.time()
        duration = end_time - start_time

        if response.status_code != 200:
            log(f"Failed to scrape metrics from {METRICS_URL}. HTTP response code: {response.status_code}")
            raise Exception("Metrics scraping failed")

        log(f"Metrics scraped successfully in {duration:.2f} seconds.")

        # Inject labels into metrics
        log("Injecting labels into metrics...")
        metrics = response.text
        start_time = time.time()
        metrics_with_labels = inject_labels(metrics, LABELS)
        end_time = time.time()
        duration = end_time - start_time
        log(f"Injecting labels took {duration:.2f} seconds.")

        # Push metrics to VictoriaMetrics
        log(f"Pushing metrics to VictoriaMetrics at {VM_URL}...")
        start_time = time.time()
        push_metrics(metrics_with_labels)
        end_time = time.time()
        duration = end_time - start_time
        log(f"Pushing metrics took {duration:.2f} seconds.")

    except Exception as e:
        log(f"An error occurred: {e}")
        exit(1)

if __name__ == "__main__":
    main()
