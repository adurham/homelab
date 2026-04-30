import sys
from urllib.parse import urlparse, unquote
import re
import socket
import ssl
import json
import os
import subprocess
import platform
import argparse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
# Attempt to import Tanium, handle if not installed
try:
    import tanium
except ModuleNotFoundError:
    pass

# ============================================================
# Logging initialization
# ============================================================
# Generate a UTC timestamp
def utc_timestamp():
    return datetime.now(timezone.utc).strftime("%F %Tz")


# Log a message with a UTC timestamp
def log(msg):
    print(f"{utc_timestamp()} {msg}", flush=True)


# ============================================================
# Global Variables and Initialization
# ============================================================
# List of domains to test
domain_list = set()
# Operating system information and threading lock
OS_NAME = platform.system()
# Cached CA paths, populated once during execution
CA_PATHS = None
_ca_lock = threading.Lock()
# Dynamically set the number of workers to the number of CPU cores
# Fallback to 1 if os.cpu_count() returns None
max_workers = os.cpu_count() or 1


# Attempt to get the base path from the Tanium client, fallback to current directory
try:
    base_path = tanium.client.common.get_client_dir()
except Exception:
    log(f"Tanium client directory not found. Using current working directory as base_path.")
    base_path = os.getcwd()


# Path to store results file
RESULTS_FILE = os.path.join(base_path, "Tools", "tls_test-Results.json")


# ============================================================
# Utility Functions
# ============================================================
# Get OS-specific paths for CA bundles and executables
def get_os_specific_paths():
    """
    Helper function to get OS-specific paths for CA bundles and executables.
    Returns a dictionary of relevant paths for the detected OS.
    """
    os_paths = {
        "Linux": {
            "ca_paths": ["/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/cert.pem", "/etc/ssl/ca-bundle.pem"],
            "exe_suffix": ""
        },
        "Darwin": {
            "ca_paths": [
                "/private/etc/ssl/cert.pem",
                "/usr/local/etc/openssl@1.1/cert.pem",
                "/usr/local/etc/openssl/cert.pem",
                "/etc/ssl/cert.pem",
                "/System/Library/OpenSSL/certs/cert.pem"
            ],
            "exe_suffix": ""
        },
        "Windows": {
            "ca_paths": [],
            "exe_suffix": ".exe"
        }
    }
    return os_paths.get(OS_NAME, {"ca_paths": [], "exe_suffix": ""})


# ============================================================
# TLS and Proxy Handling
# ============================================================
# Detect CA paths for the current operating system
def detect_ca_paths():
    """
    Detects the appropriate CA bundle and directory based on the operating system.
    Results are cached to avoid redundant detections, even in multi-threaded scenarios.
    """
    global CA_PATHS

    # Return cached CA_PATHS if already initialized
    if CA_PATHS is not None:
        return CA_PATHS

    # Use a lock to ensure only one thread initializes CA_PATHS
    with _ca_lock:
        # Double-check inside the lock
        if CA_PATHS is not None:
            return CA_PATHS

        ca_paths = {"cafile": None, "capath": None}
        log(f"Detected operating system: {OS_NAME}")

        os_specific_paths = get_os_specific_paths()
        for path in os_specific_paths["ca_paths"]:
            if os.path.exists(path):
                ca_paths["cafile"] = path
                ca_paths["capath"] = os.path.dirname(path)
                break

        if not ca_paths["cafile"] and OS_NAME == "Windows":
            log(f"Using Windows system certificate store.")
        elif not ca_paths["cafile"]:
            log(f"Defaulting to Python's built-in CA paths.")

        log(f"Detected CA paths: {ca_paths}")
        # Cache the result
        CA_PATHS = ca_paths
        return ca_paths


# Create an SSL context with the detected CA paths
def configure_ssl_context():
    """Configure and return an SSL context using detected CA paths."""
    context = ssl.create_default_context()
    ca_paths = detect_ca_paths()

    if ca_paths["cafile"] or ca_paths["capath"]:
        os.environ["SSL_CERT_FILE"] = ca_paths["cafile"] or ""
        os.environ["SSL_CERT_DIR"] = ca_paths["capath"] or ""
        context.load_verify_locations(
            cafile=ca_paths["cafile"], capath=ca_paths["capath"])

    return context


# Run a command and safely return its output
def run_command(command_path, args):
    """Safely execute a command and return the result."""
    try:
        result = subprocess.run(
            [command_path] + args,
            capture_output=True,
            text=True,
            check=True,
            shell=False
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log(f"Command failed: {command_path} {' '.join(args)} - {e}")
        return None


# Detect and validate proxies
def detect_proxies():
    """Detect and validate proxies based on the OS, only if Tanium is imported."""
    if 'tanium' not in sys.modules:
        log(f"Tanium module is not imported. Skipping proxy detection.")
        return []

    os_specific_paths = get_os_specific_paths()
    command_path = os.path.join(
        base_path, f"TaniumClient{os_specific_paths['exe_suffix']}")
    args = ["config", "get", "ProxyServers"]

    log(f"Running proxy detection command for {
        OS_NAME}: {command_path} {' '.join(args)}")
    proxies = run_command(command_path, args)

    if proxies:
        proxy_list = re.split(r'[ ,]', proxies)
        validated_proxies = [
            proxy for proxy in proxy_list if validate_proxy(proxy)]
        log(f"Validated proxies: {validated_proxies}")
        return validated_proxies
    else:
        log(f"No proxies detected.")
        return []


# Validate a proxy by attempting a connection
def validate_proxy(proxy):
    """Validate a proxy by attempting to establish a connection."""
    try:
        parsed_proxy = urlparse(proxy if "://" in proxy else f"http://{proxy}")
        hostname, port = parsed_proxy.hostname, parsed_proxy.port

        if hostname and port:
            with socket.create_connection((hostname, port), timeout=5):
                log(f"Proxy {proxy} is valid.")
                return True
    except Exception as e:
        log(f"Proxy {proxy} validation failed: {e}")
    return False


# Resolve a domain to its A records
def resolve_dns(domain):
    """Resolve the domain to A records using the standard library."""
    try:
        log(f"Resolving DNS for {domain}...")
        ip_list = socket.gethostbyname_ex(domain)[2]
        log(f"Resolved IPs for {domain}: {ip_list}")
        return ip_list
    except socket.gaierror as e:
        log(f"DNS resolution failed for {domain}: {e}")
        return []


# Test a TLS connection to a specific domain and IP
def test_tls_connection(ip, domain, domain_port=443, proxy=None):
    """Test a TLS connection using the given IP and domain name."""
    context = configure_ssl_context()

    try:
        if proxy:
            proxy_ip, proxy_port = proxy.split(":")
            log(f"Testing via proxy {proxy} to {domain}:{domain_port}")
            with socket.create_connection((proxy_ip, int(proxy_port)), timeout=5) as proxy_sock:
                proxy_sock.sendall(f"CONNECT {domain}:{
                                   domain_port} HTTP/1.1\r\n\r\n".encode())
                with context.wrap_socket(proxy_sock, server_hostname=domain):
                    log(f"TLS handshake successful for {
                        domain} via proxy {proxy}")
                    return True
        else:
            log(f"Testing direct connection to {ip}:{domain_port}")
            with socket.create_connection((ip, domain_port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=domain):
                    log(f"TLS handshake successful for {domain}")
                    return True
    except Exception as e:
        log(f"TLS connection failed for {domain} ({ip}) with error: {type(e).__name__} - {e}")

    return False


# ============================================================
# Results File Handling
# ============================================================
# Ensure the results file exists
def ensure_results_file():
    """
    Ensures that the directory and results file exist.
    """
    results_dir = os.path.dirname(RESULTS_FILE)
    if not os.path.exists(results_dir):
        os.makedirs(results_dir, exist_ok=True)
    if not os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "w") as file:
            json.dump({}, file)
    log(f"Ensuring results file exists at: {RESULTS_FILE}")



# Load results from the results file
def load_results():
    """Loads results from the results file if it exists."""
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as file:
            return json.load(file)
    return {}


# Save results to the results file
def save_results(results):
    """Saves results to the results file."""
    with open(RESULTS_FILE, "w") as file:
        json.dump(results, file, indent=4)


# Remove the results file
def remove_results():
    if os.path.isfile(RESULTS_FILE):
        os.remove(RESULTS_FILE)


# ============================================================
# Main Function
# ============================================================
# Main entry point for the script
def main():
    parser = argparse.ArgumentParser(description="TLS Connection Tester")
    parser.add_argument("--clean-results", action="store_true",
                        help="Remove all previous results")
    parser.add_argument("domains", nargs="*", help="Domains to test")
    args = parser.parse_args()

    if args.clean_results:
        log(f"Cleaning up results...")
        remove_results()
        sys.exit(0)

    domain_list.update(args.domains)
    if not domain_list:
        log(f"No domains provided. Exiting.")
        sys.exit(1)

    log(f"Domains to test: {sorted(domain_list)}")
    proxies = detect_proxies()

    # Concurrent Testing
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_test = {
            executor.submit(test_tls_connection, ip, domain, proxy=proxy): (domain, ip, proxy)
            for domain in domain_list
            for ip in resolve_dns(domain)
            for proxy in proxies or [None]
        }

        for future in as_completed(future_to_test):
            domain, ip, proxy = future_to_test[future]
            try:
                success = future.result()
                results.setdefault(domain, {}).setdefault(ip, {}).update({
                    "last_successful": utc_timestamp() if success else None,
                    "successful": success,
                })
            except Exception as e:
                log(f"Error processing {domain} ({ip}) via proxy {proxy}: {e}")

    save_results(results)
    log(f"Results saved.")


# ============================================================
# Execution Guard
# ============================================================
if __name__ == "__main__":
    main()
