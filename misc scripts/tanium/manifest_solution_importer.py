import argparse
import logging
import re
import time
import json
import xml.etree.ElementTree as ET
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from packaging import version
from urllib.parse import urlparse

# Default timeout for API requests in seconds
DEFAULT_TIMEOUT = 30
# Add this near the top of the script with other constants
SEPARATOR = "=" * 60  # You can adjust the number 60 to your preferred length
# Suppress InsecureRequestWarning since SSL verification is disabled
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# K/V to map unknown workbenches to known solutions
MANUAL_WORKBENCH_TO_SOLUTION_MAPPING = {
    "screen sharing solution": "screen sharing",
}


# 1. Utility Functions
def normalize_name(name):
    """Normalizes the solution name by converting it to lowercase and removing known prefixes."""
    prefixes = ["tanium "]
    normalized = name.lower().strip()
    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
    logging.debug(f"Normalized name: {normalized}")
    return normalized


def build_headers(session_token, content_type=None, additional_headers=None):
    """Builds the HTTP headers for API requests."""
    headers = {"session": session_token}
    if content_type:
        headers["Content-Type"] = content_type
    if additional_headers:
        headers.update(additional_headers)
    return headers


def is_valid_url(url: str) -> bool:
    """Validates the given URL."""
    parsed = urlparse(url)
    return all([parsed.scheme, parsed.netloc])


# 2. Configuration and Setup Functions
def parse_arguments():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(description="Tanium Solution Updater")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Path to the log file (default: None, logs to console)",
    )
    parser.add_argument(
        "--timeout", type=int, default=30, help="Timeout for API requests in seconds"
    )
    parser.add_argument(
        "--available-solutions-xml-url",
        default=None,
        help="URL to the available solutions XML file",
    )
    return parser.parse_args()


def setup_logging(log_level, log_file):
    """Sets up the logging configuration."""
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    handlers = []
    if log_file:
        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5)
        handlers.append(handler)
    else:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=numeric_level,
                        format=log_format, handlers=handlers)


def load_env_vars(filename):
    """Loads environment variables from a specified file."""
    env_vars = {}
    try:
        with open(filename, "r") as env_file:
            for line in env_file:
                match = re.match(r"^\s*([\w]+)\s*=\s*(.+?)\s*$", line)
                if match:
                    key, value = match.groups()
                    env_vars[key] = value.strip().strip('"').strip("'")
        logging.debug(f"Loaded environment variables: {env_vars}")
    except FileNotFoundError:
        logging.error(f"Environment file '{filename}' not found.")
        exit(1)
    required_vars = ["TANIUM_USERNAME", "TANIUM_PASSWORD", "TANIUM_BASE_URL"]
    for var in required_vars:
        if var not in env_vars or not env_vars[var]:
            logging.error(f"Required environment variable '{var}' is missing.")
            exit(1)
    return env_vars


# 3. Session and Authentication Functions
def create_session():
    """Creates and configures a requests session with retry strategy."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.verify = False
    return session


def login_to_api(session, api_login_url, username, password):
    """Logs into the Tanium API and retrieves the session token."""
    logging.debug(f"Logging in to API at: {
                  api_login_url} with username: {username}")
    try:
        response = session.post(
            api_login_url, json={"username": username, "password": password}
        )
        response.raise_for_status()
        session_token = response.json().get("data", {}).get("session")
        if not session_token:
            raise ValueError(
                "Session token not obtained. Check your credentials.")
        return session_token
    except requests.RequestException as e:
        logging.error(f"Failed to login to API: {e}")
        raise


def validate_session(session, api_validate_url, session_token):
    """Validates the current session token with the Tanium API."""
    logging.debug(f"Validating session token at: {api_validate_url}")
    try:
        response = session.post(api_validate_url, json={
                                "session": session_token})
        response.raise_for_status()
        logging.debug("Session token validated successfully.")
        return True
    except requests.RequestException as e:
        logging.error(f"Session token validation failed: {e}")
        raise


# 4. Data Retrieval Functions
def fetch_manifest_url(session, server_api_base_url, session_token):
    """
    Fetches the manifestURL from the Tanium server's local settings.
    If it fails, it attempts to fetch console_manifestURL from global settings.
    """
    headers = build_headers(session_token, content_type="application/json")

    # Try to fetch manifestURL from local settings
    local_settings_url = f"{server_api_base_url}/local_settings"
    logging.debug(f"Fetching local settings from: {local_settings_url}")
    try:
        response = session.get(
            local_settings_url, headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json().get("data", [])
        for item in data:
            if item.get("name") == "manifestURL":
                manifest_url = item.get("value")
                if manifest_url and is_valid_url(manifest_url):
                    logging.debug(
                        f"Retrieved manifestURL from local settings: {manifest_url}")
                    return manifest_url
        logging.warning(
            "manifestURL not found in local settings. Trying global settings...")
    except requests.RequestException as e:
        logging.error(f"Failed to fetch local settings from server: {e}")
        logging.warning("Falling back to global settings...")

    # Fallback to fetching console_manifestURL from global settings
    global_settings_url = f"{server_api_base_url}/system_settings"
    logging.debug(f"Fetching global settings from: {global_settings_url}")
    try:
        response = session.get(global_settings_url,
                               headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json().get("data", [])
        for item in data:
            if item.get("name") == "console_manifestURL":
                manifest_url = item.get("value")
                if manifest_url and is_valid_url(manifest_url):
                    logging.debug(
                        f"Retrieved console_manifestURL from global settings: {manifest_url}")
                    return manifest_url
        raise ValueError(
            "console_manifestURL not found or invalid in global settings.")
    except requests.RequestException as e:
        logging.error(f"Failed to fetch global settings from server: {e}")
        raise ValueError(
            "Failed to retrieve manifestURL from both local and global settings.")


def get_server_hosts(session, server_api_base_url, session_token):
    """Fetches the list of server hosts from the Tanium server."""
    server_host_url = f"{server_api_base_url}/server_host"
    headers = build_headers(session_token, content_type="application/json")
    logging.debug(f"Fetching server hosts from: {server_host_url}")
    try:
        response = session.get(
            server_host_url, headers=headers, timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        servers = data.get("servers", [])
        server_list = []
        for server in servers:
            name = server.get("name")
            address = server.get("address")
            if name and address:
                parsed = urlparse(address)
                if not parsed.scheme:
                    address = f"https://{address}"
                if is_valid_url(address):
                    server_list.append({"name": name, "address": address})
                else:
                    logging.warning(
                        f"Invalid server entry found and skipped: {server}")
        logging.info(f"Total valid servers fetched: {len(server_list)}")
        return server_list
    except requests.RequestException as e:
        logging.error(f"Failed to fetch server hosts: {e}")
        raise


def get_available_solutions(available_solutions_url, session):
    """Retrieves available solutions from the specified XML URL."""
    logging.debug(f"Fetching XML from URL: {available_solutions_url}")
    try:
        response = session.get(available_solutions_url,
                               timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        xml_content = response.content
        solutions = parse_solutions_xml(xml_content)
        logging.debug(f"Total solutions parsed: {len(solutions)}")
        return solutions
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching available solutions: {e}")
        raise


def parse_solutions_xml(xml_content):
    """Parses the solutions XML content and extracts solution details."""
    solutions = {}
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logging.error(f"Failed to parse XML: {e}")
        raise
    for solution_elem in root.findall("./solution"):
        solution = {
            "id": solution_elem.findtext("id"),
            "name": solution_elem.findtext("name"),
            "version": solution_elem.findtext("version"),
            "content_url": solution_elem.findtext("content_url"),
        }
        logging.debug(f"Parsed solution: {solution}")
        if not all(solution.values()):
            logging.warning(f"Incomplete solution data: {solution}")
            continue
        normalized_name = normalize_name(solution["name"])
        key = (normalized_name, solution["id"])
        solutions[key] = solution
    return solutions


def get_installed_solutions(api_url, session, session_token):
    """Retrieves the list of installed solutions from the Tanium server."""
    logging.debug(f"Retrieving installed solutions from API: {api_url}")
    headers = build_headers(session_token, content_type="application/json")
    try:
        response = session.get(api_url, headers=headers,
                               timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        server_info = response.json()
        installed_solutions = {}
        installed_solutions_data = (
            server_info.get("data", {})
            .get("Diagnostics", {})
            .get("Installed_Solutions", {})
        )
        for sol_key, sol in installed_solutions_data.items():
            name = sol.get("name", sol_key)
            normalized_name = normalize_name(name)
            solution = {
                "id": sol.get("id"),
                "name": name,
                "version": sol.get("version"),
                "last_updated": sol.get("last_updated"),
                "installed_xml_url": sol.get("installed_xml_url"),
            }
            logging.debug(f"Retrieved installed solution: {solution}")
            key = (normalized_name, solution["id"])
            installed_solutions[key] = solution
        logging.debug(
            f"Total installed solutions retrieved: {len(installed_solutions)}"
        )
        return installed_solutions
    except requests.exceptions.RequestException as e:
        logging.error(f"Error retrieving installed solutions: {e}")
        raise


def get_installed_workbenches(api_url, session, session_token):
    """Retrieves the list of installed workbenches from the Tanium server."""
    logging.debug(f"Retrieving installed workbenches from API: {api_url}")
    headers = build_headers(session_token, content_type="application/json")
    try:
        response = session.get(api_url, headers=headers,
                               timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        server_info = response.json()
        installed_workbenches = {}
        installed_workbenches_data = (
            server_info.get("data", {})
            .get("Diagnostics", {})
            .get("Installed_Workbenches", {})
        )
        for sol_key, sol in installed_workbenches_data.items():
            name = normalize_name(sol.get("name", sol_key))
            workbench = {
                "version": sol.get("version"),
                "last_updated": sol.get("last_updated"),
            }
            logging.debug(f"Retrieved installed workbench: {workbench}")
            installed_workbenches[name] = workbench
        logging.debug(
            f"Total installed workbenches retrieved: {
                len(installed_workbenches)}"
        )
        return installed_workbenches
    except requests.exceptions.RequestException as e:
        logging.error(f"Error retrieving installed workbenches: {e}")
        raise


# 5. Processing and Update Functions
def compare_versions(version1, version2):
    """Compares two version strings."""
    try:
        return version.parse(version1) < version.parse(version2)
    except Exception as e:
        logging.error(f"Error parsing versions: {e}")
        return False


def needs_update(installed_solution, available_solution):
    """Determines if a solution needs an update."""
    installed_version = installed_solution.get("version", "")
    available_version = available_solution.get("version", "")

    if not installed_version:
        logging.warning(
            f"Installed version is empty. Will update to {available_version}"
        )
        return True

    return compare_versions(installed_version, available_version)


def download_content(content_url, session):
    """Downloads content from a given URL."""
    if not content_url:
        raise ValueError("Content URL is empty.")
    logging.debug(f"Downloading content from URL: {content_url}")
    response = session.get(content_url, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    logging.debug(f"Content downloaded successfully from {content_url}")
    return response.content


def analyze_import_conflicts(api_base_url, session, content, session_token):
    """Analyzes import conflicts by posting the content to the Tanium API."""
    import_url = f"{api_base_url}/import?import_analyze_conflicts_only=1"
    headers = build_headers(
        session_token, content_type="application/octet-stream")

    logging.debug(
        f"Posting content to API for conflict analysis at {import_url}")
    response = session.post(
        import_url, data=content, headers=headers, timeout=DEFAULT_TIMEOUT
    )
    response.raise_for_status()

    logging.debug(f"Conflict analysis response status code: {
                  response.status_code}")
    return parse_import_conflicts(response.json())


def parse_import_conflicts(response_data):
    """Parses the import conflicts from the API response."""
    conflicts = (
        response_data.get("data", {})
        .get("object_list", {})
        .get("import_conflict_details", [])
    )
    import_conflicts = {}

    for conflict in conflicts:
        conflict_type = conflict.get("type")
        if conflict_type not in import_conflicts:
            import_conflicts[conflict_type] = []
        import_conflicts[conflict_type].append(conflict)

    logging.debug(
        f"Total import conflicts parsed: {
            sum(len(v) for v in import_conflicts.values())}"
    )
    return import_conflicts


def build_import_conflict_options(import_conflicts):
    """Builds the import conflict options by setting overwrite for all conflict types."""
    option_value = 1
    import_conflict_options = {}
    for conflict_type, conflicts in import_conflicts.items():
        conflict_type_plural = (
            conflict_type +
            "s" if not conflict_type.endswith("s") else conflict_type
        )
        import_conflict_options[conflict_type_plural] = [
            option_value] * len(conflicts)
    logging.debug(f"Built import conflict options: {import_conflict_options}")
    return import_conflict_options


def initiate_import(
    api_base_url, session, content, import_conflict_options, session_token
):
    """Initiates the import process for the solution content."""
    import_url = f"{api_base_url}/import"
    tanium_options = json.dumps(
        {"import_conflict_options": import_conflict_options})
    headers = build_headers(
        session_token,
        content_type="application/octet-stream",
        additional_headers={
            "Prefer": "respond-async",
            "tanium-options": tanium_options,
        },
    )

    logging.debug(
        f"Initiating import process with headers: {
            headers} and conflict options: {import_conflict_options}"
    )
    response = session.post(
        import_url, data=content, headers=headers, timeout=DEFAULT_TIMEOUT
    )

    if response.status_code == 202:
        import_id = response.json().get("data", {}).get("id")
        logging.info(f"Import successfully initiated with ID: {import_id}")
        return import_id
    else:
        logging.error(f"Failed to initiate import. Status code: {
                      response.status_code}")
        logging.error(f"Response content: {response.text}")
        return None


def check_import_status(api_base_url, session, import_id, session_token):
    """Checks the status of the import process."""
    import_status_url = f"{api_base_url}/import/{import_id}"
    headers = build_headers(session_token)

    response = session.get(
        import_status_url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()

    import_status = response.json().get("data", {})
    success = import_status.get("success")

    if success is True:
        logging.info(f"Import completed successfully for ID: {import_id}")
        return True
    elif success is False:
        logging.error(f"Import failed for ID: {import_id}")
        result = import_status.get("result")
        logging.error(f"Import result: {result}")
        return False
    else:
        logging.debug(f"Import is still in progress for ID: {import_id}")
        return None


def analyze_solution_conflicts(api_base_url, session, content, session_token):
    """Analyzes import conflicts for the solution content."""
    import_conflicts = analyze_import_conflicts(
        api_base_url, session, content, session_token
    )
    return import_conflicts


def prepare_import_options(import_conflicts):
    """Prepares import options based on the analyzed conflicts."""
    if import_conflicts:
        return build_import_conflict_options(import_conflicts)
    return {}


def initiate_solution_import(
    api_base_url, session, content, import_conflict_options, session_token
):
    """Initiates the import process for the solution."""
    import_id = initiate_import(
        api_base_url, session, content, import_conflict_options, session_token
    )
    return import_id


def wait_for_import_completion(
    api_base_url, session, import_id, session_token, max_retries=10, initial_delay=10
):
    """Waits for the import process to complete."""
    for attempt in range(1, max_retries + 1):
        status = check_import_status(
            api_base_url, session, import_id, session_token)
        if status is True:
            return True
        elif status is False:
            return False
        time.sleep(initial_delay * (2 ** (attempt - 1)))
    logging.error(f"Maximum retries reached for import ID: {import_id}")
    return False


def get_manual_mapping(workbench_name, installed_solutions):
    """Attempts to find a manual mapping for a workbench."""
    if workbench_name in MANUAL_WORKBENCH_TO_SOLUTION_MAPPING:
        mapped_solution_name = MANUAL_WORKBENCH_TO_SOLUTION_MAPPING[workbench_name]
        for (solution_name, _), solution_details in installed_solutions.items():
            if solution_name == mapped_solution_name:
                return solution_details
    return None


def match_workbench_to_solution(workbench_name, solution_name, solution_xml_url):
    """Checks if a workbench matches a solution by name or XML URL."""
    return workbench_name == solution_name or (
        solution_xml_url and workbench_name.lower() in solution_xml_url.lower()
    )


def map_workbenches_to_solutions(installed_workbenches, installed_solutions, available_solutions):
    """Maps each installed workbench to its parent solution, including available solution details."""
    workbench_solution_map = {}
    for workbench_name, workbench_details in installed_workbenches.items():
        logging.debug(f"Attempting to map workbench '{workbench_name}'")

        manual_mapping = get_manual_mapping(
            workbench_name, installed_solutions)
        if manual_mapping:
            # Get the corresponding available solution
            key = (normalize_name(
                manual_mapping['name']), manual_mapping['id'])
            available_solution = available_solutions.get(key)
            if available_solution:
                workbench_solution_map[workbench_name] = {
                    "workbench_details": workbench_details,
                    "installed_solution_details": manual_mapping,
                    "available_solution_details": available_solution,
                }
                logging.debug(
                    f"Manually mapped Workbench '{
                        workbench_name}' to Solution '{manual_mapping['name']}'"
                )
            else:
                logging.warning(
                    f"No available solution found for manual mapping of workbench '{
                        workbench_name}'"
                )
            continue

        for (solution_name, solution_id), installed_solution_details in installed_solutions.items():
            solution_xml_url = installed_solution_details.get(
                "installed_xml_url", "")
            if match_workbench_to_solution(
                workbench_name, solution_name, solution_xml_url
            ):
                # Get the corresponding available solution
                key = (solution_name, solution_id)
                available_solution_details = available_solutions.get(key)
                if available_solution_details:
                    workbench_solution_map[workbench_name] = {
                        "workbench_details": workbench_details,
                        "installed_solution_details": installed_solution_details,
                        "available_solution_details": available_solution_details,
                    }
                    logging.debug(
                        f"Matched Workbench '{
                            workbench_name}' to Solution '{solution_name}'"
                    )
                else:
                    logging.warning(
                        f"No available solution found for workbench '{
                            workbench_name}'"
                    )
                break
        else:
            logging.warning(
                f"No matching solution found for workbench: {workbench_name}."
            )

    return workbench_solution_map


def update_single_solution(api_base_url, session, solution_info, session_token):
    """Updates a single solution if needed."""
    try:
        content = download_content(solution_info["content_url"], session)
        import_conflicts = analyze_import_conflicts(
            api_base_url, session, content, session_token)
        import_conflict_options = prepare_import_options(import_conflicts)
        import_id = initiate_import(
            api_base_url, session, content, import_conflict_options, session_token)

        if import_id:
            return wait_for_import_completion(api_base_url, session, import_id, session_token)
        else:
            return False
    except Exception as e:
        logging.error(f"Error updating solution '{
                      solution_info['name']}': {e}")
        return False


def log_summary_statistics(
    servers_processed,
    solutions_checked,
    workbenches_checked,
    updates_attempted,
    updates_successful,
    updates_failed,
):
    logging.info(SEPARATOR)
    logging.info("Summary Statistics")
    logging.info(SEPARATOR)
    logging.info(f"Servers processed: {servers_processed}")
    logging.info(f"Solutions checked: {solutions_checked}")
    logging.info(f"Workbenches checked: {workbenches_checked}")
    logging.info(f"Updates attempted: {updates_attempted}")
    logging.info(f"Updates successful: {updates_successful}")
    logging.info(f"Updates failed: {updates_failed}")
    logging.info(SEPARATOR)


def main():
    args = parse_arguments()
    setup_logging(args.log_level, args.log_file)

    logging.info(SEPARATOR)
    logging.info("Starting Tanium Solution Updater")
    logging.info(f"Script Version: 1.0.0")
    logging.info(f"Log Level: {args.log_level}")
    logging.info(f"Timeout: {args.timeout} seconds")
    if args.available_solutions_xml_url:
        logging.info(f"Using custom solutions XML URL: {
                     args.available_solutions_xml_url}")
    logging.info(SEPARATOR)

    global DEFAULT_TIMEOUT
    DEFAULT_TIMEOUT = args.timeout
    env_vars = load_env_vars("tanium_creds.env")
    tanium_username = env_vars.get("TANIUM_USERNAME")
    tanium_password = env_vars.get("TANIUM_PASSWORD")
    tanium_base_url = env_vars.get("TANIUM_BASE_URL")
    available_solutions_xml_url = env_vars.get("AVAILABLE_SOLUTIONS_XML_URL")
    server_api_base_url = f"{tanium_base_url}/api/v2"
    api_login_url = f"{server_api_base_url}/session/login"
    session_validate_url = f"{server_api_base_url}/session/validate"
    session = create_session()

    # Initialize summary statistics
    servers_processed = 0
    total_solutions_checked = 0
    total_workbenches_checked = 0
    total_updates_attempted = 0
    total_updates_successful = 0
    total_updates_failed = 0

    try:
        # Authentication
        session_token = login_to_api(
            session, api_login_url, tanium_username, tanium_password)
        validate_session(session, session_validate_url, session_token)

        # Get server hosts
        server_hosts = get_server_hosts(
            session, server_api_base_url, session_token)
        if not server_hosts:
            logging.warning("No valid servers found to process.")
            return

        # Server processing loop
        for server in server_hosts:
            servers_processed += 1
            server_name = server["name"]
            server_address = server["address"]
            logging.info(SEPARATOR)
            logging.info(f"Processing server: {
                         server_name} ({server_address})")
            logging.info(SEPARATOR)
            server_api_base_url = f"{server_address}/api/v2"
            server_info_url = f"{server_api_base_url}/server_info"

            # Initialize per-server statistics
            solutions_checked = 0
            workbenches_checked = 0
            updates_attempted = 0
            updates_successful = 0
            updates_failed = 0

            try:
                # Fetch installed solutions and workbenches
                installed_solutions = get_installed_solutions(
                    server_info_url, session, session_token)
                solutions_checked = len(installed_solutions)

                installed_workbenches = get_installed_workbenches(
                    server_info_url, session, session_token)
                workbenches_checked = len(installed_workbenches)

                # Fetch available solutions
                try:
                    available_solutions_url = fetch_manifest_url(
                        session, server_api_base_url, session_token)
                except ValueError:
                    if not available_solutions_xml_url:
                        logging.error(
                            "Failed to fetch manifestURL from the server, "
                            "and AVAILABLE_SOLUTIONS_XML_URL is not set in the environment."
                        )
                        exit(1)
                    available_solutions_url = available_solutions_xml_url
                    logging.warning(f"Using fallback AVAILABLE_SOLUTIONS_XML_URL: {
                                    available_solutions_url}")

                # Process the fetched or fallback URL
                if not available_solutions_url or not is_valid_url(available_solutions_url):
                    logging.error("Invalid manifest URL provided. Exiting.")
                    exit(1)

                logging.info(f"Using manifest URL: {available_solutions_url}")
                available_solutions = get_available_solutions(
                    available_solutions_url, session)

                # Comparing and updating solutions
                for key, solution_info in available_solutions.items():
                    normalized_name, manifest_id = key
                    installed_solution = installed_solutions.get(key)
                    if installed_solution:
                        if needs_update(installed_solution, solution_info):
                            logging.info(
                                f"Updating solution '{
                                    normalized_name}' (ID: {manifest_id}) "
                                f"from version '{
                                    installed_solution.get('version')}' "
                                f"to '{solution_info['version']}'"
                            )
                            updates_attempted += 1
                            success = update_single_solution(
                                server_api_base_url,
                                session,
                                solution_info,
                                session_token,
                            )
                            if success:
                                updates_successful += 1
                                logging.info(
                                    f"Solution '{
                                        normalized_name}' (ID: {manifest_id}) updated successfully."
                                )
                            else:
                                updates_failed += 1
                                logging.error(
                                    f"Failed to update solution '{
                                        normalized_name}' (ID: {manifest_id})."
                                )
                        else:
                            logging.debug(
                                f"Solution '{
                                    normalized_name}' (ID: {manifest_id}) is already up-to-date."
                            )
                    else:
                        logging.debug(
                            f"No matching installed solution found for '{
                                normalized_name}' (ID: {manifest_id}). Ignoring."
                        )

                # Mapping workbenches to solutions
                workbench_solution_map = {}
                for workbench_name, workbench_details in installed_workbenches.items():
                    logging.debug(f"Attempting to map workbench '{
                                  workbench_name}'")

                    # Try to find a matching solution
                    matching_solution = None
                    for key, installed_solution_details in installed_solutions.items():
                        solution_name, solution_id = key
                        solution_xml_url = installed_solution_details.get(
                            "installed_xml_url", "")
                        if match_workbench_to_solution(
                            workbench_name, solution_name, solution_xml_url
                        ):
                            # Get the corresponding available solution
                            available_solution = available_solutions.get(key)
                            if available_solution:
                                workbench_solution_map[workbench_name] = {
                                    "workbench_details": workbench_details,
                                    "available_solution": available_solution,
                                }
                                matching_solution = available_solution
                                logging.debug(
                                    f"Matched Workbench '{
                                        workbench_name}' to Solution '{solution_name}'"
                                )
                                break
                    if not matching_solution:
                        logging.warning(f"No matching solution found for workbench: {
                                        workbench_name}")

                # Comparing and updating workbenches
                for workbench_name, details in workbench_solution_map.items():
                    workbench_details = details["workbench_details"]
                    available_solution = details["available_solution"]

                    if needs_update(workbench_details, available_solution):
                        logging.info(
                            f"Updating workbench '{workbench_name}' via solution '{
                                available_solution['name']}' "
                            f"from version '{
                                workbench_details.get('version')}' "
                            f"to '{available_solution['version']}'."
                        )
                        updates_attempted += 1
                        success = update_single_solution(
                            server_api_base_url,
                            session,
                            available_solution,
                            session_token,
                        )
                        if success:
                            updates_successful += 1
                            logging.info(
                                f"Workbench '{workbench_name}' updated successfully to version '{
                                    available_solution['version']}'."
                            )
                        else:
                            updates_failed += 1
                            logging.error(f"Failed to update workbench '{
                                          workbench_name}'.")
                    else:
                        logging.debug(
                            f"Workbench '{
                                workbench_name}' is already up-to-date with version '{workbench_details.get('version')}'."
                        )

            except Exception as e:
                logging.error(f"Error processing server {server_name}: {e}")

            # Update total statistics
            total_solutions_checked += solutions_checked
            total_workbenches_checked += workbenches_checked
            total_updates_attempted += updates_attempted
            total_updates_successful += updates_successful
            total_updates_failed += updates_failed

            # Log per-server summary
            logging.info(SEPARATOR)
            logging.info(f"Completed processing server: {server_name}")
            logging.info(f"Solutions checked: {solutions_checked}")
            logging.info(f"Workbenches checked: {workbenches_checked}")
            logging.info(f"Updates attempted: {updates_attempted}")
            logging.info(f"Updates successful: {updates_successful}")
            logging.info(f"Updates failed: {updates_failed}")
            logging.info(SEPARATOR)

    except Exception as e:
        logging.error(f"Error during session setup: {e}")
    finally:
        session.close()

    # Log total summary statistics
    log_summary_statistics(
        servers_processed,
        total_solutions_checked,
        total_workbenches_checked,
        total_updates_attempted,
        total_updates_successful,
        total_updates_failed,
    )


# Entry Point
if __name__ == "__main__":
    main()
