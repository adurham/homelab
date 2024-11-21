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
try:
    import tanium
except Exception as e:
    pass

# List of domains to test
domain_list = set(
    [
        # Example: "google.com"
        "",
    ]
)


def utc_timestamp():
    return datetime.now(timezone.utc).strftime("%F %Tz")


def log(msg):
    # Print with a UTC timestamp
    print("{} {}".format(utc_timestamp(), msg), flush=True)


# Initialize base path from Tanium client
try:
    base_path = tanium.client.common.get_client_dir()
except:
    log("Tanium client directory not found. Using current working directory as base_path.")
    base_path = os.getcwd()

# ======================
# 1) Setup Functions
# ======================


def detect_ca_paths():
    """
    Detects the appropriate CA bundle and directory based on the operating system.
    Returns a dictionary with 'cafile' and 'capath' keys.
    """
    ca_paths = {
        "cafile": None,
        "capath": None
    }

    os_name = platform.system()
    log(f"Detected operating system: {os_name}")

    if os_name == "Linux":
        # Common CA paths for Linux distributions
        if os.path.exists("/etc/ssl/certs/ca-certificates.crt"):
            ca_paths["cafile"] = "/etc/ssl/certs/ca-certificates.crt"
            ca_paths["capath"] = "/etc/ssl/certs"
        elif os.path.exists("/etc/pki/tls/cert.pem"):
            ca_paths["cafile"] = "/etc/pki/tls/cert.pem"
            ca_paths["capath"] = "/etc/pki/tls/certs"
        elif os.path.exists("/etc/ssl/ca-bundle.pem"):
            ca_paths["cafile"] = "/etc/ssl/ca-bundle.pem"
            ca_paths["capath"] = "/etc/ssl/certs"
    elif os_name == "Darwin":
        # Common CA paths for macOS
        log("Attempting to detect CA certificates on macOS.")
        possible_cafile_locations = [
            '/private/etc/ssl/cert.pem',
            '/usr/local/etc/openssl@1.1/cert.pem',
            '/usr/local/etc/openssl/cert.pem',
            '/etc/ssl/cert.pem',
            '/System/Library/OpenSSL/certs/cert.pem',
        ]
        possible_capath_locations = [
            '/private/etc/ssl/certs',
            '/usr/local/etc/openssl@1.1/certs',
            '/usr/local/etc/openssl/certs',
            '/etc/ssl/certs',
            '/System/Library/OpenSSL/certs',
        ]
        for cafile in possible_cafile_locations:
            if os.path.exists(cafile):
                log(f"Found CA file at {cafile}")
                ca_paths["cafile"] = cafile
                break
        if not ca_paths["cafile"]:
            for capath in possible_capath_locations:
                if os.path.exists(capath):
                    log(f"Found CA directory at {capath}")
                    ca_paths["capath"] = capath
                    break
        if not ca_paths["cafile"] and not ca_paths["capath"]:
            log("Could not find CA certificates on macOS.")
    elif os_name == "Windows":
        # Windows (uses the system's certificate store)
        ca_paths["cafile"] = None
        ca_paths["capath"] = None
    else:
        log("Unsupported operating system. Defaulting to Python's built-in CA paths.")

    log(f"Detected CA paths: {ca_paths}")
    return ca_paths


def configure_ssl_context():
    """
    Configures and returns an SSL context using the detected CA paths.
    """
    context = ssl.create_default_context()
    ca_paths = detect_ca_paths()

    if ca_paths["cafile"] or ca_paths["capath"]:
        os.environ["SSL_CERT_FILE"] = ca_paths["cafile"] or ""
        os.environ["SSL_CERT_DIR"] = ca_paths["capath"] or ""
        log("Using detected CA paths for SSL validation.")
        context.load_verify_locations(
            cafile=ca_paths["cafile"], capath=ca_paths["capath"])
    else:
        log("Using Python's default SSL validation paths.")

    return context


# ============================
# 2) Information Gathering Functions
# ============================

def validate_proxy(proxy):
    """Validates a proxy by attempting to establish a connection to it."""
    try:
        # Add 'http://' if the proxy string does not include a scheme
        if not proxy.startswith(('http://', 'https://', 'socks5://')):
            proxy_with_scheme = 'http://' + proxy
        else:
            proxy_with_scheme = proxy

        parsed_proxy = urlparse(proxy_with_scheme)
        hostname = parsed_proxy.hostname
        port = parsed_proxy.port

        if not hostname or not port:
            log(f"Invalid proxy format: {proxy}")
            return False

        # Attempt to create a socket connection to the proxy
        with socket.create_connection((hostname, port), timeout=5):
            log(f"Proxy {proxy} is valid.")
            return True
    except Exception as e:
        log(f"Proxy {proxy} validation failed: {e}")
        return False


def detect_proxies():
    """Detects proxies based on the OS and returns a list of validated proxies."""
    log("")

    proxies = []
    try:
        if platform.system() == "Windows":
            command_path = os.path.join(base_path, "TaniumClient.exe")
            args = ["config", "get", "ProxyServers"]
            log(f"Running Windows proxy detection command: {
                command_path} {' '.join(args)}")
            # Works the same as the non-Windows
            result = subprocess.run(
                [command_path] + args,
                capture_output=True,
                text=True,
                check=True,
                shell=False
            )
            proxies = re.split('[ ,]', result.stdout)
        elif platform.system() == "Linux":
            command_path = os.path.join(base_path, "TaniumClient")
            args = ["config", "get", "ProxyServers"]
            log(f"Running Linux proxy detection command: {
                command_path} {' '.join(args)}")
            result = subprocess.run(
                [command_path] + args,
                capture_output=True,
                text=True,
                check=True,
                shell=False
            )
            proxies = re.split('[ ,]', result.stdout)
        elif platform.system() == "Darwin":
            command_path = os.path.join(base_path, "TaniumClient")
            args = ["config", "get", "ProxyServers"]
            log(f"Running Darwin proxy detection command: {
                command_path} {' '.join(args)}")
            result = subprocess.run(
                [command_path] + args,
                capture_output=True,
                text=True,
                check=True,
                shell=False
            )
            proxies = re.split('[ ,]', result.stdout)
        else:
            log("Unsupported operating system for proxy detection.")
    except subprocess.CalledProcessError as e:
        log(f"Error detecting proxies: {e}")
    except Exception as e:
        log(f"Unexpected error: {e}")

    proxy_list = [proxy.strip() for proxy in proxies if proxy.strip()]
    # Use a 'set' to avoid duplicate entries
    validated_proxies = set(
        [proxy for proxy in proxy_list if validate_proxy(proxy)]
    )
    log(f"Validated proxies: {validated_proxies}")
    return validated_proxies

# def detect_proxies_external():
#     """Fallback function to detect proxies using the external configuration data."""
#     log("Falling back to external proxy detection method.")
#     proxies = []
#     # Get the configuration data
#     config_data = tanium.client.get_full_config()
#     # Extract 'ProxyServers' from the configuration data
#     proxy_servers = config_data.get('ProxyServers')
#     if proxy_servers:
#         # 'ProxyServers' may contain multiple proxies separated by commas
#         proxies = [proxy.strip() for proxy in proxy_servers.split(',')]
#         log(f"Extracted 'ProxyServers': {proxies}")
#     else:
#         log("No 'ProxyServers' found in external data.")
#     return proxies


def resolve_dns(domain):
    """Resolves the domain to A records using the standard library."""
    try:
        log(f"Resolving DNS for {domain}...")
        result = socket.gethostbyname_ex(domain)
        ip_list = result[2]
        log(f"Resolved IPs: {ip_list}")
        return ip_list
    except socket.gaierror as e:
        log(f"Error resolving {domain}: {e}")
        return []


# ==============================
# 3) Information Processing Functions
# ==============================

def test_tls_connection(ip, domain, domain_port=443, proxy=None):
    """Attempts to establish a TLS connection using the domain name for SNI."""
    context = configure_ssl_context()
    try:
        if proxy:
            proxy_ip, proxy_port = proxy.split(":")
            if not proxy_ip or not proxy_port:
                log(f"Invalid proxy format: {proxy}")
                return False

            log(f"Using proxy {proxy_ip}:{
                proxy_port} for connection to {domain}:{domain_port}")
            with socket.create_connection((proxy_ip, proxy_port), timeout=5) as proxy_sock:
                connect_request = (
                    f"CONNECT {domain}:{domain_port} HTTP/1.1\r\n"
                    f"Host: {domain}:{domain_port}\r\n"
                    f"Proxy-Connection: keep-alive\r\n\r\n"
                )
                proxy_sock.sendall(connect_request.encode())
                response = proxy_sock.recv(4096).decode()
                if "200 Connection established" not in response:
                    log(f"Proxy {proxy_ip}:{
                        proxy_port} failed to establish connection: {response}")
                    return False

                log(f"Establishing TLS with SNI for domain: {domain}")
                with context.wrap_socket(proxy_sock, server_hostname=domain) as tls_sock:
                    tls_sock.do_handshake()
                    log("TLS handshake completed.")
                    return True
        else:
            log(f"Connecting directly to {ip}:{domain_port}")
            with socket.create_connection((ip, domain_port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as tls_sock:
                    tls_sock.do_handshake()
                    log("TLS handshake completed.")
                    return True
    except ssl.SSLError as ssl_error:
        log(f"SSL error: {ssl_error}")
    except Exception as e:
        log(f"TLS connection failed to {ip}:{domain_port} {
            'through proxy ' + proxy if proxy else ''} - {e}")
    return False


def update_results(results, domain, ip, success):
    """Updates the results dictionary with the given domain, IP, and success status."""
    if domain not in results:
        results[domain] = {}

    if ip not in results[domain]:
        results[domain][ip] = {"last_successful": None, "successful": False}

    if success:
        results[domain][ip]["successful"] = True
        results[domain][ip]["last_successful"] = utc_timestamp()
    else:
        results[domain][ip]["successful"] = False


# =========================
# 4) Information Saving Functions
# =========================

# Construct RESULTS_FILE with base_path
RESULTS_FILE = os.path.join(base_path, "Tools", "tls_test-Results.json")


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
    log(f"Results file ensured at: {RESULTS_FILE}")


def load_results():
    """Loads results from the results file if it exists."""
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as file:
            return json.load(file)
    return {}


def save_results(results):
    """Saves results to the results file."""
    with open(RESULTS_FILE, "w") as file:
        json.dump(results, file, indent=4)


def remove_results():
    if os.path.isfile(RESULTS_FILE):
        os.remove(RESULTS_FILE)


# =========================
# 5) Main
# =========================

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='TLS Connection Tester')
    parser.add_argument(
        '--clean-results',
        help='Remove all previous test results',
        required=False,
        default=False,
        action='store_true'
    )
    parser.add_argument(
        'added_domains',
        nargs='*',
        help='List of domains to test'
    )

    tanium_params = []
    # Unquote and flatten all of the Tanium Package parameters
    if 'tanium' in sys.modules:
        tanium = sys.modules['tanium']
        tanium_params = [
            domain
            for sub_list in [re.split(r'[ ,\n]', unquote(param))
                             for param in tanium.get_arguments()]
            for domain in sub_list
        ]
    # Parse whatever Tanium libraries return along with sys.argv
    args = parser.parse_args(sys.argv[1:] + tanium_params)

    # Is this a cleanup invocation?
    if args.clean_results is True:
        log(f"Removing {RESULTS_FILE} file and exiting.")
        remove_results()
        sys.exit(0)

    # Add any command line target domains to our set
    domain_list.update(args.added_domains)
    if not domain_list:
        log("No domains provided to test.")
        return

    # Print the domain list before testing
    log("Domains to be tested: {}".format(sorted(domain_list)))

    # Test setup
    ensure_results_file()
    results = load_results()
    proxies = detect_proxies()

    # And test each target FQDN
    for base_domain in sorted(domain_list):
        log("")
        log(f"Testing domain: {base_domain}")

        a_records = resolve_dns(base_domain)
        if not a_records:
            log(f"No IPs to test for {base_domain}.")
            continue

        for ip in a_records:
            if proxies:
                for proxy in proxies:
                    success = test_tls_connection(ip, base_domain, proxy=proxy)
                    update_results(results, base_domain, ip, success)
            else:
                success = test_tls_connection(ip, base_domain)
                update_results(results, base_domain, ip, success)

    save_results(results)
    log(f"Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
