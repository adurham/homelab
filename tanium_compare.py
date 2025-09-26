#!/usr/bin/env python3
"""
Tanium API + Manifest comparison + multi-server support.

This script compares Tanium server solutions against a manifest file to identify
out-of-date or missing solutions.

The comparison happens in two phases:
1. Each server compared against the manifest
2. Servers compared against each other to detect inconsistencies

This ensures we catch both outdated servers and inconsistencies between servers.
"""

import json
import sys
import ssl
from urllib.request import Request, urlopen
import argparse
import logging
import os
import xml.etree.ElementTree as ET

# Check Python version
if sys.version_info < (3, 10):
    logging.error("This script requires Python 3.10 or higher. Your version is: " + sys.version)
    sys.exit(1)

# --------------------------------------------------------------------------- #
# Configuration
# ---------------------------------------------------------------------------

# Default values
DEFAULT_TIMEOUT = 10  # seconds
DEFAULT_POLL_INTERVAL = 5  # seconds between GET polls

# --------------------------------------------------------------------------- #
# Configuration Management
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load configuration from environment variables or return defaults.

    Returns:
        Dictionary containing configuration values
    """
    config = {
        "auth_token": (os.getenv("TANIUM_AUTH_TOKEN") or
                       "token-d5a080747431fbc998d32314795d6f8be6e8bca65e18e9168e8c20aa36"),
        "base_url_template": (os.getenv("TANIUM_BASE_URL") or
                            "https://tanium.chi.lab.amd-e.com"),
        "timeout": int(os.getenv("TANIUM_TIMEOUT", DEFAULT_TIMEOUT)),
        "poll_interval": int(os.getenv("TANIUM_POLL_INTERVAL", DEFAULT_POLL_INTERVAL))
    }
    
    return config

# --------------------------------------------------------------------------- #
# Client Class
# ---------------------------------------------------------------------------

class TaniumClient:
    """Wrapper for Tanium API requests with automatic base URL and token handling."""

    def __init__(self, host: str, config: dict = None):
        # Use the server's actual address if provided, otherwise use base URL template
        if host.startswith("http"):
            self.base = host
        else:
            self.base = config["base_url_template"].format(host=host)
        self.timeout = config["timeout"]
        self.poll_interval = config["poll_interval"]
        # Create unverified SSL context (for testing/development)
        self.context = ssl._create_unverified_context()
        self.auth_token = config["auth_token"]
        logging.debug(f"Created TaniumClient for host: {host}, base URL: {self.base}")

    def _full(self, path: str) -> str:
        """Construct the full URL for a given path."""
        return f"{self.base}{path}"

    def get(self, path: str) -> bytes:
        """Perform a GET request to the Tanium API."""
        req = Request(self._full(path), headers={
            "Accept": "application/json",
            "Session": self.auth_token
        })
        logging.debug(f"GET request to: {self._full(path)}")
        try:
            with urlopen(req, timeout=self.timeout, context=self.context) as resp:
                logging.debug(f"GET {self._full(path)} returned status: {resp.getcode()}")
                return resp.read()
        except Exception as exc:
            # Check for HTTP 401 Unauthorized specifically
            if hasattr(exc, 'code') and exc.code == 401:
                logging.error("Authentication failed: The TANIUM_AUTH_TOKEN is invalid or expired.")
                logging.error("Please check your TANIUM_AUTH_TOKEN environment variable.")
                logging.error("If you're using a session token, make sure it's not expired.")
                sys.exit(1)
            logging.error(f"GET {self._full(path)} failed: {exc}")
            raise

    def post(self, path: str, data: bytes,
             conflict_header: dict = None,
             prefer_async: bool = False) -> dict:
        """Perform a POST request to the Tanium API."""
        headers = {
            "Content-Type": "application/xml",
            "Session": self.auth_token
        }
        if prefer_async:
            headers["Prefer"] = "respond-async"

        if conflict_header is not None:
            # Only the second POST needs default_import_conflict_option
            if prefer_async:
                conflict_header.setdefault("default_import_conflict_option", 1)
            headers["tanium-options"] = json.dumps(conflict_header)

        # Debug: print the exact headers that will be sent
        logging.debug(f"POST {self._full(path)} headers: {headers}")

        req = Request(self._full(path), data=data, headers=headers)
        logging.debug(f"POST request to: {self._full(path)} with headers: {headers}")
        try:
            with urlopen(req, timeout=self.timeout, context=self.context) as resp:
                response_data = resp.read().decode("utf-8")
                logging.debug(f"POST {self._full(path)} returned status: {resp.getcode()}")
                logging.debug(f"POST response data: {response_data[:200]}...")  # Log first 200 chars
                return json.loads(response_data)
        except Exception as exc:
            # Check for HTTP 401 Unauthorized specifically
            if hasattr(exc, 'code') and exc.code == 401:
                logging.error("Authentication failed: The TANIUM_AUTH_TOKEN is invalid or expired.")
                logging.error("Please check your TANIUM_AUTH_TOKEN environment variable.")
                logging.error("If you're using a session token, make sure it's not expired.")
                sys.exit(1)
            logging.error(f"POST {self._full(path)} failed: {exc}")
            # Log the full error for debugging
            if hasattr(exc, 'read'):
                try:
                    error_content = exc.read().decode('utf-8')
                    logging.error(f"Error response content: {error_content}")
                except AttributeError:
                    pass
            raise

# --------------------------------------------------------------------------- #
# Data Retrieval Functions
# ---------------------------------------------------------------------------

def fetch_api_solutions(client: TaniumClient) -> dict:
    """Fetch the list of solutions from the Tanium API."""
    try:
        logging.info(f"Fetching solutions from: {client.base}")
        raw = client.get("/api/v2/solutions")
        data = json.loads(raw.decode("utf-8"))
        
        sol_map = {}
        for s in data.get("data", []):
            sid = s.get("solution_id") or s.get("id")
            ver = s.get("imported_version")
            name = s.get("name")
            if sid and ver:
                sol_map[sid] = {"version": ver, "name": name}
        return sol_map
    except Exception as exc:
        logging.error(f"Failed to fetch API solutions: {exc}")
        raise

def fetch_manifest_url(client: TaniumClient) -> str:
    """Retrieve the manifest URL from the Tanium server's system settings.

    Args:
        client: Tanium client instance

    Returns:
        The manifest URL as a string

    Raises:
        ValueError: If console_manifestURL is not found
    """
    try:
        logging.info("Fetching manifest URL from system settings")
        raw = client.get("/api/v2/system_settings")
        data = json.loads(raw.decode("utf-8"))

        for item in data.get("data", []):
            if item.get("name") == "console_manifestURL":
                value = item.get("value")
                if value:
                    return value
        logging.error("console_manifestURL not found in system settings")
        raise ValueError("console_manifestURL not found")
    except Exception as exc:
        logging.error(f"Failed to fetch manifest URL: {exc}")
        raise

def fetch_manifest_data(client: TaniumClient, url: str) -> dict:
    """Fetch and parse the manifest from the given URL.

    Args:
        client: Tanium client instance
        url: URL of the manifest file

    Returns:
        Dictionary containing the parsed manifest data

    Raises:
        SystemExit: If any HTTP or JSON error occurs
    """
    try:
        logging.info(f"Fetching manifest from URL: {url}")
        # Create request with appropriate headers
        req = Request(url, headers={"Accept": "application/xml"})
        
        # Fetch the data
        with urlopen(req, timeout=client.timeout, context=client.context) as resp:
            if resp.getcode() != 200:
                logging.error(f"HTTP {resp.getcode()} fetching manifest from {url}")
                raise ConnectionError(f"HTTP {resp.getcode()}")
            
            # Read and decode the response
            raw_data = resp.read().decode("utf-8")
            
            # Check if response is empty
            if not raw_data.strip():
                logging.error(f"Manifest URL returned empty response: {url}")
                logging.error("This may indicate that the manifest URL is not accessible or returns empty data.")
                logging.error("Please verify that the URL is correct and accessible.")
                raise ValueError("Empty manifest response")
            
            # Try to parse as XML first (since you mentioned it's an XML manifest)
            try:
                root = ET.fromstring(raw_data)
                manifest_data = {}
                
                # Parse the XML manifest
                for solution in root.findall("./solution"):
                    sid = solution.findtext("id")
                    ver = solution.findtext("version")
                    url_ = solution.findtext("content_url") or solution.findtext("contenturl")
                    name_alt = solution.findtext("name_alternate")
                    
                    if sid and ver:
                        manifest_data[sid] = {
                            "version": ver, 
                            "content_url": url_,
                            "name": name_alt or f"Unknown Solution ({sid})"
                        }
                
                logging.info(f"Successfully parsed XML manifest from {url}")
                return manifest_data
                
            except ET.ParseError as xml_exc:
                logging.error(f"Failed to parse manifest as XML: {xml_exc}")
                logging.error(f"Raw response: {raw_data[:500]}...")  # Show first 500 chars
                logging.error("The manifest might not be in XML format, or the server returned unexpected content.")
                logging.error("Please verify that the URL is correct and returns a valid XML manifest.")
                raise ValueError(f"XML parsing failed: {xml_exc}")
                
    except Exception as exc:
        logging.error(f"Failed to fetch manifest data from {url}: {exc}")
        raise

def get_server_hosts(client: TaniumClient) -> list[dict]:
    """Retrieve the list of server hosts from the Tanium server.

    Args:
        client: Tanium client instance

    Returns:
        List of dictionaries containing server information
    """
    try:
        logging.info("Fetching server hosts")
        raw = client.get("/api/v2/server_host")  # Uses base URL
        data = json.loads(raw.decode("utf-8"))
        
        servers = []
        for server in data.get("data", {}).get("servers", []):
            name = server.get("name")
            address = server.get("address")
            if name and address:
                # Ensure address has a scheme
                if not address.startswith("http"):
                    address = f"https://{address}"
                servers.append({"name": name, "address": address})
        
        if not servers:
            logging.error("No servers found in server_host response")
            raise ValueError("No servers found")
            
        return servers
    except Exception as exc:
        logging.error(f"Failed to fetch server hosts: {exc}")
        raise

# --------------------------------------------------------------------------- #
# Import Functions
# ---------------------------------------------------------------------------

def import_solution(client: TaniumClient, solution_id: str, content_url: str) -> dict:
    """Import a single solution by ID using its content URL.
    
    Args:
        client: Tanium client instance
        solution_id: The ID of the solution to import
        content_url: The URL where the solution content can be retrieved
        
    Returns:
        Dictionary with import results
    """
    # Initialize variables at the beginning of the function
    import_url = None
    content_data = None
    
    try:
        # First, fetch the content from the content_url
        logging.info(f"Fetching content for solution {solution_id} from {content_url}")
        
        # Create request with appropriate headers
        req = Request(content_url, headers={"Accept": "application/xml"})
        
        # Fetch the content
        with urlopen(req, timeout=client.timeout, context=client.context) as resp:
            if resp.getcode() != 200:
                logging.error(f"HTTP {resp.getcode()} fetching content for solution {solution_id}")
                raise ConnectionError(f"HTTP {resp.getcode()}")
            
            # Read and decode the response
            content_data = resp.read()
            logging.debug(f"Fetched {len(content_data)} bytes of content for solution {solution_id}")
            
        # Prepare the import request with tanium-options header
        conflict_header = {"import_analyze_conflicts_only": 1}
        
        # Set the import URL and log it
        import_url = client._full("/api/v2/import")
        logging.info(f"Attempting to import solution {solution_id} to URL: {import_url}")
        logging.debug(f"Content data preview: {content_data[:200] if content_data else 'N/A'}...")  # Log first 200 chars
        logging.debug(f"Conflict header: {conflict_header}")
        
        # Make the POST request to /api/v2/import
        response = client.post("/api/v2/import", 
                             data=content_data,
                             conflict_header=conflict_header)
        
        logging.info(f"Import request for solution {solution_id} completed")
        return response
        
    except Exception as exc:
        logging.error(f"Failed to import solution {solution_id}: {exc}")
        # Add extra debug info for 403 errors specifically
        if "403" in str(exc):
            logging.error(f"POST URL attempted: {import_url}")
            if import_url is None:
                logging.error("ERROR: import_url was not set properly!")
        raise

def import_out_of_date_solutions(client: TaniumClient, manifest: dict, out_of_date_solutions: list) -> dict:
    """Import all out-of-date solutions.
    
    Args:
        client: Tanium client instance
        manifest: Dictionary containing manifest data
        out_of_date_solutions: List of out-of-date solution dictionaries
        
    Returns:
        Dictionary with import results
    """
    import_results = {}
    
    for solution in out_of_date_solutions:
        sid = solution["sid"]
        name = solution["name"]
        manifest_ver = solution["manifest_ver"]
        
        # Get the content URL from manifest
        if sid in manifest:
            content_url = manifest[sid]["content_url"]
            if not content_url:
                logging.warning(f"No content URL found for solution {sid}")
                continue
                
            try:
                logging.info(f"Importing solution {sid} ({name}) - Manifest version: {manifest_ver}")
                result = import_solution(client, sid, content_url)
                import_results[sid] = {
                    "status": "success",
                    "result": result
                }
            except Exception as exc:
                logging.error(f"Failed to import solution {sid}: {exc}")
                import_results[sid] = {
                    "status": "failed",
                    "error": str(exc)
                }
        else:
            logging.warning(f"Solution {sid} not found in manifest")
            
    return import_results

# --------------------------------------------------------------------------- #
# Comparison Functions
# ---------------------------------------------------------------------------

def compare_solutions(client: TaniumClient, manifest: dict) -> dict:
    """Compare the manifest solutions against the API's current solutions.

    Returns:
        Dictionary with comparison results
    """
    try:
        sol_map = fetch_api_solutions(client)
        logging.info(f"API has {len(sol_map)} solutions")

        results = {
            "out_of_date": [],
            "missing": [],
            "up_to_date": []
        }

        for sid, ver_info in manifest.items():
            ver = ver_info.get("version", "")
            name = ver_info.get("name", f"Unknown Solution ({sid})")
            if sid not in sol_map:
                logging.warning(f"[MISSING] Solution {sid} ({name}) (version {ver}) not found in API")
                results["missing"].append({"sid": sid, "version": ver, "name": name})
            else:
                api_ver = sol_map[sid].get("version", "")
                if api_ver != ver:
                    logging.warning(f"[OUT-OF-DATE] Solution {sid} ({name}) (API version: {api_ver}, Manifest: {ver})")
                    results["out_of_date"].append({"sid": sid, "api_version": api_ver, "manifest_version": ver, "name": name})
                else:
                    results["up_to_date"].append({"sid": sid, "version": ver, "name": name})

        return results

    except Exception as exc:
        logging.error(f"Comparison failed: {exc}")
        raise

def compare_servers(server_results: dict) -> dict:
    """
    Compare servers against each other to detect inconsistencies.

    Args:
        server_results: Dictionary containing results from each server comparison

    Returns:
        Dictionary with comparison results between servers
    """
    server_versions = {}
    
    for server_name, results in server_results.items():
        server_versions[server_name] = {}
        
        # Process each category of results
        for item in results["out_of_date"] + results["missing"] + results["up_to_date"]:
            sid = item["sid"]
            name = item["name"]
            
            # Extract version based on the source list
            if "api_version" in item:
                ver = item["api_version"]
            elif "version" in item:
                ver = item["version"]
            else:
                continue  # Skip items without version info
            
            server_versions[server_name][sid] = {"name": name, "ver": ver}
    
    # Compare versions across servers
    inconsistencies = {}
    
    # Find all unique solution IDs across all servers
    all_sids = set()
    for versions in server_versions.values():
        all_sids.update(versions.keys())
    
    # Compare each solution across servers
    for sid in all_sids:
        server_versions_list = []
        for server_name, versions in server_versions.items():
            if sid in versions:
                server_versions_list.append((server_name, versions[sid]))
        
        # If solution exists on multiple servers, check if versions match
        if len(server_versions_list) > 1:
            # Get all versions for this solution across servers
            versions = [ver["ver"] for _, ver in server_versions_list]
            names = [ver["name"] for _, ver in server_versions_list]
            unique_versions = set(versions)
            
            if len(unique_versions) > 1:
                # Version mismatch found
                inconsistencies[sid] = {
                    "solutions": server_versions_list,
                    "versions": list(unique_versions),
                    "names": list(set(names)),
                    "status": "inconsistent"
                }
                logging.warning(f"[INCONSISTENCY] Solution {sid} ({list(set(names))[0]}) has different versions across servers: {dict(server_versions_list)}")
    
    return inconsistencies

# --------------------------------------------------------------------------- #
# Main Execution
# ---------------------------------------------------------------------------

def main():
    """Main function to execute the comparison.

    The comparison happens in two phases:
    1. Each server compared against the manifest
    2. Servers compared against each other to detect inconsistencies
    """
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Compare Tanium solutions against manifest")
    parser.add_argument("--manifest-url", help="URL to the manifest file (optional)")
    parser.add_argument("--log-level", default="DEBUG", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Logging level")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds")
    parser.add_argument("--import-out-of-date", action="store_true", help="Import out-of-date solutions")
    
    args = parser.parse_args()
    
    # Set up logging
    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                       format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Load configuration
    config = load_config()
    if args.timeout:
        config["timeout"] = args.timeout

    # Get the list of servers from the primary server
    try:
        primary_client = TaniumClient("https://tanium.chi.lab.amd-e.com", config)
        servers = get_server_hosts(primary_client)
        logging.info(f"Found {len(servers)} servers: {[s['name'] for s in servers]}")
    except Exception as exc:
        logging.error(f"Failed to get server list: {exc}")
        sys.exit(1)
    
    # If no manifest URL provided, fetch it from the primary server
    if not args.manifest_url:
        try:
            manifest_url = fetch_manifest_url(primary_client)
            logging.info(f"Retrieved manifest URL: {manifest_url}")
        except Exception as exc:
            logging.error(f"Failed to get manifest URL: {exc}")
            sys.exit(1)
    else:
        manifest_url = args.manifest_url
        logging.info(f"Using provided manifest URL: {manifest_url}")
    
    # Fetch the manifest
    try:
        manifest = fetch_manifest_data(primary_client, manifest_url)
        logging.info(f"Manifest has {len(manifest)} solutions")
    except Exception as exc:
        logging.error(f"Failed to fetch manifest: {exc}")
        sys.exit(1)
    
    # Phase 1: Compare each server against the manifest
    server_results = {}
    server_clients = {}  # Keep track of server clients for imports
    
    for server in servers:
        logging.info(f"Processing server: {server['name']} ({server['address']})")
        try:
            # Create a client for this specific server
            client = TaniumClient(server["address"], config)
            server_clients[server["name"]] = client  # Store for later use
            results = compare_solutions(client, manifest)
            server_results[server["name"]] = results
        except Exception as exc:
            logging.error(f"Failed to compare server {server['name']}: {exc}")
            # Continue with other servers
            continue
    
    # Phase 2: Compare servers against each other
    inconsistencies = compare_servers(server_results)
    
    # Display results
    print("\n=== SERVER COMPARISON RESULTS ===")
    
    total_missing = 0
    total_out_of_date = 0
    total_up_to_date = 0
    
    for server_name, results in server_results.items():
        print(f"\n{server_name}:")
        print(f"  Missing: {len(results['missing'])}")
        print(f"  Out of date: {len(results['out_of_date'])}")
        print(f"  Up to date: {len(results['up_to_date'])}")
        
        total_missing += len(results['missing'])
        total_out_of_date += len(results['out_of_date'])
        total_up_to_date += len(results['up_to_date'])
    
    if inconsistencies:
        print("\n=== INCONSISTENCIES FOUND ===")
        for sid, info in inconsistencies.items():
            print(f"  Solution {sid} ({info['names'][0]}): versions {info['versions']}")
    else:
        print("\n=== NO INCONSISTENCIES FOUND ===")
    
    # Show summary
    print("\n=== FINAL SUMMARY ===")
    print(f"Total missing solutions: {total_missing}")
    print(f"Total out-of-date solutions: {total_out_of_date}")
    print(f"Total inconsistencies between servers: {len(inconsistencies)}")
    
    # If --import-out-of-date flag is set, import the out-of-date solutions
    if args.import_out_of_date:
        print("\n=== IMPORTING OUT-OF-DATE SOLUTIONS ===")
        
        # Collect all out-of-date solutions from all servers
        all_out_of_date = []
        for server_name, results in server_results.items():
            all_out_of_date.extend(results["out_of_date"])
        
        # Remove duplicates based on solution ID
        seen_sids = set()
        unique_out_of_date = []
        for sol in all_out_of_date:
            if sol["sid"] not in seen_sids:
                unique_out_of_date.append(sol)
                seen_sids.add(sol["sid"])
        
        print(f"Found {len(unique_out_of_date)} unique out-of-date solutions to import")
        
        # Import each solution - use the appropriate server client
        for solution in unique_out_of_date:
            sid = solution["sid"]
            name = solution["name"]
            manifest_version = solution["manifest_version"]  # Fixed key name
            api_version = solution["api_version"]
            
            print(f"Importing solution {sid} ({name}) - API: {api_version} -> Manifest: {manifest_version}")
            
            # Find which server has this solution out-of-date
            target_server = None
            for server_name, results in server_results.items():
                # Check if this solution is out-of-date on this server
                for out_of_date_sol in results["out_of_date"]:
                    if out_of_date_sol["sid"] == sid:
                        target_server = server_name
                        break
                if target_server:
                    break
            
            if target_server:
                try:
                    # Import using the specific server client
                    client = server_clients[target_server]
                    import_solution(client, sid, manifest[sid]["content_url"])
                    print(f"  Import successful for {sid} on server {target_server}")
                except Exception as exc:
                    print(f"  Import failed for {sid} on server {target_server}: {exc}")
            else:
                print(f"  Could not determine target server for solution {sid}")
    
    # Exit with error code if inconsistencies or missing solutions found
    exit_code = 0
    for results in server_results.values():
        if results["missing"] or results["out_of_date"]:
            exit_code = 1
    if inconsistencies:
        exit_code = 1
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
