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

# Suppress InsecureRequestWarning since SSL verification is disabled
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# 1. Utility Functions

def normalize_name(name):
    """
    Normalizes the solution name by converting it to lowercase and removing the 'tanium ' prefix.

    Args:
        name (str): The original solution name.

    Returns:
        str: The normalized solution name.
    """
    normalized_name = name.lower().replace("tanium ", "").strip()
    logging.debug(f"Normalized name from '{name}' to '{normalized_name}'")
    return normalized_name


def build_headers(session_token, content_type=None, additional_headers=None):
    """
    Builds the HTTP headers for API requests.

    Args:
        session_token (str): The authenticated session token.
        content_type (str, optional): The Content-Type header value.
        additional_headers (dict, optional): Any additional headers to include.

    Returns:
        dict: The constructed headers.
    """
    headers = {
        "session": session_token,
    }
    if content_type:
        headers["Content-Type"] = content_type
    if additional_headers:
        headers.update(additional_headers)
    return headers


def is_valid_url(url: str) -> bool:
    """
    Validates the given URL.

    Args:
        url (str): The URL to validate.

    Returns:
        bool: True if URL is valid, False otherwise.
    """
    parsed = urlparse(url)
    return all([parsed.scheme, parsed.netloc])


# 2. Configuration and Setup Functions

def parse_arguments():
    """
    Parses command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments including log level, log file path, timeout, and available solutions XML URL.
    """
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
        "--timeout",
        type=int,
        default=30,
        help="Timeout for API requests in seconds",
    )
    parser.add_argument(
        "--available-solutions-xml-url",
        default=None,
        help=(
            "URL to the available solutions XML file. "
            "If not provided, the script will fetch it from the Tanium server's local settings."
        ),
    )
    return parser.parse_args()


def setup_logging(log_level, log_file):
    """
    Sets up the logging configuration.

    Args:
        log_level (str): The logging level (e.g., DEBUG, INFO).
        log_file (str or None): The path to the log file. If None, logs to console.
    """
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    handlers = []
    if log_file:
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5)
        handlers.append(handler)
    else:
        handlers.append(logging.StreamHandler())
    
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        handlers=handlers
    )


def load_env_vars(filename):
    """
    Loads environment variables from a specified file.

    Args:
        filename (str): The path to the environment variables file.

    Returns:
        dict: A dictionary of loaded environment variables.

    Exits:
        If the environment file is not found or required variables are missing.
    """
    env_vars = {}
    try:
        logging.debug(f"Loading environment variables from file: {filename}")
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
    required_vars = [
        "TANIUM_USERNAME",
        "TANIUM_PASSWORD",
        "TANIUM_BASE_URL",
    ]
    for var in required_vars:
        if var not in env_vars or not env_vars[var]:
            logging.error(f"Required environment variable '{var}' is missing.")
            exit(1)
    return env_vars


# 3. Session and Authentication Functions

def create_session():
    """
    Creates and configures a requests session with retry strategy.

    Returns:
        requests.Session: The configured HTTP session.
    """
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
    session.verify = False  # SSL verification is disabled as per your requirement
    return session


def login_to_api(session, api_login_url, username, password):
    """
    Logs into the Tanium API and retrieves the session token.

    Args:
        session (requests.Session): The HTTP session.
        api_login_url (str): The API login endpoint.
        username (str): Tanium username.
        password (str): Tanium password.

    Returns:
        str: The authenticated session token.

    Raises:
        ValueError: If the session token is not found in the response.
        requests.RequestException: If the API request fails.
    """
    logging.debug(f"Logging in to API at: {api_login_url} with username: {username}")
    try:
        response = session.post(
            api_login_url,
            json={"username": username, "password": password},
        )
        logging.debug(f"Login response status code: {response.status_code}")
        response.raise_for_status()
        session_token = response.json().get("data", {}).get("session")
        logging.debug(f"Obtained session token: {session_token}")
        if not session_token:
            logging.error("Login failed: Session token not found in response.")
            raise ValueError("Session token not obtained. Check your credentials.")
        return session_token
    except requests.RequestException as e:
        logging.error(f"Failed to login to API: {e}")
        raise


def validate_session(session, api_validate_url, session_token):
    """
    Validates the current session token with the Tanium API.

    Args:
        session (requests.Session): The HTTP session.
        api_validate_url (str): The API session validation endpoint.
        session_token (str): The authenticated session token.

    Returns:
        bool: True if the session is valid.

    Raises:
        requests.RequestException: If the API request fails.
    """
    logging.debug(f"Validating session token at: {api_validate_url}")
    try:
        response = session.post(
            api_validate_url,
            json={"session": session_token},
        )
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

    Args:
        session (requests.Session): The HTTP session.
        server_api_base_url (str): The base URL for the Tanium API.
        session_token (str): The authenticated session token.

    Returns:
        str: The manifestURL if found.

    Raises:
        ValueError: If manifestURL is not found or is invalid in the response.
        requests.RequestException: If the API request fails.
    """
    local_settings_url = f"{server_api_base_url}/local_settings"
    headers = build_headers(session_token, content_type="application/json")
    logging.debug(f"Fetching local settings from: {local_settings_url}")
    try:
        response = session.get(local_settings_url, headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json().get("data", [])
        for item in data:
            if item.get("name") == "manifestURL":
                manifest_url = item.get("value")
                if manifest_url and is_valid_url(manifest_url):
                    logging.debug(f"Retrieved manifestURL from server: {manifest_url}")
                    return manifest_url
                else:
                    logging.error("manifestURL value is empty or invalid in local settings.")
                    raise ValueError("manifestURL value is empty or invalid in local settings.")
        logging.error("manifestURL not found in local settings.")
        raise ValueError("manifestURL not found in local settings.")
    except requests.RequestException as e:
        logging.error(f"Failed to fetch local settings from server: {e}")
        raise


def get_server_hosts(session, server_api_base_url, session_token):
    """
    Fetches the list of server hosts from the Tanium server.

    Args:
        session (requests.Session): The HTTP session.
        server_api_base_url (str): The base URL for the Tanium API.
        session_token (str): The authenticated session token.

    Returns:
        list of dict: A list containing server details with 'name' and 'address'.

    Raises:
        requests.RequestException: If the API request fails.
    """
    server_host_url = f"{server_api_base_url}/server_host"
    headers = build_headers(session_token, content_type="application/json")
    logging.debug(f"Fetching server hosts from: {server_host_url}")
    try:
        response = session.get(server_host_url, headers=headers, timeout=DEFAULT_TIMEOUT)
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
                    logging.debug(f"Added default scheme to address: {address}")
                if is_valid_url(address):
                    server_list.append({"name": name, "address": address})
                    logging.debug(f"Added server: Name={name}, Address={address}")
                else:
                    logging.warning(f"Invalid server entry found and skipped after modification: {server}")
            else:
                logging.warning(f"Invalid server entry found and skipped: {server}")
        logging.info(f"Total valid servers fetched: {len(server_list)}")
        return server_list
    except requests.RequestException as e:
        logging.error(f"Failed to fetch server hosts: {e}")
        raise


def get_available_solutions(available_solutions_url, session):
    """
    Retrieves available solutions from the specified XML URL.

    Args:
        available_solutions_url (str): The URL to fetch the solutions XML.
        session (requests.Session): The HTTP session.

    Returns:
        dict: A dictionary of available solutions.
    
    Raises:
        requests.RequestException: If the API request fails.
    """
    logging.debug(f"Fetching XML from URL: {available_solutions_url}")
    try:
        response = session.get(available_solutions_url, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        xml_content = response.content
        solutions = parse_solutions_xml(xml_content)
        logging.debug(f"Total solutions parsed: {len(solutions)}")
        return solutions
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching available solutions: {e}")
        raise


def parse_solutions_xml(xml_content):
    """
    Parses the solutions XML content and extracts solution details.

    Args:
        xml_content (bytes): The XML content as bytes.

    Returns:
        dict: A dictionary of parsed solutions keyed by their normalized names and IDs.

    Raises:
        ET.ParseError: If the XML content is malformed.
    """
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
    """
    Retrieves the list of installed solutions from the Tanium server.

    Args:
        api_url (str): The API endpoint to retrieve server information.
        session (requests.Session): The HTTP session.
        session_token (str): The authenticated session token.

    Returns:
        dict: A dictionary of installed solutions keyed by their normalized names and IDs.

    Raises:
        requests.RequestException: If the API request fails.
    """
    logging.debug(f"Retrieving installed solutions from API: {api_url}")
    headers = build_headers(session_token, content_type="application/json")
    try:
        response = session.get(api_url, headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        logging.debug(
            f"Installed solutions response status code: {response.status_code}"
        )
        server_info = response.json()
        installed_solutions = {}
        installed_solutions_data = (
            server_info.get("data", {})
            .get("Diagnostics", {})
            .get("Installed_Solutions", {})
        )
        for sol_key, sol in installed_solutions_data.items():
            name = normalize_name(sol.get("name", sol_key))
            solution = {
                "id": sol.get("id"),
                "version": sol.get("version"),
                "last_updated": sol.get("last_updated"),
            }
            logging.debug(f"Retrieved installed solution: {solution}")
            key = (name, solution["id"])
            installed_solutions[key] = solution
        logging.debug(
            f"Total installed solutions retrieved: {len(installed_solutions)}"
        )
        return installed_solutions
    except requests.exceptions.RequestException as e:
        logging.error(f"Error retrieving installed solutions: {e}")
        raise


# 5. Processing and Update Functions

def update_solutions(
    api_base_url, session, available_solutions, installed_solutions, session_token
):
    """
    Compares available and installed solutions and updates them if necessary.

    Args:
        api_base_url (str): The base URL for the Tanium API.
        session (requests.Session): The HTTP session.
        available_solutions (dict): Available solutions from the XML manifest.
        installed_solutions (dict): Installed solutions on the server.
        session_token (str): The authenticated session token.
    """
    for key, solution_info in available_solutions.items():
        normalized_name, manifest_id = key
        installed_solution = installed_solutions.get(key)
        if installed_solution:
            installed_version = installed_solution.get("version")
            available_version = solution_info["version"]
            if version.parse(installed_version) < version.parse(available_version):
                logging.info(
                    f"Updating solution '{normalized_name}' (ID: {manifest_id}) "
                    f"from version {installed_version} to {available_version}"
                )
                content = download_content(solution_info["content_url"], session)
                import_conflicts = analyze_import_conflicts(
                    api_base_url, session, content, session_token
                )
                if import_conflicts:
                    logging.info("Conflicts detected during conflict analysis.")
                    import_conflict_options = build_import_conflict_options(
                        import_conflicts
                    )
                else:
                    logging.info("No conflicts detected during conflict analysis.")
                    import_conflict_options = {}
                success = import_content(
                    api_base_url, session, content, import_conflict_options, session_token
                )
                if success:
                    logging.info(f"Solution '{normalized_name}' (ID: {manifest_id}) updated successfully.")
                else:
                    logging.error(f"Failed to update solution '{normalized_name}' (ID: {manifest_id}).")
            else:
                logging.info(f"Solution '{normalized_name}' (ID: {manifest_id}) is already up-to-date.")
        else:
            logging.debug(
                f"No matching installed solution found for '{normalized_name}' (ID: {manifest_id}). Ignoring."
            )
    for key in installed_solutions:
        if key not in available_solutions:
            name, id_ = key
            logging.debug(f"Installed solution '{name}' (ID: {id_}) not found in manifest. Ignoring.")


def download_content(content_url, session):
    """
    Downloads the content from the specified URL.

    Args:
        content_url (str): The URL to download the content from.
        session (requests.Session): The HTTP session.

    Returns:
        bytes: The downloaded content.

    Raises:
        requests.RequestException: If the download fails.
    """
    logging.debug(f"Downloading content from URL: {content_url}")
    try:
        response = session.get(content_url, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        logging.debug(f"Content downloaded successfully from {content_url}")
        return response.content
    except requests.exceptions.RequestException as e:
        logging.error(f"Error downloading content: {e}")
        raise


def analyze_import_conflicts(api_base_url, session, content, session_token):
    """
    Analyzes import conflicts by posting the content to the Tanium API.

    Args:
        api_base_url (str): The base URL for the Tanium API.
        session (requests.Session): The HTTP session.
        content (bytes): The content to import.
        session_token (str): The authenticated session token.

    Returns:
        dict: A dictionary of import conflicts.

    Raises:
        requests.RequestException: If the API request fails.
    """
    import_url = f"{api_base_url}/import?import_analyze_conflicts_only=1"
    logging.debug(f"Posting content to API for conflict analysis at {import_url}")
    headers = build_headers(session_token, content_type="application/octet-stream")
    try:
        response = session.post(
            import_url, data=content, headers=headers, timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()
        logging.debug(f"Conflict analysis response status code: {response.status_code}")
        logging.debug(f"Conflict analysis response content: {response.text}")
        response_data = response.json().get("data", {})
        conflicts = response_data.get("object_list", {}).get(
            "import_conflict_details", []
        )
        import_conflicts = parse_import_conflicts(conflicts)
        logging.debug(
            f"Total import conflicts parsed: {sum(len(v) for v in import_conflicts.values())}"
        )
        return import_conflicts
    except requests.exceptions.RequestException as e:
        logging.error(f"Error during conflict analysis: {e}")
        raise


def parse_import_conflicts(conflicts):
    """
    Parses the import conflicts from the API response.

    Args:
        conflicts (list): A list of conflict details from the API response.

    Returns:
        dict: A dictionary categorizing conflicts by their types.
    """
    import_conflicts = {}
    for conflict in conflicts:
        conflict_type = conflict.get("type")
        conflict_name = conflict.get("name")
        is_new = conflict.get("is_new")
        is_permission_denied = conflict.get("permission_denied")
        conflict_info = {
            "type": conflict_type,
            "name": conflict_name,
            "is_new": is_new,
            "is_permission_denied": is_permission_denied,
        }
        logging.debug(
            f"Parsed conflict - Type: {conflict_type}, Name: {conflict_name}, New: {is_new}, Permission Denied: {is_permission_denied}"
        )
        if conflict_type not in import_conflicts:
            import_conflicts[conflict_type] = []
        import_conflicts[conflict_type].append(conflict_info)
    return import_conflicts


def build_import_conflict_options(import_conflicts):
    """
    Builds the import conflict options by setting overwrite for all conflict types.

    Args:
        import_conflicts (dict): A dictionary of import conflicts categorized by type.

    Returns:
        dict: A dictionary mapping conflict types to their overwrite options.
    """
    option_value = 1  # Overwrite
    import_conflict_options = {}
    for conflict_type, conflicts in import_conflicts.items():
        conflict_type_plural = (
            conflict_type + "s" if not conflict_type.endswith("s") else conflict_type
        )
        import_conflict_options[conflict_type_plural] = [option_value] * len(conflicts)
    logging.debug(f"Built import conflict options: {import_conflict_options}")
    return import_conflict_options


def import_content(
    api_base_url, session, content, import_conflict_options, session_token
):
    """
    Initiates the import process for the solution content.

    Args:
        api_base_url (str): The base URL for the Tanium API.
        session (requests.Session): The HTTP session.
        content (bytes): The content to import.
        import_conflict_options (dict): Conflict resolution options.
        session_token (str): The authenticated session token.

    Returns:
        bool: True if the import is successful, False otherwise.

    Raises:
        requests.RequestException: If the API request fails.
    """
    import_url = f"{api_base_url}/import"
    tanium_options = json.dumps({"import_conflict_options": import_conflict_options})
    headers = build_headers(
        session_token,
        content_type="application/octet-stream",
        additional_headers={
            "Prefer": "respond-async",
            "tanium-options": tanium_options,
        },
    )
    logging.debug(
        f"Initiating import process with headers: {headers} and conflict options: {import_conflict_options}"
    )
    try:
        response = session.post(
            import_url, data=content, headers=headers, timeout=DEFAULT_TIMEOUT
        )
        if response.status_code == 202:
            logging.info("Import successfully initiated, awaiting completion.")
            import_id = response.json().get("data", {}).get("id")
            return check_and_report_import_status(
                api_base_url, session, import_id, session_token
            )
        else:
            logging.error(
                f"Failed to initiate import. Status code: {response.status_code}"
            )
            logging.error(f"Response content: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Error initiating import: {e}")
        raise


def check_and_report_import_status(
    api_base_url, session, import_id, session_token, max_retries=10, initial_delay=10
):
    """
    Checks and reports the status of the import process.

    Args:
        api_base_url (str): The base URL for the Tanium API.
        session (requests.Session): The HTTP session.
        import_id (str): The import job ID.
        session_token (str): The authenticated session token.
        max_retries (int, optional): Maximum number of status check attempts.
        initial_delay (int, optional): Initial delay in seconds before retrying.

    Returns:
        bool: True if the import is successful, False otherwise.
    """
    import_status_url = f"{api_base_url}/import/{import_id}"
    headers = build_headers(session_token)
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(
                import_status_url, headers=headers, timeout=DEFAULT_TIMEOUT
            )
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
                logging.debug(
                    f"Import is still in progress. Attempt {attempt}/{max_retries}."
                )
        except requests.exceptions.RequestException as e:
            logging.error(f"Error checking import status: {e}")
        sleep_time = initial_delay * (2 ** (attempt - 1))
        logging.debug(f"Waiting {sleep_time} seconds before next status check...")
        time.sleep(sleep_time)
    logging.error("Maximum retries reached. Import status unknown.")
    return False


# 6. Main Execution Function

def main():
    """
    The main execution function orchestrating the solution update process.
    """
    args = parse_arguments()
    setup_logging(args.log_level, args.log_file)
    global DEFAULT_TIMEOUT
    DEFAULT_TIMEOUT = args.timeout
    env_vars = load_env_vars("tanium_creds.env")
    
    tanium_username = env_vars.get("TANIUM_USERNAME")
    tanium_password = env_vars.get("TANIUM_PASSWORD")
    tanium_base_url = env_vars.get("TANIUM_BASE_URL")
    
    server_api_base_url = f"{tanium_base_url}/api/v2"
    api_login_url = f"{server_api_base_url}/session/login"
    session_validate_url = f"{server_api_base_url}/session/validate"
    server_info_url = f"{server_api_base_url}/server_info"
    
    # Determine the AVAILABLE_SOLUTIONS_XML_URL
    if args.available_solutions_xml_url:
        available_solutions_url = args.available_solutions_xml_url
        logging.debug(f"Using AVAILABLE_SOLUTIONS_XML_URL from command-line: {available_solutions_url}")
    elif env_vars.get("AVAILABLE_SOLUTIONS_XML_URL"):
        available_solutions_url = env_vars.get("AVAILABLE_SOLUTIONS_XML_URL")
        logging.debug(f"Using AVAILABLE_SOLUTIONS_XML_URL from environment variable: {available_solutions_url}")
    else:
        logging.debug("No AVAILABLE_SOLUTIONS_XML_URL provided via command-line or environment. Fetching from server.")
        session = create_session()
        try:
            session_token = login_to_api(
                session, api_login_url, tanium_username, tanium_password
            )
            validate_session(session, session_validate_url, session_token)
            available_solutions_url = fetch_manifest_url(session, server_api_base_url, session_token)
            logging.debug(f"Using AVAILABLE_SOLUTIONS_XML_URL from server: {available_solutions_url}")
        except Exception as e:
            logging.error(f"Failed to retrieve AVAILABLE_SOLUTIONS_XML_URL from server: {e}")
            exit(1)
        finally:
            session.close()
    
    # Fetch server hosts
    session = create_session()
    try:
        # Authenticate using the original base URL
        session_token = login_to_api(
            session, api_login_url, tanium_username, tanium_password
        )
        validate_session(session, session_validate_url, session_token)
        
        server_hosts = get_server_hosts(session, server_api_base_url, session_token)
        
        if not server_hosts:
            logging.warning("No valid servers found to process.")
            exit(0)
        
        # Proceed with updating solutions for each server host
        for server in server_hosts:
            server_name = server["name"]
            server_address = server["address"]
            logging.info(f"Processing server: {server_name} ({server_address})")
            
            # Construct server-specific API base URL
            server_api_base_url = f"{server_address}/api/v2"
            server_info_url = f"{server_api_base_url}/server_info"
            
            try:
                # For each server, fetch available and installed solutions
                available_solutions = get_available_solutions(available_solutions_url, session)
                installed_solutions = get_installed_solutions(
                    server_info_url, session, session_token
                )
                update_solutions(
                    server_api_base_url,
                    session,
                    available_solutions,
                    installed_solutions,
                    session_token,
                )
            except Exception as e:
                logging.error(f"An error occurred while processing server {server_name}: {e}")
    except Exception as e:
        logging.error(f"Failed to fetch or process server hosts: {e}")
    finally:
        session.close()


# 7. Entry Point

if __name__ == "__main__":
    main()
