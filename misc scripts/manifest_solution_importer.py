import json
import os
import requests
import xml.etree.ElementTree as ET
import time
import urllib3
import logging
from packaging import version

# Disable SSL warnings from urllib3 (useful when SSL certificate verification is disabled)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Setup basic logging to file
logging.basicConfig(
    level=logging.DEBUG,
    filename='application.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def parse_xml(xml_url):
    """Fetch and parse XML from a URL to extract solutions details."""
    logging.debug("Fetching XML from URL: %s", xml_url)
    response = requests.get(xml_url, verify=False)
    if response.status_code == 200:
        xml_data = response.text
        root = ET.fromstring(xml_data)
        solutions = []
        for solution in root.findall('.//solution'):
            solution_details = {
                'id': solution.find('id').text,
                'name': solution.find('name').text,
                'version': solution.find('version').text,
                'content_url': solution.find('content_url').text
            }
            solutions.append(solution_details)
            logging.debug("Parsed solution: %s", solution_details)
        return solutions
    else:
        logging.error("Failed to fetch or parse XML from URL: %s, Status code: %d", xml_url, response.status_code)
        raise Exception("Failed to fetch XML data")

def login_to_api(api_login_url, username, password):
    """Authenticate with the API and retrieve a session token."""
    logging.debug("Logging in to API at: %s", api_login_url)
    response = requests.post(api_login_url, json={'username': username, 'password': password}, verify=False)
    if response.status_code == 200:
        session = response.json().get('data', {}).get('session')
        logging.debug("Obtained session token: %s", session)
        return session
    else:
        logging.error("Failed to login to API, Status code: %d", response.status_code)
        raise Exception("Failed to login to API")

def validate_session(api_validate_url, session_token):
    """Check if the provided session token is still valid."""
    logging.debug("Validating session token at: %s", api_validate_url)
    response = requests.post(api_validate_url, json={'session': session_token}, verify=False)
    if response.status_code == 200:
        logging.debug("Session token validated successfully")
        return True
    else:
        logging.error("Session token validation failed, Status code: %d", response.status_code)
        return False

def get_server_details(api_url, headers):
    """Retrieve server details including name and address."""
    logging.debug("Retrieving server details from API: %s", api_url)
    response = requests.get(api_url, headers=headers, verify=False)
    if response.status_code == 200:
        servers = response.json().get('data', {}).get('servers', [])
        server_list = [{'name': server['name'], 'address': server['address']} for server in servers]
        logging.debug("Retrieved server details: %s", server_list)
        return server_list
    else:
        logging.error("Failed to fetch server details, Status code: %d", response.status_code)
        raise Exception("Failed to fetch server details")

def normalize_name(name):
    """Normalize solution names by removing known prefixes and replacing underscores."""
    original_name = name
    name = name.replace('_', ' ')
    prefixes = ['Tanium ']
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
    normalized_name = name.strip()
    logging.debug("Normalized name from '%s' to '%s'", original_name, normalized_name)
    return normalized_name

def get_installed_solutions(api_url, headers):
    """Retrieve details of installed solutions from the server."""
    logging.debug("Retrieving installed solutions from API: %s", api_url)
    response = requests.get(api_url, headers=headers, verify=False)
    if response.status_code == 200:
        data = response.json().get('data', {}).get('Diagnostics', {}).get('Installed_Solutions', {})
        installed_solutions = {}
        for details in data.values():
            normalized_name = normalize_name(details['name'])
            solution_details = {
                'id': details['id'],
                'version': details['version'],
                'last_updated': details['last_updated']
            }
            installed_solutions[normalized_name] = solution_details
            logging.debug("Retrieved installed solution: %s", solution_details)
        return installed_solutions
    else:
        logging.error("Failed to fetch installed solutions details, Status code: %d", response.status_code)
        raise Exception("Failed to fetch installed solutions details")

def get_installed_workbenches(api_url, headers):
    """Retrieve details of installed workbenches from the server."""
    logging.debug("Retrieving installed workbenches from API: %s", api_url)
    response = requests.get(api_url, headers=headers, verify=False)
    if response.status_code == 200:
        data = response.json().get('data', {}).get('Diagnostics', {}).get('Installed_Workbenches', {})
        installed_workbenches = {}
        for name, details in data.items():
            normalized_name = normalize_name(name)
            workbench_details = {
                'version': details['version'],
                'last_updated': details['last_updated']
            }
            installed_workbenches[normalized_name] = workbench_details
            logging.debug("Retrieved installed workbench: %s", workbench_details)
        return installed_workbenches
    else:
        logging.error("Failed to fetch installed workbenches details, Status code: %d", response.status_code)
        raise Exception("Failed to fetch installed workbenches details")

def download_content(content_url):
    """Download content from the specified URL."""
    logging.debug("Downloading content from URL: %s", content_url)
    response = requests.get(content_url, verify=False)
    if response.status_code == 200:
        logging.debug("Content downloaded successfully: %s", response.content)
        return response.content
    else:
        logging.error("Failed to download content from URL: %s, Status code: %d", content_url, response.status_code)
        raise Exception(f"Failed to download content from URL: {content_url}")

def get_import_conflict_details(api_import_url, headers, content):
    """Post content to the API and retrieve any import conflicts."""
    logging.debug("Posting content to API for conflict check: %s", api_import_url)
    response = requests.post(api_import_url, headers=headers, data=content, verify=False)
    if response.status_code in (200, 202):
        response_data = response.json().get('data', {})
        object_list = response_data.get('object_list', {})
        import_conflict_details = object_list.get('import_conflict_details', [])
        conflicts = {}
        for conflict in import_conflict_details:
            conflict_type = conflict.get('type')
            conflict_name = conflict.get('name')
            if conflict_type in conflicts:
                conflicts[conflict_type].append(conflict_name)
            else:
                conflicts[conflict_type] = [conflict_name]
        logging.debug("Retrieved import conflict details: %s", conflicts)
        return conflicts
    else:
        logging.error("Failed to get import conflict details, Status code: %d", response.status_code)
        raise Exception(f"Failed to get import conflict details: Unexpected response status code {response.status_code}")

def build_import_conflict_options(import_conflicts):
    """Build options to resolve identified import conflicts based on the API's conflict reports."""
    import_conflict_options = {}
    for conflict_type, conflicts in import_conflicts.items():
        if not conflict_type.endswith('s'):
            conflict_type_plural = conflict_type + 's'
        else:
            conflict_type_plural = conflict_type
        import_conflict_options[conflict_type_plural] = [1] * len(conflicts)
    logging.debug("Built import conflict options: %s", import_conflict_options)
    return import_conflict_options

def initiate_import(api_url, headers, content, import_conflict_options=None, max_retries=6):
    """Initiate the import process with the specified content and conflict resolution options, with retry logic."""
    headers['Prefer'] = 'respond-async'
    headers['tanium-options'] = json.dumps({"import_conflict_options": import_conflict_options})
    logging.debug("Headers set for import: %s", headers)
    attempt = 0
    while attempt < max_retries:
        logging.debug("Type of content: %s", type(content))
        logging.debug("Content: %s", content)
        response = requests.post(api_url, headers=headers, data=content, verify=False)
        if response.status_code in (200, 202):
            logging.debug("Import initiated successfully: %s", response.json())
            return response
        elif response.status_code == 409:
            attempt += 1
            logging.warning("Attempt %d: Server is still processing the previous import. Retrying...", attempt)
            time.sleep(10)
        else:
            logging.error("Failed to initiate import: %s, Status code: %d", response.text, response.status_code)
            raise Exception(f"Failed to initiate import: Unexpected response status code {response.status_code}")
    logging.error("Failed to initiate import after %d retries due to ongoing server processing.", max_retries)
    raise Exception("Failed to initiate import after multiple retries due to ongoing server processing.")

def check_and_report_import_status(api_url, headers, import_id):
    """Monitor and report the status of an ongoing import operation."""
    logging.debug("Starting import status check for ID: %s", import_id)
    start_time = time.time()
    success = None
    while time.time() - start_time < 600:
        logging.debug("Checking Import Status for import ID: %s", import_id)
        response = requests.get(f"{api_url}/{import_id}", headers=headers, verify=False)
        if response.status_code in (200, 202):
            response_data = response.json().get('data', {})
            success = response_data.get('success')
            status_text = response_data.get('status', 'Unknown')
            if success is not None:
                if success:
                    logging.info("Import successful for ID: %s", import_id)
                    break
                else:
                    logging.warning("Import failed for ID: %s, Status: %s", import_id, status_text)
                    break
            else:
                logging.debug("Import Status for ID: %s: %s", import_id, status_text)
            time.sleep(30)
        else:
            logging.error("Failed to check import status for ID: %s: HTTP status code %d", import_id, response.status_code)
            break
    if success is None or not success:
        logging.error("Import status check timed out or failed without a clear success message for ID: %s", import_id)
    return success

# Main script execution starts here
base_url = os.environ.get('TANIUM_BASE_URL')
if not base_url:
    print("Error: 'TANIUM_BASE_URL' environment variable is not set.")
    exit(1)
api_login_url = f'https://{base_url}/api/v2/session/login'
api_validate_url = f'https://{base_url}/api/v2/session/validate'
api_server_host_url = f'https://{base_url}/api/v2/server_host'
api_token = os.environ.get('API_TOKEN')
if api_token:
    session_token = api_token
else:
    username = os.environ.get('API_USERNAME')
    if not username:
        print("Error: 'API_USERNAME' environment variable is not set.")
        exit(1)
    password = os.environ.get('API_PASSWORD')
    if not password:
        print("Error: 'API_PASSWORD' environment variable is not set.")
        exit(1)
    session_token = login_to_api(api_login_url, username, password)
    if not session_token:
        print("Failed to log in or obtain session token.")
        exit(1)
    if not validate_session(api_validate_url, session_token):
        print("Session token is not valid.")
        exit(1)
headers = {'session': session_token}
ring_urls = {
    'dev': os.getenv('TANIUM_RING_DEV', 'default_dev_url'),
    'test': os.getenv('TANIUM_RING_TEST', 'default_test_url'),
    'canary': os.getenv('TANIUM_RING_CANARY', 'default_canary_url'),
    'ea': os.getenv('TANIUM_RING_EA', 'default_ea_url'),
    'ga': os.getenv('TANIUM_RING_GA', 'default_ga_url')
}
ring_type = os.environ.get('RING_TYPE', 'canary')
xml_url = ring_urls[ring_type]
xml_solutions = parse_xml(xml_url)
server_details = get_server_details(api_server_host_url, headers)
for server in server_details:
    print(f"Checking for updates on {server['name']} at {server['address']}")
    server_api_base_url = f"https://{server['address']}"
    server_info_url = f"{server_api_base_url}/api/v2/server_info"
    installed_solutions = get_installed_solutions(server_info_url, headers)
    installed_workbenches = get_installed_workbenches(server_info_url, headers)
    no_updates_required = []
    for xml_solution in xml_solutions:
        solution_name = normalize_name(xml_solution['name'])
        installed_version = installed_solutions.get(solution_name, {}).get('version')
        workbench_version = installed_workbenches.get(solution_name, {}).get('version')
        needs_update = installed_version and version.parse(xml_solution['version']) > version.parse(installed_version)
        workbench_needs_update = workbench_version and version.parse(xml_solution['version']) > version.parse(workbench_version)
        if needs_update or workbench_needs_update:
            print(f"Update required for {solution_name}. Solution version: {installed_version}, Workbench version: {workbench_version}, XML version: {xml_solution['version']}")
            content_url = xml_solution['content_url']
            content = download_content(content_url)
            import_conflicts = get_import_conflict_details(server_api_base_url + '/api/v2/import', headers, content)
            import_conflict_options = build_import_conflict_options(import_conflicts)
            response = initiate_import(server_api_base_url + '/api/v2/import', headers, content, import_conflict_options)
            if response.status_code in (200,202):
                import_id = response.json().get("data", {}).get("id")
                if not check_and_report_import_status(server_api_base_url + '/api/v2/import', headers, import_id):
                    print(f"Update for {solution_name} failed after retry.")
        else:
            no_updates_required.append(solution_name)
    if no_updates_required:
        print(f"No updates required on {server['name']} for {', '.join(no_updates_required)}")
