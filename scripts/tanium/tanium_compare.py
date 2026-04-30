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
from urllib.error import HTTPError
import argparse
import logging
import os
import xml.etree.ElementTree as ET
import time
import re
import time as _time
from typing import Any, Dict, List, Optional
import signal
from dataclasses import dataclass
from enum import Enum
import gzip
from io import BytesIO
import atexit

# Check Python version
if sys.version_info < (3, 9):
    logging.error("This script requires Python 3.9 or higher. Your version is: " + sys.version)
    sys.exit(1)

# --------------------------------------------------------------------------- #
# Configuration
# ---------------------------------------------------------------------------

# Default values
DEFAULT_TIMEOUT = 10  # seconds
DEFAULT_POLL_INTERVAL = 5  # seconds between GET polls
DEFAULT_MAX_RETRIES = 5
DEFAULT_IMPORT_TIMEOUT = 600  # 10 minutes
DEFAULT_MAX_CONCURRENCY = 4

# HTTP status codes
HTTP_UNAUTHORIZED = 401
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERRORS = (500, 502, 503, 504)

# Import conflict options
CONFLICT_OPTION_REPLACE = 1
CONFLICT_OPTION_SKIP = 0

# --------------------------------------------------------------------------- #
# Data Classes and Enums
# ---------------------------------------------------------------------------

class ConflictDefault(Enum):
    """Enum for conflict resolution defaults."""
    REPLACE = "replace"
    SKIP = "skip"

@dataclass
class SolutionInfo:
    """Information about a solution."""
    sid: str
    version: str
    name: str
    content_url: Optional[str] = None

@dataclass
class ServerInfo:
    """Information about a server."""
    name: str
    address: str

@dataclass
class ComparisonResult:
    """Results of comparing solutions."""
    out_of_date: List[Dict[str, Any]]
    missing: List[Dict[str, Any]]
    up_to_date: List[Dict[str, Any]]

# --------------------------------------------------------------------------- #
# Configuration Management
# ---------------------------------------------------------------------------

def load_config() -> Dict[str, Any]:
    """Load configuration from environment variables or return defaults.

    Returns:
        Dictionary containing configuration values
    """
    config = {
        "auth_token": (os.getenv("TANIUM_AUTH_TOKEN") or
                       "token-"),
        "base_url_template": (os.getenv("TANIUM_BASE_URL") or
                            "https://your-tanium-server.com"),
        "timeout": int(os.getenv("TANIUM_TIMEOUT", DEFAULT_TIMEOUT)),
        "poll_interval": int(os.getenv("TANIUM_POLL_INTERVAL", DEFAULT_POLL_INTERVAL)),
        "tls_verify": os.getenv("TANIUM_TLS_VERIFY", "0") != "0",
        "tls_ca_bundle": os.getenv("TANIUM_TLS_CA_BUNDLE")
    }

    return config

# --------------------------------------------------------------------------- #
# Client Class
# ---------------------------------------------------------------------------

class TaniumClient:
    """Wrapper for Tanium API requests with automatic base URL and token handling."""

    def __init__(self, host: str, config: Optional[Dict[str, Any]] = None):
        self.host = host  # Store original host for debugging
        if config is None:
            config = load_config()

        if host.startswith("http"):
            self.base = host
        else:
            try:
                self.base = config["base_url_template"].format(host=host)
                logging.debug(f"Constructed base URL: {self.base}")
            except Exception as e:
                logging.error(f"Failed to construct base URL for host {host}: {e}")
                self.base = f"https://{host}"  # Fallback
        self.timeout = config["timeout"]
        self.poll_interval = config["poll_interval"]
        # TLS context - disabled by default for lab environments
        if config.get("tls_verify"):
            # TLS verification enabled - use proper context
            if config.get("tls_ca_bundle"):
                ca_file = config["tls_ca_bundle"]
                logging.debug(f"Using custom CA bundle: {ca_file}")
                self.context = ssl.create_default_context(cafile=ca_file)
            else:
                # Try certifi bundle first for broader CA coverage
                try:
                    import certifi  # type: ignore
                    ca_file = certifi.where()
                    logging.debug(f"Using certifi CA bundle: {ca_file}")
                    self.context = ssl.create_default_context(cafile=ca_file)
                except Exception as e:
                    logging.debug(f"certifi not available, using system CA bundle: {e}")
                    self.context = ssl.create_default_context()
            self.context.check_hostname = True
            self.context.verify_mode = ssl.CERT_REQUIRED
            logging.debug("TLS verification enabled")
        else:
            # TLS verification disabled - use unverified context
            self.context = ssl._create_unverified_context()
            logging.debug("TLS verification disabled")
        self.auth_token = config["auth_token"]
        logging.debug(f"Created TaniumClient with host: {self.host}, base URL: {self.base}")

    def _full(self, path: str) -> str:
        """Construct the full URL for a given path."""
        return f"{self.base}{path}"

    def get(self, path: str) -> bytes:
        """Perform a GET request to the Tanium API."""
        # Rate limiting: small delay between API calls
        time.sleep(0.1)

        # Audit logging
        audit_log("API_GET", {"path": path, "base_url": self.base})

        req = Request(self._full(path), headers={
            "Accept": "application/json",
            "Session": self.auth_token
        })
        logging.debug(f"GET request to: {self._full(path)}")
        attempt = 0
        backoff = 1.0
        while True:
            try:
                with urlopen(req, timeout=self.timeout, context=self.context) as resp:
                    logging.debug(f"GET {self._full(path)} returned status: {resp.getcode()}")
                    return resp.read()
            except Exception as exc:
                logging.debug(f"GET {self._full(path)} failed with exception type: {type(exc).__name__}")
                logging.debug(f"GET {self._full(path)} failed with exception: {exc}")
                # Check for HTTP 401 Unauthorized specifically
                code = getattr(exc, 'code', None)
                if code == HTTP_UNAUTHORIZED:
                    logging.error("Authentication failed: The TANIUM_AUTH_TOKEN is invalid or expired.")
                    audit_log("AUTH_FAILURE", {"path": path, "error": "Invalid or expired token"})
                    logging.error("Please check your TANIUM_AUTH_TOKEN environment variable.")
                    logging.error("You can obtain a new token from your Tanium console or API.")
                    sys.exit(1)
                # Retry on 429/5xx with backoff; honor Retry-After if present
                if code in (HTTP_TOO_MANY_REQUESTS,) + HTTP_SERVER_ERRORS and attempt < DEFAULT_MAX_RETRIES:
                    retry_after = None
                    if isinstance(exc, HTTPError) and exc.headers:
                        retry_after = exc.headers.get('Retry-After')
                    sleep_secs = float(retry_after) if retry_after else backoff
                    logging.warning(f"GET {self._full(path)} failed with {code}; retrying in {sleep_secs:.1f}s (attempt {attempt+1}/5)")
                    _time.sleep(sleep_secs)
                    attempt += 1
                    backoff = min(backoff * 2, 30)
                    continue
                logging.error(f"GET {self._full(path)} failed: {exc}")
                raise

    def post(self, path: str, data: bytes,
             conflict_header: Optional[Dict[str, Any]] = None,
             prefer_async: bool = False) -> Dict[str, Any]:
        """Perform a POST request to the Tanium API."""
        # Rate limiting: small delay between API calls
        time.sleep(0.1)

        # Audit logging
        audit_log("API_POST", {"path": path, "base_url": self.base, "prefer_async": prefer_async})

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
        redacted_headers = dict(headers)
        if "Session" in redacted_headers:
            redacted_headers["Session"] = "***REDACTED***"
        logging.debug(f"POST {self._full(path)} headers: {redacted_headers}")

        req = Request(self._full(path), data=data, headers=headers)
        logging.debug(f"POST request to: {self._full(path)} with headers: {headers}")
        attempt = 0
        backoff = 1.0
        while True:
            try:
                with urlopen(req, timeout=self.timeout, context=self.context) as resp:
                    response_data = resp.read().decode("utf-8")
                    logging.debug(f"POST {self._full(path)} returned status: {resp.getcode()}")
                    logging.debug(f"POST response data: {response_data[:200]}...")
                    return json.loads(response_data)
            except Exception as exc:
                code = getattr(exc, 'code', None)
                if code == HTTP_UNAUTHORIZED:
                    logging.error("Authentication failed: The TANIUM_AUTH_TOKEN is invalid or expired.")
                    audit_log("AUTH_FAILURE", {"path": path, "error": "Invalid or expired token"})
                    logging.error("Please check your TANIUM_AUTH_TOKEN environment variable.")
                    logging.error("You can obtain a new token from your Tanium console or API.")
                    sys.exit(1)
                if code in (HTTP_TOO_MANY_REQUESTS,) + HTTP_SERVER_ERRORS and attempt < DEFAULT_MAX_RETRIES:
                    retry_after = None
                    if isinstance(exc, HTTPError) and exc.headers:
                        retry_after = exc.headers.get('Retry-After')
                    sleep_secs = float(retry_after) if retry_after else backoff
                    logging.warning(f"POST {self._full(path)} failed with {code}; retrying in {sleep_secs:.1f}s (attempt {attempt+1}/5)")
                    _time.sleep(sleep_secs)
                    attempt += 1
                    backoff = min(backoff * 2, 30)
                    continue
                logging.error(f"POST {self._full(path)} failed: {exc}")
                if isinstance(exc, HTTPError):
                    try:
                        error_content = exc.read().decode('utf-8')
                        logging.error(f"Error response content: {error_content}")
                    except Exception:
                        pass
                raise

    def patch(self, path: str, data: bytes) -> Dict[str, Any]:
        """Perform a PATCH request to the Tanium API."""
        # Rate limiting: small delay between API calls
        time.sleep(0.1)

        # Audit logging
        audit_log("API_PATCH", {"path": path, "base_url": self.base})

        headers = {
            "Content-Type": "application/json",
            "Session": self.auth_token
        }

        req = Request(self._full(path), data=data, headers=headers, method='PATCH')
        logging.debug(f"PATCH request to: {self._full(path)}")

        attempt = 0
        backoff = 1.0
        while True:
            try:
                with urlopen(req, timeout=self.timeout, context=self.context) as resp:
                    response_data = resp.read().decode("utf-8")
                    logging.debug(f"PATCH {self._full(path)} returned status: {resp.getcode()}")
                    return json.loads(response_data)
            except Exception as exc:
                code = getattr(exc, 'code', None)
                if code == HTTP_UNAUTHORIZED:
                    logging.error("Authentication failed: The TANIUM_AUTH_TOKEN is invalid or expired.")
                    audit_log("AUTH_FAILURE", {"path": path, "error": "Invalid or expired token"})
                    logging.error("Please check your TANIUM_AUTH_TOKEN environment variable.")
                    logging.error("You can obtain a new token from your Tanium console or API.")
                    sys.exit(1)
                if code in (HTTP_TOO_MANY_REQUESTS,) + HTTP_SERVER_ERRORS and attempt < DEFAULT_MAX_RETRIES:
                    retry_after = None
                    if isinstance(exc, HTTPError) and exc.headers:
                        retry_after = exc.headers.get('Retry-After')
                    sleep_secs = float(retry_after) if retry_after else backoff
                    logging.warning(f"PATCH {self._full(path)} failed with {code}; retrying in {sleep_secs:.1f}s (attempt {attempt+1}/{DEFAULT_MAX_RETRIES})")
                    _time.sleep(sleep_secs)
                    attempt += 1
                    backoff = min(backoff * 2, 30)
                    continue
                logging.error(f"PATCH {self._full(path)} failed: {exc}")
                raise

# --------------------------------------------------------------------------- #
# Data Retrieval Functions
# ---------------------------------------------------------------------------

def fetch_api_solutions(client: TaniumClient) -> dict:
    """Fetch the list of solutions from the Tanium API (legacy; may not reflect installed)."""
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
def fetch_installed_solutions(client: TaniumClient) -> dict:
    """Fetch installed solutions from /api/v2/server_info -> Diagnostics -> Installed_Solutions.

    Returns a map: { solution_id: {"version": str, "name": str} }
    """
    try:
        logging.info("Fetching installed solutions from server_info")
        raw = client.get("/api/v2/server_info")
        data = json.loads(raw.decode("utf-8"))

        installed = data.get("data", {}).get("Diagnostics", {}).get("Installed_Solutions", {})
        sol_map = {}
        for display_name, entry in installed.items():
            sid = entry.get("id")
            ver = entry.get("version")
            name = entry.get("name") or display_name
            if sid and ver is not None:
                sol_map[sid] = {"version": ver or "", "name": name}
        logging.debug(f"Installed solutions count: {len(sol_map)}")
        return sol_map
    except Exception as exc:
        logging.error(f"Failed to fetch installed solutions: {exc}")
        raise

def _normalize_name(name: str) -> str:
    """Normalize solution/workbench names for fuzzy matching.

    - lowercase
    - remove 'tanium' prefix
    - drop parenthetical qualifiers e.g., (DEV)
    - replace non-alphanumeric with single spaces
    - collapse spaces
    """
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"\([^\)]*\)", " ", s)  # remove (...) chunks
    s = s.replace("tanium ", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def fetch_installed_effective_versions(client: TaniumClient) -> dict:
    """Return effective installed versions per solution id by reconciling Solutions and Workbenches.

    Prefers a matching Workbench version when a fuzzy name match to the Solution exists.
    Returns: { solution_id: {"version": str, "name": str} }
    """
    raw = client.get("/api/v2/server_info")
    data = json.loads(raw.decode("utf-8"))

    diag = data.get("data", {}).get("Diagnostics", {})
    installed = diag.get("Installed_Solutions", {})
    workbenches = diag.get("Installed_Workbenches", {})

    # Build normalized workbench map: normalized_name -> (display_name, version)
    norm_wb: dict[str, tuple[str, str]] = {}
    for wb_display, wb in workbenches.items():
        wb_name = wb.get("name") or wb_display
        wb_ver = wb.get("version") or ""
        norm = _normalize_name(wb_name)
        if norm:
            norm_wb[norm] = (wb_name, wb_ver)

    effective: dict[str, dict] = {}
    for disp, sol in installed.items():
        sid = sol.get("id")
        sname = sol.get("name") or disp
        sver = sol.get("version") or ""
        if not sid:
            continue

        # Attempt fuzzy match to a workbench
        norm_sol = _normalize_name(sname)

        chosen_ver = sver
        # exact normalized match
        if norm_sol in norm_wb and norm_wb[norm_sol][1]:
            chosen_ver = norm_wb[norm_sol][1]
        else:
            # try contains either direction
            # find any wb where wb_norm contained in sol_norm or vice versa
            for wb_norm, (_wb_name, wb_ver) in norm_wb.items():
                if not wb_ver:
                    continue
                if wb_norm in norm_sol or norm_sol in wb_norm:
                    chosen_ver = wb_ver
                    break

        effective[sid] = {"version": chosen_ver, "name": sname}

    logging.debug(f"Effective installed solutions (reconciled) count: {len(effective)}")
    return effective

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
                # Prefer hostname in cert SANs; strip :port from name if present
                host_only = name.split(":")[0]
                # Always use 443 for HTTPS (no custom port in URL for TLS)
                address = f"https://{host_only}"
                logging.debug(f"Server list entry: name='{name}', original_address='{server.get('address')}' -> resolved to '{address}'")
                servers.append({"name": name, "address": address})

        if not servers:
            logging.error("No servers found in server_host response")
            raise ValueError("No servers found")

        return servers
    except Exception as exc:
        logging.error(f"Failed to fetch server hosts: {exc}")
        raise

# --------------------------------------------------------------------------- #
# Global Lock Management (System Settings)
# ---------------------------------------------------------------------------

class GlobalLock:
    """Global lock using Tanium system settings to prevent concurrent imports across servers."""

    LOCK_SETTING_NAME = "tanium_compare_import_lock"
    LOCK_SETTING_DESCRIPTION = "Tanium Compare Import Lock - prevents concurrent solution imports"

    def __init__(self, client: TaniumClient):
        self.client = client
        self.setting_id = None
        self.server_name = os.uname().nodename if hasattr(os, 'uname') else "unknown"

    def acquire(self, timeout: int = 300, stale_lock_timeout: int = 1800) -> bool:
        """Acquire the global lock.

        Args:
            timeout: Maximum time to wait for lock (seconds)
            stale_lock_timeout: Time after which a lock is considered stale (seconds, default: 30 minutes)

        Returns:
            True if lock acquired, False if timeout or error
        """
        try:
            # First, try to get the existing setting
            self.setting_id = self._get_setting_id()
            if not self.setting_id:
                # Setting doesn't exist, create it with value 0 (unlocked)
                logging.info("Lock setting not found, creating it with value 0 (unlocked)")
                self.setting_id = self._create_setting()
                if not self.setting_id:
                    # If creation failed, it might be because another server created it
                    # Wait a moment and try to get it again
                    logging.debug("Setting creation failed, checking if another server created it...")
                    time.sleep(2)
                    self.setting_id = self._get_setting_id()
                    if not self.setting_id:
                        logging.error("Failed to create or find lock setting")
                        return False

            # Try to acquire the lock
            start_time = time.time()

            # Add small random delay at start to reduce collision probability
            import random
            initial_delay = random.uniform(0, 0.5)  # 0-500ms random delay
            logging.debug(f"Initial random delay: {initial_delay:.3f}s")
            time.sleep(initial_delay)

            while time.time() - start_time < timeout:
                logging.debug(f"Lock acquisition attempt (elapsed: {time.time() - start_time:.1f}s)")

                # Try to acquire the lock normally first
                if self._try_acquire_lock():
                    logging.info(f"Acquired global import lock (server: {self.server_name})")
                    audit_log("LOCK_ACQUIRED", {"server": self.server_name, "setting_id": self.setting_id})
                    return True

                # If we failed to acquire, check if it might be stale
                # First check if the lock is actually held (value = "1")
                try:
                    raw = self.client.get(f"/api/v2/system_settings/{self.setting_id}")
                    data = json.loads(raw.decode("utf-8"))
                    current_value = str(data.get("data", {}).get("value", "0"))

                    if current_value == "1" and self._is_lock_stale(stale_lock_timeout):
                        logging.warning("Detected stale lock, attempting to break and acquire atomically")
                        if self._break_stale_lock_and_acquire():
                            logging.info(f"Successfully broke stale lock and acquired it (server: {self.server_name})")
                            audit_log("LOCK_ACQUIRED", {"server": self.server_name, "setting_id": self.setting_id})
                            return True
                        else:
                            logging.debug("Failed to break stale lock and acquire atomically")
                except Exception as exc:
                    logging.debug(f"Could not check lock status: {exc}")

                logging.debug("Lock is held by another server, waiting...")
                # Add small random delay to reduce collision probability
                import random
                delay = 5 + random.uniform(0, 2)  # 5-7 seconds with some randomness
                time.sleep(delay)

            logging.warning(f"Failed to acquire lock within {timeout} seconds")
            return False

        except Exception as exc:
            logging.error(f"Failed to acquire global lock: {exc}")
            return False

    def _get_setting_id(self) -> Optional[str]:
        """Get existing setting ID only.

        Returns:
            Setting ID if found, None if not found
        """
        try:
            # Get all system settings
            raw = self.client.get("/api/v2/system_settings")
            data = json.loads(raw.decode("utf-8"))

            # Look for existing setting
            for setting in data.get("data", []):
                if setting.get("name") == self.LOCK_SETTING_NAME:
                    logging.debug(f"Found existing lock setting with ID: {setting.get('id')}")
                    return str(setting.get("id"))

            logging.debug("Lock setting not found")
            return None

        except Exception as exc:
            logging.error(f"Failed to get lock setting: {exc}")
            return None

    def _create_setting(self) -> Optional[str]:
        """Create the lock setting.

        Returns:
            Setting ID if successful, None if failed
        """
        try:
            logging.info("Creating global lock setting...")

            setting_data = json.dumps({
                "name": self.LOCK_SETTING_NAME,
                "description": self.LOCK_SETTING_DESCRIPTION,
                "default_value": "0",
                "value": "0",
                "value_type": "Numeric"
            }).encode('utf-8')

            response = self.client.post("/api/v2/system_settings", setting_data)
            setting_id = response.get("data", {}).get("id")

            if setting_id:
                logging.info(f"Successfully created lock setting with ID: {setting_id}")
                return str(setting_id)
            else:
                logging.error("Failed to create lock setting - no ID returned")
                return None

        except Exception as exc:
            logging.error(f"Failed to create lock setting: {exc}")
            return None

    def _is_lock_stale(self, stale_timeout: int) -> bool:
        """Check if the current lock is stale (held too long).

        Args:
            stale_timeout: Time in seconds after which lock is considered stale

        Returns:
            True if lock appears stale, False otherwise
        """
        try:
            raw = self.client.get(f"/api/v2/system_settings/{self.setting_id}")
            data = json.loads(raw.decode("utf-8"))
            current_value = str(data.get("data", {}).get("value", "0"))

            logging.debug(f"Lock status check: value={current_value}")

            if current_value != "1":
                logging.debug("Lock is not held (value is not 1)")
                return False  # Lock is not held

            # Check when the setting was last modified
            modified_time = data.get("data", {}).get("modified_time")
            if not modified_time:
                # If we can't determine when it was modified, assume it's not stale
                logging.debug("No modified_time available, assuming lock is not stale")
                return False

            # Parse the timestamp (assuming ISO format)
            from datetime import datetime, timezone
            try:
                modified_dt = datetime.fromisoformat(modified_time.replace('Z', '+00:00'))
                now_dt = datetime.now(timezone.utc)
                age_seconds = (now_dt - modified_dt).total_seconds()

                logging.debug(f"Lock age: {age_seconds:.0f}s, threshold: {stale_timeout}s")

                if age_seconds > stale_timeout:
                    logging.warning(f"Lock appears stale (age: {age_seconds:.0f}s, threshold: {stale_timeout}s)")
                    return True
                else:
                    logging.debug(f"Lock is not stale (age: {age_seconds:.0f}s < {stale_timeout}s)")
                    return False

            except Exception as parse_exc:
                logging.debug(f"Could not parse lock timestamp: {parse_exc}")
                return False

        except Exception as exc:
            logging.debug(f"Could not check lock staleness: {exc}")
            return False

    def _break_stale_lock(self) -> bool:
        """Attempt to break a stale lock by setting it to 0.

        Returns:
            True if lock was broken, False otherwise
        """
        try:
            logging.warning("Breaking stale lock by setting value to 0")
            patch_data = json.dumps({
                "value": "0",
                "value_type": "Numeric"
            }).encode('utf-8')

            self.client.patch(f"/api/v2/system_settings/{self.setting_id}", patch_data)

            # Verify the lock was broken
            raw = self.client.get(f"/api/v2/system_settings/{self.setting_id}")
            data = json.loads(raw.decode("utf-8"))
            new_value = str(data.get("data", {}).get("value", "0"))

            if new_value == "0":
                logging.info("Successfully broke stale lock")
                return True
            else:
                logging.warning("Failed to break stale lock")
                return False

        except Exception as exc:
            logging.error(f"Failed to break stale lock: {exc}")
            return False

    def _break_stale_lock_and_acquire(self) -> bool:
        """Atomically break a stale lock and acquire it.

        This method attempts to break a stale lock and immediately acquire it
        to prevent race conditions.

        Returns:
            True if lock was broken and acquired, False otherwise
        """
        try:
            # First, verify the lock is still stale (double-check)
            if not self._is_lock_stale(1800):  # Use 30 minutes as default
                logging.debug("Lock is no longer stale, skipping break and acquire")
                return False

            logging.warning("Atomically breaking stale lock and acquiring it")

            # Step 1: Break the stale lock
            patch_data = json.dumps({
                "value": "0",
                "value_type": "Numeric"
            }).encode('utf-8')

            self.client.patch(f"/api/v2/system_settings/{self.setting_id}", patch_data)

            # Step 2: Immediately try to acquire it (with minimal delay)
            time.sleep(0.1)  # Very small delay to ensure the patch is processed

            # Use the same simple approach as _try_acquire_lock
            acquire_data = json.dumps({
                "value": "1",
                "value_type": "Numeric"
            }).encode('utf-8')

            self.client.patch(f"/api/v2/system_settings/{self.setting_id}", acquire_data)

            # If we got here without an exception, we successfully acquired the lock
            logging.info("Successfully broke stale lock and acquired it atomically")
            return True

        except Exception as exc:
            logging.error(f"Failed to break stale lock and acquire atomically: {exc}")
            return False

    def release(self) -> None:
        """Release the global lock."""
        if not self.setting_id:
            return

        try:
            # Set lock value to 0 (unlocked)
            patch_data = json.dumps({
                "value": "0",
                "value_type": "Numeric"
            }).encode('utf-8')

            self.client.patch(f"/api/v2/system_settings/{self.setting_id}", patch_data)
            logging.info(f"Released global import lock (server: {self.server_name})")
            audit_log("LOCK_RELEASED", {"server": self.server_name, "setting_id": self.setting_id})

        except Exception as exc:
            logging.error(f"Failed to release global lock: {exc}")


    def _try_acquire_lock(self) -> bool:
        """Try to acquire the lock using a more robust approach.

        Since the Tanium API doesn't support true compare-and-swap, we'll use
        a combination of immediate retry and exponential backoff to handle race conditions.

        Returns:
            True if lock acquired, False if already held
        """
        import time
        import random

        # Try multiple times with exponential backoff to handle race conditions
        max_attempts = 3
        base_delay = 0.1  # Start with 100ms

        for attempt in range(max_attempts):
            try:
                # Get current value
                raw = self.client.get(f"/api/v2/system_settings/{self.setting_id}")
                data = json.loads(raw.decode("utf-8"))
                current_value = str(data.get("data", {}).get("value", "0"))

                logging.debug(f"Attempting to acquire lock (attempt {attempt + 1}/{max_attempts}): current_value={current_value}")

                if current_value == "1":
                    # Lock is already held - stop trying
                    logging.debug(f"Lock is already held by another server (value: {current_value})")
                    return False

                # Try to set lock to 1
                patch_data = json.dumps({
                    "value": "1",
                    "value_type": "Numeric"
                }).encode('utf-8')

                logging.debug(f"Setting lock to 1 (server: {self.server_name}, attempt {attempt + 1})")

                try:
                    self.client.patch(f"/api/v2/system_settings/{self.setting_id}", patch_data)

                    # Verify we actually got the lock by checking the value again
                    time.sleep(0.05)  # Small delay to ensure the patch is processed
                    raw = self.client.get(f"/api/v2/system_settings/{self.setting_id}")
                    data = json.loads(raw.decode("utf-8"))
                    final_value = str(data.get("data", {}).get("value", "0"))

                    if final_value == "1":
                        logging.info(f"Successfully acquired lock (server: {self.server_name})")
                        return True
                    else:
                        logging.debug(f"Lock acquisition failed - value changed to: {final_value} (race condition)")
                        if attempt < max_attempts - 1:
                            # Exponential backoff with jitter
                            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                            logging.debug(f"Retrying in {delay:.3f}s...")
                            time.sleep(delay)
                            continue
                        else:
                            return False

                except Exception as patch_exc:
                    # If the patch failed, it likely means another server modified the setting
                    logging.debug(f"Lock acquisition failed due to race condition: {patch_exc}")
                    if attempt < max_attempts - 1:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                        logging.debug(f"Retrying in {delay:.3f}s...")
                        time.sleep(delay)
                        continue
                    else:
                        return False

            except Exception as exc:
                logging.debug(f"Failed to acquire lock (attempt {attempt + 1}): {exc}")
                if attempt < max_attempts - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                    logging.debug(f"Retrying in {delay:.3f}s...")
                    time.sleep(delay)
                    continue
                else:
                    return False

        return False

# --------------------------------------------------------------------------- #
# Import Functions
# ---------------------------------------------------------------------------

def import_solution(client: TaniumClient, solution_id: str, content_url: str, conflict_policy_path: Optional[str] = None, conflict_default: str = "replace") -> dict:
    if not client.base:
        raise ValueError(f"Client for {client.host} has no base URL set")

    try:
        # Content fetching with headers similar to curl
        content_headers = {
            "Accept": "*/*",
            "User-Agent": "curl/7.64.1",
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip, deflate"
        }
        logging.debug(f"Content fetch headers: {content_headers}")
        req = Request(content_url, headers=content_headers)

        # Debug output to see exactly what we're sending
        import pprint
        logging.debug(f"Final request headers: {pprint.pformat(req.headers)}")

        with urlopen(req, timeout=client.timeout, context=client.context) as resp:
            if resp.getcode() != 200:
                raise ConnectionError(f"HTTP {resp.getcode()} fetching content")

            # Read the response with encoding information
            content_data = resp.read()

            # Check if this is gzipped content (common for compressed responses)
            # Try decompressing if it looks like gzip
            try:
                with gzip.GzipFile(fileobj=BytesIO(content_data)) as f:
                    decompressed_data = f.read()
                    logging.debug(f"Decompressed {len(decompressed_data)} bytes")
                    content_preview = decompressed_data[:200].decode("utf-8", errors="replace")
                    logging.debug(f"Decompressed content preview: {content_preview}")
                    content_data = decompressed_data
            except Exception as e:
                logging.debug(f"Not gzipped content or decompression failed: {e}")
                # Log the raw content type and first few bytes
                logging.debug(f"Content type: {resp.headers.get('Content-Type')}")
                if len(content_data) > 0:
                    logging.debug(f"First 20 bytes of content: {content_data[:20]}")
                else:
                    logging.debug("Content is empty")

            # Verify we have XML content
            try:
                content_preview = content_data[:200].decode("utf-8", errors="replace")
                if "<" not in content_preview:  # Basic check for XML
                    raise ValueError("Content doesn't appear to be XML")
                logging.debug(f"Valid content preview: {content_preview}")
            except Exception as e:
                logging.error(f"Content doesn't appear to be valid XML: {e}")
                raise

            # Prepare import request - First phase: analyze conflicts
            conflict_header = {"import_analyze_conflicts_only": 1}
            import_path = "/api/v2/import"
            logging.debug(f"Constructing URL for path {import_path} on base {client.base}")
            import_url = client._full(import_path)

            if not import_url:
                raise ValueError(f"Could not construct import URL for {client.host}")

            logging.info(f"Preparing to POST to: {import_url}")
            headers = {
                "Content-Type": "application/xml",
                "Session": client.auth_token,
                "tanium-options": json.dumps(conflict_header)
            }
            logging.debug(f"Request headers: {headers}")
            req = Request(import_url, data=content_data, headers=headers)

            # Execute first request to analyze conflicts
            with urlopen(req, timeout=client.timeout, context=client.context) as resp:
                response_data = resp.read().decode("utf-8")
                logging.debug(f"First POST response: {response_data[:500]}")
                first_response = json.loads(response_data)

                # Extract conflict details
                import_conflict_details = []
                if "data" in first_response and "object_list" in first_response["data"]:
                    object_list = first_response["data"]["object_list"]
                    if "import_conflict_details" in object_list:
                        import_conflict_details = object_list["import_conflict_details"]

                # Build conflict resolution options
                # Strategy:
                # - For each conflict, set action to 1 (replace) unless permission_denied
                # - Provide a per-type default of 1 as a safety net
                # - Set global default_import_conflict_option based on conflict_default
                conflict_options_by_type_and_name = {}
                conflict_options_by_type = {}
                if import_conflict_details:
                    for detail in import_conflict_details:
                        obj_type = detail.get("type", "unknown")
                        obj_name = detail.get("name", "unknown")
                        perm_denied = detail.get("permission_denied", False)

                        # If we cannot modify this object, skip replacing it explicitly
                        # but keep a per-type default below; log for visibility
                        if perm_denied:
                            logging.warning(f"Permission denied for conflict {obj_type}:{obj_name}; leaving to defaults")
                            continue

                        conflict_options_by_type_and_name.setdefault(obj_type, {})[obj_name] = CONFLICT_OPTION_REPLACE
                        # Also set a per-type default to replace
                        conflict_options_by_type[obj_type] = CONFLICT_OPTION_REPLACE

                # Merge external conflict policy file if provided
                if conflict_policy_path and os.path.isfile(conflict_policy_path):
                    try:
                        with open(conflict_policy_path, "r", encoding="utf-8") as f:
                            policy = json.load(f)
                        by_type = policy.get("import_conflict_options_by_type", {})
                        by_type_and_name = policy.get("import_conflict_options_by_type_and_name", {})
                        for t, action in by_type.items():
                            conflict_options_by_type[t] = action
                        for t, names in by_type_and_name.items():
                            conflict_options_by_type_and_name.setdefault(t, {}).update(names)
                        logging.info("Merged external conflict policy")
                    except Exception as e:
                        logging.warning(f"Failed to read conflict policy file {conflict_policy_path}: {e}")

                # Prepare second request - actually import with conflict resolution
                if conflict_options_by_type_and_name or conflict_options_by_type:
                    # Build the complete tanium-options header with conflict resolution
                    final_conflict_header = {
                        "import_conflict_options_by_type_and_name": conflict_options_by_type_and_name or {},
                        "import_conflict_options_by_type": conflict_options_by_type or {},
                        "default_import_conflict_option": CONFLICT_OPTION_REPLACE if conflict_default == "replace" else CONFLICT_OPTION_SKIP
                    }
                else:
                    # If no conflicts, apply requested default
                    final_conflict_header = {"default_import_conflict_option": CONFLICT_OPTION_REPLACE if conflict_default == "replace" else CONFLICT_OPTION_SKIP}

                logging.debug(f"Final conflict resolution options: {final_conflict_header}")

                # Second request - actually perform the import asynchronously
                headers["tanium-options"] = json.dumps(final_conflict_header)
                headers["Prefer"] = "respond-async"
                req = Request(import_url, data=content_data, headers=headers)

                # Execute second request to initiate async import
                with urlopen(req, timeout=client.timeout, context=client.context) as resp:
                    response_data = resp.read().decode("utf-8")
                    logging.debug(f"Second POST response (async kickoff): {response_data[:500]}")
                    kickoff = json.loads(response_data)

                # Extract import ID and poll status
                import_id = None
                try:
                    import_id = kickoff.get("data", {}).get("id")
                except Exception:
                    pass

                if not import_id:
                    raise ValueError("Async import did not return an import id")

                logging.info(f"Async import started with id {import_id}; polling for completion")

                # Poll /api/v2/import/{id} every poll_interval seconds up to timeout
                poll_path = f"/api/v2/import/{import_id}"
                deadline = time.time() + DEFAULT_IMPORT_TIMEOUT
                last_payload = None
                while time.time() < deadline:
                    try:
                        raw_status = client.get(poll_path)
                        last_payload = json.loads(raw_status.decode("utf-8"))
                        logging.debug(f"Poll response: {str(last_payload)[:500]}")
                        data_obj = last_payload.get("data", {})
                        if data_obj.get("success") is True:
                            logging.info(f"Import {import_id} completed successfully")
                            return last_payload
                    except Exception as poll_exc:
                        logging.warning(f"Polling import {import_id} failed once: {poll_exc}")
                    time.sleep(client.poll_interval)

                # Timed out
                logging.error(f"Import {import_id} did not complete within 10 minutes")
                if last_payload is not None:
                    return last_payload
                raise TimeoutError(f"Import {import_id} timed out with no status payload")

    except Exception as exc:
        # Detailed error handling
        if isinstance(exc, HTTPError):
            logging.error(f"HTTP {exc.code} when importing solution {solution_id}")
            # Try to get more context from the response
            try:
                error_content = exc.read().decode('utf-8')
                logging.error(f"Error response: {error_content[:500]}")
            except Exception as e:
                logging.debug(f"Could not read error response: {e}")
        else:
            logging.error(f"Unknown error importing solution {solution_id}: {exc}")

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
        # Use reconciled effective versions (Solutions vs Workbenches)
        sol_map = fetch_installed_effective_versions(client)
        logging.info(f"Server reports {len(sol_map)} effective installed solutions")

        results = {
            "out_of_date": [],
            "missing": [],
            "up_to_date": []
        }

        for sid, ver_info in manifest.items():
            ver = ver_info.get("version", "")
            name = ver_info.get("name", f"Unknown Solution ({sid})")
            if sid not in sol_map:
                logging.info(f"[MISSING] Solution {sid} ({name}) (version {ver}) not found in API")
                results["missing"].append({"sid": sid, "version": ver, "name": name})
            else:
                api_ver = sol_map[sid].get("version", "")
                if api_ver != ver:
                    logging.info(f"[OUT-OF-DATE] Solution {sid} ({name}) (API version: {api_ver}, Manifest: {ver})")
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
# Security Functions
# ---------------------------------------------------------------------------

def validate_file_path(file_path: str, allowed_dirs: Optional[List[str]] = None) -> bool:
    """Validate file path to prevent path traversal attacks.

    Args:
        file_path: Path to validate
        allowed_dirs: List of allowed parent directories (optional)

    Returns:
        True if path is safe, False otherwise
    """
    if not file_path:
        return False

    # Check for path traversal attempts
    if ".." in file_path:
        logging.warning(f"Path traversal attempt detected: {file_path}")
        return False

    # Normalize the path
    normalized_path = os.path.normpath(file_path)

    # Check if normalized path contains any parent directory references
    if ".." in normalized_path:
        logging.warning(f"Path traversal in normalized path: {normalized_path}")
        return False

    # If allowed_dirs specified, check if path is within allowed directories
    if allowed_dirs:
        for allowed_dir in allowed_dirs:
            if normalized_path.startswith(allowed_dir):
                return True
        logging.warning(f"Path not in allowed directories: {normalized_path}")
        return False

    return True

def secure_file_permissions(file_path: str) -> None:
    """Set secure file permissions on a file.

    Args:
        file_path: Path to the file to secure
    """
    try:
        if os.path.exists(file_path):
            # Set restrictive permissions: owner read/write only
            os.chmod(file_path, 0o600)
            logging.debug(f"Set secure permissions (600) on {file_path}")
    except Exception as e:
        logging.warning(f"Failed to set secure permissions on {file_path}: {e}")

def audit_log(operation: str, details: Optional[Dict[str, Any]] = None) -> None:
    """Log security-relevant operations for audit purposes.

    Args:
        operation: Type of operation being performed
        details: Additional details to log
    """
    user = os.getenv('USER', 'unknown')
    hostname = os.uname().nodename if hasattr(os, 'uname') else 'unknown'
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())

    audit_msg = f"AUDIT: {operation} by {user}@{hostname} at {timestamp}"
    if details:
        # Redact sensitive information
        safe_details = {}
        for key, value in details.items():
            if any(sensitive in key.lower() for sensitive in ['token', 'password', 'secret', 'key']):
                safe_details[key] = "[REDACTED]"
            else:
                safe_details[key] = value
        audit_msg += f" - {safe_details}"

    logging.info(audit_msg)

# --------------------------------------------------------------------------- #
# Helper Functions
# ---------------------------------------------------------------------------

def print_tanium_logo() -> None:
    """Print the Tanium logo."""
    print("""
    ++++++++++
 +++++++++++++++
++++++++++++++++++   ++++++++++++    +++++      ++++++    ++++  ++++  ++++     ++++  ++++++     ++++++
+++++++++++++++++++  ++++++++++++   +++++++     +++++++   ++++  ++++  ++++     ++++  +++++++    ++++++
++++++                   ++++      +++   +++    +++++++++ ++++  ++++  ++++     ++++  ++++++++ ++++++++
+++++++++++  ++++++      ++++     +++++++++++   ++++ +++++++++  ++++  ++++     ++++  +++++++++++++++++
+++++++++++  +++++       ++++   ++++++++++++++  ++++   +++++++  ++++  +++++++++++++  ++++  ++++++ ++++
 ++++++++++  +++         ++++  +++++       ++++ ++++    ++++++  ++++   +++++++++++   ++++   +++   ++++
    +++++++
    """)

def validate_manifest(manifest: dict, strict: bool = False) -> None:
    """Validate manifest data and raise errors if invalid.

    Args:
        manifest: Dictionary containing manifest data
        strict: If True, fail on missing required fields

    Raises:
        SystemExit: If validation fails and strict=True
    """
    if not strict:
        return

    errors = []
    for sid, entry in manifest.items():
        if not entry.get("version"):
            errors.append(f"Manifest entry {sid} missing version")
        if "content_url" not in entry:
            errors.append(f"Manifest entry {sid} missing content_url")

    if errors:
        for e in errors:
            logging.error(e)
        sys.exit(1)

def print_comparison_summary(server_results: Dict[str, Dict[str, Any]],
                           inconsistencies: Dict[str, Any]) -> None:
    """Print a formatted summary of comparison results.

    Args:
        server_results: Results from each server comparison
        inconsistencies: Inconsistencies found between servers
    """
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


# --------------------------------------------------------------------------- #
# Main Execution
# ---------------------------------------------------------------------------

def main():
    """Main function to execute the comparison.

    The comparison happens in two phases:
    1. Each server compared against the manifest
    2. Servers compared against each other to detect inconsistencies
    """
    # Only print logo if running interactively (not in cron)
    if sys.stdout.isatty():
        print_tanium_logo()

    # Global lock will be acquired later when we have a client
    global_lock = None

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Compare Tanium solutions against manifest")
    parser.add_argument("--manifest-url", help="URL to the manifest file (optional)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Logging level")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds")
    parser.add_argument("--import-out-of-date", action="store_true", help="Import out-of-date solutions")
    parser.add_argument("--import-missing", action="store_true", help="Import missing solutions (new solutions that have never been imported)")
    parser.add_argument("--dry-run", action="store_true", help="Plan actions but do not execute imports")
    # Reconciled behavior is always used; flag removed
    parser.add_argument("--conflict-default", default="replace", choices=["replace", "skip"], help="Default conflict behavior for unhandled items")
    parser.add_argument("--tls-verify", choices=["0","1"], default="0", help="Override TLS verification (1=verify, 0=disable, default=0)")
    parser.add_argument("--tls-ca-bundle", help="Path to CA bundle for TLS verification (ignored when tls-verify=0)")
    parser.add_argument("--strict-manifest", action="store_true", help="Fail if manifest entries are missing required fields")
    parser.add_argument("--conflict-policy", help="Path to JSON file defining conflict options per type/name")
    parser.add_argument("--max-compare-concurrency", type=int, default=DEFAULT_MAX_CONCURRENCY, help="Max concurrent server comparisons")
    parser.add_argument("--summary-out", help="Write JSON summary to this path")
    parser.add_argument("--name-map", help="Path to JSON name override map for Solution↔Workbench")
    parser.add_argument("--log-file", help="Write logs to specified file (default: console only)")
    parser.add_argument("--global-lock-timeout", type=int, default=300, help="Global lock timeout in seconds (default: 300)")
    parser.add_argument("--stale-lock-timeout", type=int, default=1800, help="Time after which a lock is considered stale (seconds, default: 1800)")
    parser.add_argument("--skip-global-lock", action="store_true", help="Skip global lock acquisition (for testing)")
    parser.add_argument("--create-lock-setting", action="store_true", help="Create the global lock setting and exit (utility function)")
    parser.add_argument("--check-lock-status", action="store_true", help="Check the current lock status and exit")

    args = parser.parse_args()

    # Set up logging - use different formats for interactive vs cron
    if sys.stdout.isatty():
        # Interactive mode - more detailed format
        log_format = '%(asctime)s - %(levelname)s - %(message)s'
    else:
        # Cron mode - simpler format, include process info
        log_format = '%(asctime)s - %(process)d - %(levelname)s - %(message)s'

    # Set up handlers - console always, file only if specified
    handlers = [logging.StreamHandler(sys.stdout)]

    # Add file handler if log file is specified
    if hasattr(args, 'log_file') and args.log_file:
        # Validate log file path for security
        if not validate_file_path(args.log_file, allowed_dirs=['/var/log', '/tmp']):
            logging.error(f"Invalid log file path: {args.log_file}")
            sys.exit(1)

        try:
            # Ensure directory exists
            log_dir = os.path.dirname(args.log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            handlers.append(logging.FileHandler(args.log_file, mode='a'))
            # Set secure permissions on log file
            secure_file_permissions(args.log_file)
        except (PermissionError, OSError) as e:
            logging.warning(f"Could not create log file {args.log_file}: {e}")
            logging.warning("Continuing with console output only")

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format=log_format,
        handlers=handlers
    )

    # Load configuration
    config = load_config()
    if args.timeout:
        config["timeout"] = args.timeout
    if args.tls_verify is not None:
        config["tls_verify"] = args.tls_verify == "1"
    if args.tls_ca_bundle:
        config["tls_ca_bundle"] = args.tls_ca_bundle

    # Validate configuration
    if config["base_url_template"] == "https://your-tanium-server.com":
        logging.error("ERROR: TANIUM_BASE_URL not configured!")
        logging.error("Please set the TANIUM_BASE_URL environment variable to your Tanium server URL.")
        logging.error("Example: export TANIUM_BASE_URL=https://your-tanium-server.com")
        sys.exit(1)

    if config["auth_token"] == "token-":
        logging.error("ERROR: TANIUM_AUTH_TOKEN not configured!")
        logging.error("Please set the TANIUM_AUTH_TOKEN environment variable to your Tanium API token.")
        logging.error("Example: export TANIUM_AUTH_TOKEN=your-token-here")
        sys.exit(1)

    # Get the list of servers from the primary server
    try:
        primary_client = TaniumClient(config["base_url_template"], config)
        servers = get_server_hosts(primary_client)
        logging.info(f"Found {len(servers)} servers: {[s['name'] for s in servers]}")
    except Exception as exc:
        logging.error(f"Failed to get server list: {exc}")
        sys.exit(1)

    # Handle create lock setting option
    if args.create_lock_setting:
        try:
            global_lock = GlobalLock(primary_client)

            # First check if it already exists
            existing_id = global_lock._get_setting_id()
            if existing_id:
                logging.info(f"Lock setting already exists with ID: {existing_id}")
                print(f"Lock setting already exists with ID: {existing_id}")
                sys.exit(0)

            # Create it if it doesn't exist
            setting_id = global_lock._create_setting()
            if setting_id:
                logging.info(f"Successfully created lock setting with ID: {setting_id}")
                print(f"Lock setting created with ID: {setting_id}")
                sys.exit(0)
            else:
                logging.error("Failed to create lock setting")
                sys.exit(1)
        except Exception as exc:
            logging.error(f"Failed to create lock setting: {exc}")
            sys.exit(1)

    # Handle check lock status option
    if args.check_lock_status:
        try:
            global_lock = GlobalLock(primary_client)
            setting_id = global_lock._get_setting_id()
            if not setting_id:
                logging.info("Lock setting not found")
                print("Lock setting not found")
                sys.exit(1)

            # Get current lock value
            raw = primary_client.get(f"/api/v2/system_settings/{setting_id}")
            data = json.loads(raw.decode("utf-8"))
            current_value = str(data.get("data", {}).get("value", "0"))

            if current_value == "1":
                logging.info("Lock is currently HELD (value: 1)")
                print("Lock is currently HELD (value: 1)")
            else:
                logging.info("Lock is currently FREE (value: 0)")
                print("Lock is currently FREE (value: 0)")

            sys.exit(0)
        except Exception as exc:
            logging.error(f"Failed to check lock status: {exc}")
            sys.exit(1)

    # Ensure global lock setting exists (create if needed)
    if not args.skip_global_lock:
        try:
            global_lock = GlobalLock(primary_client)
            setting_id = global_lock._get_setting_id()
            if not setting_id:
                # Setting doesn't exist, create it with value 0 (unlocked)
                logging.info("Lock setting not found, creating it with value 0 (unlocked)")
                setting_id = global_lock._create_setting()
                if not setting_id:
                    logging.error("Failed to create lock setting")
                    sys.exit(1)
                logging.info(f"Successfully created lock setting with ID: {setting_id}")
            else:
                logging.debug(f"Lock setting already exists with ID: {setting_id}")
        except Exception as exc:
            logging.error(f"Failed to ensure lock setting exists: {exc}")
            sys.exit(1)
    else:
        logging.warning("Skipping global lock setup (--skip-global-lock specified)")

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
        validate_manifest(manifest, args.strict_manifest)
        logging.info(f"Manifest has {len(manifest)} solutions")
    except Exception as exc:
        logging.error(f"Failed to fetch manifest: {exc}")
        sys.exit(1)

    # Phase 1: Compare each server against the manifest
    server_results = {}
    server_clients = {}  # Keep track of server clients for imports

    # Optional name-map for matching tweaks
    name_map = {}
    if args.name_map and os.path.isfile(args.name_map):
        try:
            with open(args.name_map, "r", encoding="utf-8") as f:
                name_map = json.load(f)
            logging.info("Loaded name-map overrides")
        except Exception as e:
            logging.warning(f"Failed to read name-map file {args.name_map}: {e}")

    # Ctrl+C handling for graceful stop with double-kill
    stop_flag = {"stop": False, "kill_count": 0}
    def _handle_sigint(signum, frame):
        stop_flag["kill_count"] += 1
        if stop_flag["kill_count"] == 1:
            stop_flag["stop"] = True
            logging.warning("Interrupt received; will stop after current operation")
            logging.warning("Press Ctrl+C again to force kill")
        elif stop_flag["kill_count"] >= 2:
            logging.error("Force kill requested - exiting immediately")
            sys.exit(1)
    signal.signal(signal.SIGINT, _handle_sigint)

    # Concurrent comparisons
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def _compare_one(server):
        name = server["name"]
        addr = server["address"]
        logging.info(f"Processing server: {name} ({addr})")
        try:
            client = TaniumClient(addr, config)
            server_clients[name] = client
            sol_map = fetch_installed_effective_versions(client)
            results = {"out_of_date": [], "missing": [], "up_to_date": []}
            for sid, ver_info in manifest.items():
                if stop_flag["stop"]:
                    logging.warning(f"Stop signal received, breaking comparison loop for {name}")
                    break
                ver = ver_info.get("version", "")
                nm = ver_info.get("name", f"Unknown Solution ({sid})")
                # Apply optional name-map (for display only)
                if nm in name_map:
                    nm = name_map[nm]
                if sid not in sol_map:
                    logging.info(f"[MISSING] {name}: Solution {sid} ({nm}) (version {ver}) not found in installed source")
                    results["missing"].append({"sid": sid, "version": ver, "name": nm})
                else:
                    installed_ver = sol_map[sid].get("version", "")
                    if installed_ver != ver:
                        logging.info(f"[OUT-OF-DATE] {name}: Solution {sid} ({nm}) (Installed: {installed_ver}, Manifest: {ver})")
                        results["out_of_date"].append({"sid": sid, "api_version": installed_ver, "manifest_version": ver, "name": nm})
                    else:
                        results["up_to_date"].append({"sid": sid, "version": ver, "name": nm})
            return name, results
        except Exception as exc:
            logging.error(f"Failed to compare server {name}: {exc}")
            return name, {"out_of_date": [], "missing": [], "up_to_date": []}

    with ThreadPoolExecutor(max_workers=max(1, args.max_compare_concurrency)) as pool:
        futures = [pool.submit(_compare_one, s) for s in servers]
        for fut in as_completed(futures):
            if stop_flag["stop"]:
                logging.warning("Stop signal received, cancelling remaining comparisons")
                # Cancel any remaining futures
                for f in futures:
                    f.cancel()
                break
            name, results = fut.result()
            server_results[name] = results

    # Remove legacy sequential comparison loop (now handled above)

    # Phase 2: Compare servers against each other
    inconsistencies = compare_servers(server_results)

    # Display results
    print_comparison_summary(server_results, inconsistencies)

    # Initialize import statistics (used for final combined summary)
    import_stats = {
        "total_attempted": 0,
        "total_successful": 0,
        "total_skipped": 0,
        "total_failed": 0,
        "servers_processed": 0,
        "servers_skipped": 0
    }
    missing_import_stats = {
        "total_attempted": 0,
        "total_successful": 0,
        "total_skipped": 0,
        "total_failed": 0,
        "servers_processed": 0,
        "servers_skipped": 0
    }

    # If --import-out-of-date flag is set, import the out-of-date solutions
    if args.import_out_of_date:
        print("\n=== IMPORTING OUT-OF-DATE SOLUTIONS ===")

        # Import each out-of-date solution on each server where it is out-of-date
        total_targets = sum(len(results["out_of_date"]) for results in server_results.values())
        print(f"Queued {total_targets} server-specific imports based on manifest deltas")

        for server_name, results in server_results.items():
            if not results["out_of_date"]:
                continue
            client = server_clients.get(server_name)
            if client is None or not client.base:
                logging.error(f"Server client not available for {server_name}")
                continue

            # Test client connectivity once per server (use server_info)
            try:
                test_url = client._full("/api/v2/server_info")
                logging.debug(f"Testing client with GET {test_url}")
                raw = client.get("/api/v2/server_info")
                if not raw:
                    logging.error(f"Test GET to {test_url} returned empty response")
                    continue
                data = json.loads(raw.decode("utf-8"))
                if not data.get("data"):
                    logging.error(f"Test GET to {test_url} returned no data")
                    continue
            except Exception as exc:
                logging.error(f"Test GET failed for {server_name}: {exc}")
                continue

            # Acquire global lock for this server's imports
            server_global_lock = None
            if not args.dry_run and not args.skip_global_lock:
                try:
                    # Use the primary client for the global lock (shared across all servers)
                    server_global_lock = GlobalLock(primary_client)
                    logging.info(f"Attempting to acquire global import lock for {server_name}...")
                    if not server_global_lock.acquire(timeout=args.global_lock_timeout, stale_lock_timeout=args.stale_lock_timeout):
                        logging.error(f"Could not acquire global import lock for {server_name} within {args.global_lock_timeout} seconds.")
                        logging.error("Another server may be running imports. Skipping imports for this server.")
                        continue

                    # Register cleanup function for this server
                    def cleanup_outofdate_lock():
                        if server_global_lock:
                            try:
                                server_global_lock.release()
                                logging.info(f"Released global import lock for {server_name}")
                            except Exception as cleanup_exc:
                                logging.error(f"Error releasing lock for {server_name}: {cleanup_exc}")

                    atexit.register(cleanup_outofdate_lock)
                    logging.info(f"Successfully acquired global import lock for {server_name}")

                except Exception as lock_exc:
                    logging.error(f"Failed to set up global lock for {server_name}: {lock_exc}")
                    logging.error("Skipping imports for this server due to lock setup failure")
                    import_stats["servers_skipped"] += 1
                    continue

            # Track this server's imports
            server_imports_attempted = 0
            server_imports_successful = 0
            server_imports_skipped = 0
            server_imports_failed = 0

            for solution in results["out_of_date"]:
                # Check for stop signal before each import
                if stop_flag["stop"]:
                    logging.warning(f"Stop signal received, skipping remaining imports for {server_name}")
                    break

                sid = solution["sid"]
                name = solution["name"]
                manifest_version = solution["manifest_version"]
                api_version = solution["api_version"]

                print(f"Importing solution {sid} ({name}) on {server_name} - Installed: {api_version} -> Manifest: {manifest_version}")

                if args.dry_run:
                    print(f"  [DRY-RUN] Would import {sid} on {server_name}")
                    server_imports_attempted += 1
                    server_imports_successful += 1  # Count dry run as successful
                    continue

                server_imports_attempted += 1
                import_stats["total_attempted"] += 1

                # Re-check installed version just before import (idempotency)
                try:
                    current_map = fetch_installed_effective_versions(client)
                    current_ver = current_map.get(sid, {}).get("version")
                    if current_ver == manifest_version:
                        print(f"  Skipping {sid} on {server_name}: already at manifest version")
                        server_imports_skipped += 1
                        import_stats["total_skipped"] += 1
                        continue
                except Exception:
                    pass

                try:
                    import_solution(client, sid, manifest[sid]["content_url"], conflict_policy_path=args.conflict_policy, conflict_default=args.conflict_default)
                    print(f"  Import successful for {sid} on server {server_name}")
                    server_imports_successful += 1
                    import_stats["total_successful"] += 1
                except Exception as exc:
                    print(f"  Import failed for {sid} on server {server_name}: {exc}")
                    server_imports_failed += 1
                    import_stats["total_failed"] += 1

            # Track server completion
            import_stats["servers_processed"] += 1
            print(f"\n📊 Server {server_name} import summary:")
            print(f"  Attempted: {server_imports_attempted}")
            print(f"  Successful: {server_imports_successful}")
            print(f"  Skipped: {server_imports_skipped} (already up-to-date)")
            print(f"  Failed: {server_imports_failed}")

            # Release global lock for this server after all imports are complete
            if server_global_lock:
                server_global_lock.release()
                logging.info(f"Released global import lock for {server_name}")

        # Print final import statistics
        if import_stats["total_attempted"] > 0:
            print("\n🎯 FINAL IMPORT STATISTICS:")
            print(f"  Servers processed: {import_stats['servers_processed']}")
            print(f"  Servers skipped: {import_stats['servers_skipped']}")
            print(f"  Total imports attempted: {import_stats['total_attempted']}")
            print(f"  Total imports successful: {import_stats['total_successful']}")
            print(f"  Total imports skipped: {import_stats['total_skipped']} (already up-to-date)")
            print(f"  Total imports failed: {import_stats['total_failed']}")
            # Calculate success rate including skipped as successful (reached desired state)
            effective_success = import_stats['total_successful'] + import_stats['total_skipped']
            success_rate = (effective_success / import_stats['total_attempted']) * 100
            print(f"  Success rate: {success_rate:.1f}% ({effective_success}/{import_stats['total_attempted']})")

    # If --import-missing flag is set, import the missing solutions
    if args.import_missing:
        print("\n=== IMPORTING MISSING SOLUTIONS ===")

        # Import each missing solution on each server where it is missing
        total_targets = sum(len(results["missing"]) for results in server_results.values())
        print(f"Queued {total_targets} server-specific imports for missing solutions")

        for server_name, results in server_results.items():
            if not results["missing"]:
                continue
            client = server_clients.get(server_name)
            if client is None or not client.base:
                logging.error(f"Server client not available for {server_name}")
                continue

            # Test client connectivity once per server (use server_info)
            try:
                test_url = client._full("/api/v2/server_info")
                logging.debug(f"Testing client with GET {test_url}")
                raw = client.get("/api/v2/server_info")
                if not raw:
                    logging.error(f"Test GET to {test_url} returned empty response")
                    continue
                data = json.loads(raw.decode("utf-8"))
                if not data.get("data"):
                    logging.error(f"Test GET to {test_url} returned no data")
                    continue
            except Exception as exc:
                logging.error(f"Test GET failed for {server_name}: {exc}")
                continue

            # Acquire global lock for this server's imports
            server_global_lock = None
            if not args.dry_run and not args.skip_global_lock:
                try:
                    # Use the primary client for the global lock (shared across all servers)
                    server_global_lock = GlobalLock(primary_client)
                    logging.info(f"Attempting to acquire global import lock for {server_name}...")
                    if not server_global_lock.acquire(timeout=args.global_lock_timeout, stale_lock_timeout=args.stale_lock_timeout):
                        logging.error(f"Could not acquire global import lock for {server_name} within {args.global_lock_timeout} seconds.")
                        logging.error("Another server may be running imports. Skipping imports for this server.")
                        continue

                    # Register cleanup function for this server
                    def cleanup_missing_lock():
                        if server_global_lock:
                            try:
                                server_global_lock.release()
                                logging.info(f"Released global import lock for {server_name}")
                            except Exception as exc:
                                logging.error(f"Failed to release global import lock for {server_name}: {exc}")

                    atexit.register(cleanup_missing_lock)
                    logging.info(f"Successfully acquired global import lock for {server_name}")
                except Exception as exc:
                    logging.error(f"Failed to acquire global import lock for {server_name}: {exc}")
                    continue

            # Track server-specific import statistics
            server_imports_attempted = 0
            server_imports_successful = 0
            server_imports_skipped = 0
            server_imports_failed = 0

            # Import each missing solution for this server
            for solution in results["missing"]:
                if stop_flag["stop"]:
                    break

                solution_id = solution["sid"]
                solution_name = solution["name"]
                solution_version = solution["version"]

                logging.info(f"Importing missing solution {solution_id} ({solution_name}) on {server_name} - Version: {solution_version}")

                if args.dry_run:
                    logging.info(f"[DRY RUN] Would import missing solution {solution_id} ({solution_name}) version {solution_version} on {server_name}")
                    server_imports_attempted += 1
                    server_imports_successful += 1
                    missing_import_stats["total_attempted"] += 1
                    missing_import_stats["total_successful"] += 1
                    continue

                try:
                    server_imports_attempted += 1
                    missing_import_stats["total_attempted"] += 1

                    # Import the missing solution using the same logic as out-of-date imports
                    import_solution(client, solution_id, manifest[solution_id]["content_url"], conflict_policy_path=args.conflict_policy, conflict_default=args.conflict_default)
                    logging.info(f"✅ Successfully imported missing solution {solution_id} ({solution_name}) on {server_name}")
                    server_imports_successful += 1
                    missing_import_stats["total_successful"] += 1

                except Exception as exc:
                    logging.error(f"❌ Failed to import missing solution {solution_id} ({solution_name}) on {server_name}: {exc}")
                    server_imports_failed += 1
                    missing_import_stats["total_failed"] += 1

            # Track server completion
            missing_import_stats["servers_processed"] += 1
            print(f"\n📊 Server {server_name} missing solutions import summary:")
            print(f"  Attempted: {server_imports_attempted}")
            print(f"  Successful: {server_imports_successful}")
            print(f"  Skipped: {server_imports_skipped} (already up-to-date)")
            print(f"  Failed: {server_imports_failed}")

            # Release global lock for this server after all imports are complete
            if server_global_lock:
                try:
                    server_global_lock.release()
                    logging.info(f"Released global import lock for {server_name}")
                except Exception as exc:
                    logging.error(f"Failed to release global import lock for {server_name}: {exc}")

        # Print final missing solutions import statistics
        if missing_import_stats["total_attempted"] > 0:
            print("\n🎯 FINAL MISSING SOLUTIONS IMPORT STATISTICS:")
            print(f"  Servers processed: {missing_import_stats['servers_processed']}")
            print(f"  Servers skipped: {missing_import_stats['servers_skipped']}")
            print(f"  Total imports attempted: {missing_import_stats['total_attempted']}")
            print(f"  Total imports successful: {missing_import_stats['total_successful']}")
            print(f"  Total imports skipped: {missing_import_stats['total_skipped']} (already up-to-date)")
            print(f"  Total imports failed: {missing_import_stats['total_failed']}")
            # Calculate success rate including skipped as successful (reached desired state)
            effective_success = missing_import_stats['total_successful'] + missing_import_stats['total_skipped']
            success_rate = (effective_success / missing_import_stats['total_attempted']) * 100
            print(f"  Success rate: {success_rate:.1f}% ({effective_success}/{missing_import_stats['total_attempted']})")

    # Print combined final summary if any imports ran
    if args.import_out_of_date or args.import_missing:
        if import_stats["total_attempted"] > 0 or missing_import_stats["total_attempted"] > 0:
            combined_attempted = import_stats["total_attempted"] + missing_import_stats["total_attempted"]
            combined_successful = import_stats["total_successful"] + missing_import_stats["total_successful"]
            combined_skipped = import_stats["total_skipped"] + missing_import_stats["total_skipped"]
            combined_failed = import_stats["total_failed"] + missing_import_stats["total_failed"]
            combined_servers = max(import_stats["servers_processed"], missing_import_stats["servers_processed"])

            separator = "=" * 60
            print(f"\n{separator}")
            print("🏆 COMBINED IMPORT SUMMARY (ALL PHASES)")
            print(separator)
            print(f"  Servers processed: {combined_servers}")
            if import_stats["total_attempted"] > 0:
                print(f"  Out-of-date solutions imported: {import_stats['total_successful']}")
            if missing_import_stats["total_attempted"] > 0:
                print(f"  Missing solutions imported: {missing_import_stats['total_successful']}")
            print(f"  Total imports attempted: {combined_attempted}")
            print(f"  Total imports successful: {combined_successful}")
            print(f"  Total imports skipped: {combined_skipped} (already up-to-date)")
            print(f"  Total imports failed: {combined_failed}")
            if combined_attempted > 0:
                combined_effective_success = combined_successful + combined_skipped
                combined_success_rate = (combined_effective_success / combined_attempted) * 100
                print(f"  Overall success rate: {combined_success_rate:.1f}% ({combined_effective_success}/{combined_attempted})")
            print(separator)

    # Write summary JSON if requested
    if args.summary_out:
        # Validate summary file path for security
        if not validate_file_path(args.summary_out, allowed_dirs=['/var/log', '/tmp', '/opt']):
            logging.error(f"Invalid summary file path: {args.summary_out}")
            sys.exit(1)

        try:
            # Calculate totals
            total_missing = sum(len(results['missing']) for results in server_results.values())
            total_out_of_date = sum(len(results['out_of_date']) for results in server_results.values())
            total_up_to_date = sum(len(results['up_to_date']) for results in server_results.values())

            summary = {
                "servers": server_results,
                "inconsistencies": inconsistencies,
                "totals": {
                    "missing": total_missing,
                    "out_of_date": total_out_of_date,
                    "up_to_date": total_up_to_date
                }
            }
            with open(args.summary_out, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
            # Set secure permissions on summary file
            secure_file_permissions(args.summary_out)
            logging.info(f"Wrote summary to {args.summary_out}")
        except Exception as e:
            logging.error(f"Failed to write summary file {args.summary_out}: {e}")

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
