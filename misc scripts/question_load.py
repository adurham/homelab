import json
import re
import http.client
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Function to parse date input
def parse_date(date_str):
    return datetime.strptime(date_str, '%m/%d/%Y, %I:%M:%S %p')

# Prompt the user for the file path and date
file_path = input("Please enter the path to the JSON file: ")
date_str = input("Please enter the date (e.g., 6/14/2024, 11:46:38 AM): ")
logging.debug(f"File path: {file_path}, Date: {date_str}")

# Parse the user-provided date
user_date = parse_date(date_str)
logging.debug(f"Parsed user date: {user_date}")

# Read the JSON data from the file
with open(file_path, 'r') as file:
    data = json.load(file)

# Extract and filter query_text fields based on expiration date and user
query_texts = []
time_window = timedelta(minutes=2)
for item in data['object_list']['question_history']:
    expiration = datetime.strptime(item.get('expiration', ''), '%Y-%m-%dT%H:%M:%SZ')
    user_name = item.get('user', {}).get('name', '')
    if abs(expiration - user_date) <= time_window and user_name == "Tanium Data":
        query_text = item.get('query_text', 'No query_text found')
        # Replace the substring from Get? to the next space with just Get
        modified_query_text = re.sub(r'Get\?.*?\s', 'Get ', query_text)
        query_texts.append(modified_query_text)
logging.debug(f"Filtered query texts: {query_texts}")

# Placeholder for the URL and headers for the API call
api_host = "tanium.lab.amd-e.com"
api_path = "/api/v2/questions"
headers = {
    'Content-Type': 'application/json',
    'session': 'token-'  # Add your authorization token here if needed
}
logging.debug(f"API Host: {api_host}, API Path: {api_path}, Headers: {headers}")

# Function to make the API call
def make_api_call(index, total, query_text):
    payload = json.dumps({
        "query_text": query_text
    })
    logging.debug(f"Payload for #{index}: {payload}")

    conn = http.client.HTTPSConnection(api_host)
    # Convert headers to a format suitable for HTTPConnection
    formatted_headers = {key: value for key, value in headers.items()}

    # Make the actual API call
    conn.request("POST", api_path, body=payload, headers=formatted_headers)
    response = conn.getresponse()
    response_data = response.read().decode()

    # Check and print the response status and body
    if response.status == 200:
        logging.debug(f"Making API call for #{index} out of {total}: Successfully made API call")
    else:
        logging.debug(f"Making API call for #{index} out of {total}: Failed to make API call, Status code: {response.status}")
    conn.close()

# Function to execute API calls in parallel
def execute_api_calls_in_parallel(query_texts, max_workers=10):
    total = len(query_texts)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_query = {
            executor.submit(make_api_call, index+1, total, query_text): query_text
            for index, query_text in enumerate(query_texts)
        }
        for future in as_completed(future_to_query):
            future.result()  # Ensure all exceptions are raised and handled

# Execute API calls in parallel with 10 threads
execute_api_calls_in_parallel(query_texts, max_workers=10)
