import json
import logging
import requests
import time
import xml.etree.ElementTree as ET
from packaging import version
import urllib3

# Disable SSL warnings from urllib3 (useful when SSL certificate verification is disabled)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Setup basic logging to file
logging.basicConfig(
    level=logging.DEBUG,
    filename="application.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def load_env_vars(filename):
    try:
        env_vars = {}
        with open(filename) as file:
            for line in file:
                line = line.strip()
                if line and "=" in line:
                    name, value = line.split("=", 1)
                    env_vars[name] = value
        return env_vars
    except FileNotFoundError:
        logging.error("Environment file 'tanium_creds.env' not found.")
        exit(1)


def parse_xml(xml_url):
    """Fetch and parse XML from a URL to extract solutions details."""
    logging.debug("Fetching XML from URL: %s", xml_url)
    try:
        response = requests.get(xml_url, verify=False)
        response.raise_for_status()
        xml_data = response.text
        root = ET.fromstring(xml_data)
        solutions = []
        for solution in root.findall(".//solution"):
            solution_details = {
                "id": solution.find("id").text,
                "name": solution.find("name").text,
                "version": solution.find("version").text,
                "content_url": solution.find("content_url").text,
            }
            solutions.append(solution_details)
            logging.debug("Parsed solution: %s", solution_details)
        return solutions
    except requests.RequestException as e:
        logging.error("Failed to fetch or parse XML: %s", e)
        raise


def login_to_api(api_login_url, username, password):
    """Authenticate with the API and retrieve a session token."""
    logging.debug("Logging in to API at: %s", api_login_url)
    try:
        response = requests.post(
            api_login_url,
            json={"username": username, "password": password},
            verify=False,
        )
        response.raise_for_status()
        session = response.json().get("data", {}).get("session")
        logging.debug("Obtained session token: %s", session)
        return session
    except requests.RequestException as e:
        logging.error("Failed to login to API: %s", e)
        raise


def validate_session(api_validate_url, session_token):
    """Check if the provided session token is still valid."""
    logging.debug("Validating session token at: %s", api_validate_url)
    try:
        response = requests.post(
            api_validate_url, json={"session": session_token}, verify=False
        )
        response.raise_for_status()
        logging.debug("Session token validated successfully.")
        return True
    except requests.RequestException as e:
        logging.error("Session token validation failed: %s", e)
        return False


def get_server_details(api_url, headers):
    """Retrieve server details including name and address."""
    logging.debug("Retrieving server details from API: %s", api_url)
    try:
        response = requests.get(api_url, headers=headers, verify=False)
        response.raise_for_status()
        servers = response.json().get("data", {}).get("servers", [])
        server_list = [
            {"name": server["name"], "address": server["address"]} for server in servers
        ]
        logging.debug("Retrieved server details: %s", server_list)
        return server_list
    except requests.RequestException as e:
        logging.error("Failed to fetch server details: %s", e)
        raise


def normalize_name(name):
    """Normalize solution names by removing known prefixes and replacing underscores."""
    original_name = name
    name = name.replace("_", " ")
    prefixes = ["Tanium "]
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix) :]
    normalized_name = name.strip()
    logging.debug("Normalized name from '%s' to '%s'", original_name, normalized_name)
    return normalized_name


def get_installed_solutions(api_url, headers):
    """Retrieve details of installed solutions from the server."""
    logging.debug("Retrieving installed solutions from API: %s", api_url)
    try:
        response = requests.get(api_url, headers=headers, verify=False)
        response.raise_for_status()
        data = (
            response.json()
            .get("data", {})
            .get("Diagnostics", {})
            .get("Installed_Solutions", {})
        )
        installed_solutions = {}
        for details in data.values():
            normalized_name = normalize_name(details["name"])
            solution_details = {
                "id": details["id"],
                "version": details["version"],
                "last_updated": details["last_updated"],
            }
            installed_solutions[normalized_name] = solution_details
            logging.debug("Retrieved installed solution: %s", solution_details)
        return installed_solutions
    except requests.RequestException as e:
        logging.error("Failed to fetch installed solutions details: %s", e)
        raise


def get_installed_workbenches(api_url, headers):
    """Retrieve details of installed workbenches from the server."""
    logging.debug("Retrieving installed workbenches from API: %s", api_url)
    try:
        response = requests.get(api_url, headers=headers, verify=False)
        response.raise_for_status()
        data = (
            response.json()
            .get("data", {})
            .get("Diagnostics", {})
            .get("Installed_Workbenches", {})
        )
        installed_workbenches = {}
        for name, details in data.items():
            normalized_name = normalize_name(name)
            workbench_details = {
                "version": details["version"],
                "last_updated": details["last_updated"],
            }
            installed_workbenches[normalized_name] = workbench_details
            logging.debug("Retrieved installed workbench: %s", workbench_details)
        return installed_workbenches
    except requests.RequestException as e:
        logging.error("Failed to fetch installed workbenches details: %s", e)
        raise


def download_content(content_url):
    """Download content from the specified URL."""
    logging.debug("Downloading content from URL: %s", content_url)
    try:
        response = requests.get(content_url, verify=False)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        logging.error(
            "Failed to download content from URL: %s, error: %s", content_url, e
        )
        raise


def get_import_conflict_details(api_import_url, headers, content):
    """Post content to the API and retrieve any import conflicts."""
    logging.debug("Posting content to API for conflict check: %s", api_import_url)
    try:
        response = requests.post(
            api_import_url, headers=headers, data=content, verify=False
        )
        response.raise_for_status()
        response_data = response.json().get("data", {})
        object_list = response_data.get("object_list", {})
        import_conflict_details = object_list.get("import_conflict_details", [])
        conflicts = {}
        for conflict in import_conflict_details:
            conflict_type = conflict.get("type")
            conflict_name = conflict.get("name")
            if conflict_type in conflicts:
                conflicts[conflict_type].append(conflict_name)
            else:
                conflicts[conflict_type] = [conflict_name]
        logging.debug("Retrieved import conflict details: %s", conflicts)
        return conflicts
    except requests.RequestException as e:
        logging.error("Failed to get import conflict details: %s", e)
        raise


def build_import_conflict_options(import_conflicts):
    """Build options to resolve identified import conflicts based on the API's conflict reports."""
    import_conflict_options = {}
    for conflict_type, conflicts in import_conflicts.items():
        conflict_type_plural = (
            conflict_type + "s" if not conflict_type.endswith("s") else conflict_type
        )
        import_conflict_options[conflict_type_plural] = [1] * len(conflicts)
    logging.debug("Built import conflict options: %s", import_conflict_options)
    return import_conflict_options


def initiate_import(
    api_url, headers, content, import_conflict_options=None, max_retries=6
):
    """Initiate the import process with the specified content and conflict resolution options, with retry logic."""
    headers["Prefer"] = "respond-async"
    headers["tanium-options"] = json.dumps(
        {"import_conflict_options": import_conflict_options}
    )
    logging.debug("Headers set for import: %s", headers)
    attempt = 0
    while attempt < max_retries:
        logging.debug("Type of content: %s", type(content))
        logging.debug("Content: %s", content)
        try:
            response = requests.post(
                api_url, headers=headers, data=content, verify=False
            )
            if response.status_code in (200, 202):
                logging.debug("Import initiated successfully: %s", response.json())
                return response
            elif response.status_code == 409:
                logging.warning(
                    "Conflict detected during import initiation: %s", response.json()
                )
                attempt += 1
                time.sleep(10 * attempt)  # Exponential back-off
            else:
                logging.error(
                    "Import initiation failed with status code %d: %s",
                    response.status_code,
                    response.text,
                )
                response.raise_for_status()
        except requests.RequestException as e:
            logging.error("Exception occurred during import initiation: %s", e)
            attempt += 1
            time.sleep(10 * attempt)  # Exponential back-off

    raise Exception("Max retries reached, failed to initiate import")


def check_and_report_import_status(api_url, headers, import_id):
    """Check import status until completion and report the final status."""
    logging.debug("Checking import status for import ID: %s", import_id)
    while True:
        try:
            response = requests.get(
                f"{api_url}/{import_id}", headers=headers, verify=False
            )
            response.raise_for_status()
            status_data = response.json()
            status = status_data.get("data", {}).get("stage")
            if status == "complete":
                logging.info("Import completed successfully for ID: %s", import_id)
                break
            elif status in ("failed", "error"):
                logging.error("Import failed for ID: %s", import_id)
                break
            else:
                logging.debug("Current import status for ID %s: %s", import_id, status)
                time.sleep(10)  # Polling interval
        except requests.RequestException as e:
            logging.error("Failed to check import status: %s", e)
            break


def update_solutions(api_base_url, headers, available_solutions, installed_solutions):
    """Update solutions if newer versions are available."""
    for solution in available_solutions:
        normalized_name = normalize_name(solution["name"])
        if normalized_name in installed_solutions:
            current_version = installed_solutions[normalized_name]["version"]
            new_version = solution["version"]
            if version.parse(new_version) > version.parse(current_version):
                logging.info(
                    "Updating solution %s from version %s to %s",
                    normalized_name,
                    current_version,
                    new_version,
                )
                try:
                    content = download_content(solution["content_url"])
                    import_conflicts = get_import_conflict_details(
                        f"{api_base_url}/api/v2/snapshot/import/submit",
                        headers,
                        content,
                    )
                    import_conflict_options = build_import_conflict_options(
                        import_conflicts
                    )
                    response = initiate_import(
                        f"{api_base_url}/api/v2/snapshot/import/submit",
                        headers,
                        content,
                        import_conflict_options,
                    )
                    import_id = response.headers["Location"].split("/")[-1]
                    check_and_report_import_status(
                        f"{api_base_url}/api/v2/snapshot/import/status",
                        headers,
                        import_id,
                    )
                except Exception as e:
                    logging.error(
                        "Exception occurred while updating %s: %s",
                        normalized_name,
                        str(e),
                    )
            else:
                logging.info("Solution %s is already up-to-date.", normalized_name)
        else:
            logging.info("Solution %s is not installed.", normalized_name)


def main():
    env_vars = load_env_vars("tanium_creds.env")
    tanium_username = env_vars.get("TANIUM_USERNAME")
    tanium_password = env_vars.get("TANIUM_PASSWORD")
    server_api_base_url = env_vars.get("TANIUM_BASE_URL")
    available_solutions_xml_url = env_vars.get("AVAILABLE_SOLUTIONS_XML_URL")

    session_token = login_to_api(
        f"https://{server_api_base_url}/api/v2/session/login", tanium_username, tanium_password
    )
    headers = {
        "session": session_token,
        "Content-Type": "application/octet-stream",
    }

    available_solutions = parse_xml(available_solutions_xml_url)
    installed_solutions = get_installed_solutions(
        f"https://{server_api_base_url}/api/v2/result_data/69", headers
    )
    installed_workbenches = get_installed_workbenches(
        f"https://{server_api_base_url}/api/v2/result_data/70", headers
    )

    # Combine installed solutions and workbenches for the update process
    installed_items = {**installed_solutions, **installed_workbenches}

    update_solutions(server_api_base_url, headers, available_solutions, installed_items)

    logging.info("Update check and process complete.")


if __name__ == "__main__":
    main()
