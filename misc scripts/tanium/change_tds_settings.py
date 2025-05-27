import http.client
import json
import ssl

# Define host and API token directly
host = ""  # Replace with your actual host
api_token = "token-"  # Replace with your actual API token

# Create an SSL context that ignores certificate verification
context = ssl._create_unverified_context()

# Function to create a new connection
def create_connection(host):
    return http.client.HTTPSConnection(host, context=context)

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
        "continuous_harvest_interval": {"value": "7200s"},
        "continuous_harvest_question_expiration": {"value": "7200s"},
        "max_sensors_per_question": {"value": "60"}
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

# Read and decode the response body
response_body = response.read().decode()

# Try to pretty-print the JSON response
try:
    parsed_json = json.loads(response_body)
    pretty_response = json.dumps(parsed_json, indent=4)
except json.JSONDecodeError:
    pretty_response = response_body  # Fallback if response is not valid JSON

# Print the response
print(f"Status Code: {response.status}")
print("Response Body:")
print(pretty_response)

# Close the connection
conn.close()
