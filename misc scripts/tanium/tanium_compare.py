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
        self.base = config["base_url_template"].format(host=host)
        self.timeout = config["timeout"]
        self.poll_interval = config["poll_interval"]
        # Create unverified SSL context (for testing/development)
        self.context = ssl._create_unverified_context()
        self.auth_token = config["auth_token"]

    def _full(self, path: str) -> str:
        """Construct the full URL for a given path."""
        return f"{self.base}{path}"

    def get(self, path: str) -> bytes:
        """Perform a GET request to the Tanium API."""
        req = Request(self._full(path), headers={
            "Accept": "application/json",
            "Session": self.auth_token
        })
        try:
            with urlopen(req, timeout=self.timeout, context=self.context) as resp:
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
        try:
            with urlopen(req, timeout=self.timeout, context=self.context) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            # Check for HTTP 401 Unauthorized specifically
            if hasattr(exc, 'code') and exc.code == 401:
                logging.error("Authentication failed: The TANIUM_AUTH_TOKEN is invalid or expired.")
                logging.error("Please check your TANIUM_AUTH_TOKEN environment variable.")
                logging.error("If you're using a session token, make sure it's not expired.")
                sys.exit(1)
            logging.error(f"POST {self._full(path)} failed: {exc}")
            raise

# --------------------------------------------------------------------------- #
# Data Retrieval Functions
# ---------------------------------------------------------------------------

def fetch_api_solutions(client: TaniumClient) -> dict:
    """Fetch the list of solutions from the Tanium API."""
    try:
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
        raw = client.get("/api/v2/server_host")
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
                results["missing"].append({"sid": sid, "name": name, "ver": ver})
            elif sol_map[sid]["version"] != ver:
                logging.warning(f"[OUT-OF-DATE] Solution {sid} ({name}) (API version {sol_map[sid]['version']}, manifest version {ver})")
                results["out_of_date"].append({
                    "sid": sid, 
                    "name": name, 
                    "api_ver": sol_map[sid]["version"], 
                    "manifest_ver": ver
                })
            else:
                results["up_to_date"].append({"sid": sid, "name": name, "ver": ver})
        
        return results
        
    except Exception as exc:
        logging.error(f"Error comparing solutions: {exc}")
        raise

def compare_servers(server_results: dict) -> dict:
    """Compare servers against each other to detect inconsistencies.

    Args:
        server_results: Dictionary containing results from each server comparison

    Returns:
        Dictionary with comparison results between servers
    """
    # Extract all solution versions from each server
    server_versions = {}
    for server_name, results in server_results.items():
        server_versions[server_name] = {}
        for item in results["out_of_date"] + results["missing"] + results["up_to_date"]:
            sid = item["sid"]
            name = item["name"]
            ver = item["ver"] if "ver" in item else item["api_ver"]
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
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Logging level")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds")
    
    args = parser.parse_args()
    
    # Set up logging
    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                        format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Load configuration
    config = load_config()
    if args.timeout:
        config["timeout"] = args.timeout
    
    # Get base URL from config
    base_url = config["base_url_template"]
    
    # Create base client to discover servers
    try:
        # Use a dummy host to discover servers
        base_client = TaniumClient("127.0.0.1", config)
        server_hosts = get_server_hosts(base_client)
        
        if not server_hosts:
            logging.error("No servers found in the discovery response")
            sys.exit(1)
            
        logging.info(f"Found {len(server_hosts)} servers to process")
        
        # Dictionary to store results from each server
        server_results = {}
        
        # Process each server
        for server in server_hosts:
            server_name = server["name"]
            server_address = server["address"]
            logging.info(f"\n[HOST] {server_name} ({server_address})")
            
            try:
                # Create client for this server
                client = TaniumClient(server_address, config)
                
                # Try to use the provided manifest URL first
                if args.manifest_url:
                    logging.info(f"Using provided manifest URL: {args.manifest_url}")
                    manifest_data = fetch_manifest_data(client, args.manifest_url)
                else:
                    # Otherwise look up the manifest URL from the server
                    logging.info("Looking up manifest URL from server settings")
                    manifest_url = fetch_manifest_url(client)
                    manifest_data = fetch_manifest_data(client, manifest_url)
                
                # Compare server against manifest
                results = compare_solutions(client, manifest_data)
                server_results[server_name] = results
                
                # Show summary
                missing_count = len(results["missing"])
                out_of_date_count = len(results["out_of_date"])
                up_to_date_count = len(results["up_to_date"])
                
                logging.info(f"Summary for {server_name}: {missing_count} missing, {out_of_date_count} out-of-date, {up_to_date_count} up-to-date")
                
            except Exception as exc:
                logging.error(f"Failed to process server {server_name}: {exc}")
        
        # Now compare servers against each other to detect inconsistencies
        logging.info("\n" + "="*60)
        logging.info("SERVER TO SERVER COMPARISON")
        logging.info("="*60)
        
        inconsistencies = compare_servers(server_results)
        
        if inconsistencies:
            logging.warning(f"Found {len(inconsistencies)} inconsistencies between servers")
            for sid, info in inconsistencies.items():
                logging.warning(f"Solution {sid} ({info['names'][0]}) has different versions across servers: {dict(info['solutions'])}")
        else:
            logging.info("All servers have consistent versions across all solutions")
        
        # Final summary
        logging.info("\n" + "="*60)
        logging.info("FINAL SUMMARY")
        logging.info("="*60)
        
        total_missing = 0
        total_out_of_date = 0
        total_inconsistent = len(inconsistencies)
        
        for server_name, results in server_results.items():
            total_missing += len(results["missing"])
            total_out_of_date += len(results["out_of_date"])
        
        logging.info(f"Total missing solutions: {total_missing}")
        logging.info(f"Total out-of-date solutions: {total_out_of_date}")
        logging.info(f"Total inconsistencies between servers: {total_inconsistent}")
        
        if total_missing == 0 and total_out_of_date == 0 and total_inconsistent == 0:
            logging.info("All servers are up-to-date and consistent with each other!")
        else:
            logging.info("Some servers need attention. Please review the output above.")
            
    except Exception as exc:
        logging.error(f"Error during main execution: {exc}")
        sys.exit(1)
    
    logging.info("Comparison complete")

if __name__ == "__main__":
    main()
