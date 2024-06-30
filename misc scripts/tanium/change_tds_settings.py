import http.client
import json
import ssl

# Create an SSL context that ignores certificate verification
context = ssl._create_unverified_context()

# Function to create a new connection
def create_connection(host):
    return http.client.HTTPSConnection(host, context=context)

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
env_vars = load_env_vars('tanium_creds.env')


# URL details
host = env_vars.get("HOST")
api_token = env_vars.get("API_TOKEN")

# Headers including the API token
headers = {
    "session": f"{api_token}",
    "Content-Type": "application/json"
}

# Define the path
path = "/plugin/products/core-data/v1/settings"

# Define the JSON body
payload = {
    "harvest": {
        "continuous_harvest_interval": {"value": "14400s"},
        "continuous_harvest_question_expiration": {"value": "1800s"}
    }
}

# Convert the payload to a JSON string
json_payload = json.dumps(payload)

# Create a connection
conn = create_connection(host)

# Send the PATCH request
conn.request("PATCH", path, body=json_payload, headers=headers)

# Get the response
response = conn.getresponse()

# Read the response body
response_body = response.read().decode()

# Print the response
print(f"Status Code: {response.status}")
print(f"Response Body: {response_body}")

# Close the connection
conn.close()
