from urllib.parse import urlparse
import socket
import ssl
import json
import os
import subprocess
import platform
from datetime import datetime
import tanium

# Initialize base path from Tanium client
base_path = tanium.client.common.get_client_dir()

# Construct RESULTS_FILE with base_path
RESULTS_FILE = os.path.join(base_path, "Tools", "tls_results.json")

# List of domains to test
domain_list = [

]

# ======================
# 1) Setup Functions
# ======================


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
    print(f"Results file ensured at: {RESULTS_FILE}")


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
    print(f"Detected operating system: {os_name}")

    if os_name == "Linux":
        # Detect Linux distribution
        try:
            distro = platform.freedesktop_os_release().get("ID", "").lower()
            print(f"Detected Linux distribution: {distro}")
        except AttributeError:
            distro = "unknown"

        # Common CA paths for different distributions
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
        # macOS (attempt to locate CA certificates)
        print("Attempting to detect CA certificates on macOS.")
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
                print(f"Found CA file at {cafile}")
                ca_paths["cafile"] = cafile
                break
        if not ca_paths["cafile"]:
            for capath in possible_capath_locations:
                if os.path.exists(capath):
                    print(f"Found CA directory at {capath}")
                    ca_paths["capath"] = capath
                    break
        if not ca_paths["cafile"] and not ca_paths["capath"]:
            print("Could not find CA certificates on macOS.")
    elif os_name == "Windows":
        # Windows (uses the system's certificate store)
        ca_paths["cafile"] = None
        ca_paths["capath"] = None
    else:
        print("Unsupported operating system. Defaulting to Python's built-in CA paths.")

    print(f"Detected CA paths: {ca_paths}")
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
        print("Using detected CA paths for SSL validation.")
        context.load_verify_locations(
            cafile=ca_paths["cafile"], capath=ca_paths["capath"])
    else:
        print("Using Python's default SSL validation paths.")

    return context


# ============================
# 2) Information Gathering Functions
# ============================

def validate_proxy(proxy):
    """Validates a proxy by attempting to establish a connection to it."""
    try:
        parsed_proxy = urlparse(proxy)
        with socket.create_connection((parsed_proxy.hostname, parsed_proxy.port), timeout=5):
            print(f"Proxy {proxy} is valid.")
            return True
    except Exception as e:
        print(f"Proxy {proxy} validation failed: {e}")
        return False


def detect_proxies():
    """Detects proxies based on the OS and returns a list of validated proxies."""
    proxies = []
    try:
        if platform.system() == "Windows":
            command_path = os.path.join(base_path, "TaniumClient.exe")
            args = ["config", "get", "ProxyServers"]
            print(f"Running Windows proxy detection command: {
                  command_path} {' '.join(args)}")
            result = subprocess.run(
                [command_path] + args,
                capture_output=True,
                text=True,
                check=True,
                shell=True  # For handling paths with spaces
            )
            proxies = result.stdout.split()
        elif platform.system() == "Linux":
            command_path = os.path.join(base_path, "TaniumClient")
            args = ["config", "get", "ProxyServers"]
            print(f"Running Linux proxy detection command: {
                  command_path} {' '.join(args)}")
            result = subprocess.run(
                [command_path] + args,
                capture_output=True,
                text=True,
                check=True,
                shell=True
            )
            proxies = result.stdout.split()
        elif platform.system() == "Darwin":
            command_path = os.path.join(base_path, "TaniumClient")
            args = ["config", "get", "ProxyServers"]
            print(f"Running Darwin proxy detection command: {
                  command_path} {' '.join(args)}")
            result = subprocess.run(
                [command_path] + args,
                capture_output=True,
                text=True,
                check=True,
                shell=True
            )
            proxies = result.stdout.split()
        else:
            print("Unsupported operating system for proxy detection.")
    except subprocess.CalledProcessError as e:
        print(f"Error detecting proxies: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

    proxy_list = [proxy.strip() for proxy in proxies if proxy.strip()]
    validated_proxies = [
        proxy for proxy in proxy_list if validate_proxy(proxy)]
    print(f"Validated proxies: {validated_proxies}")
    return validated_proxies


def resolve_dns(domain):
    """Resolves the domain to A records using the standard library."""
    try:
        print(f"Resolving DNS for {domain}...")
        result = socket.gethostbyname_ex(domain)
        ip_list = result[2]
        print(f"Resolved IPs: {ip_list}")
        return ip_list
    except socket.gaierror as e:
        print(f"Error resolving {domain}: {e}")
        return []


# ==============================
# 3) Information Processing Functions
# ==============================

def test_tls_connection(ip, domain, proxy=None, port=443):
    """Attempts to establish a TLS connection using the domain name for SNI."""
    context = configure_ssl_context()
    try:
        if proxy:
            parsed_proxy = urlparse(proxy)
            proxy_ip = parsed_proxy.hostname
            proxy_port = parsed_proxy.port

            if not proxy_ip or not proxy_port:
                print(f"Invalid proxy format: {proxy}")
                return False

            print(f"Using proxy {proxy_ip}:{
                  proxy_port} for connection to {domain}:{port}")
            with socket.create_connection((proxy_ip, proxy_port), timeout=5) as proxy_sock:
                connect_request = (
                    f"CONNECT {domain}:{port} HTTP/1.1\r\n"
                    f"Host: {domain}:{port}\r\n"
                    f"Proxy-Connection: keep-alive\r\n\r\n"
                )
                proxy_sock.sendall(connect_request.encode())
                response = proxy_sock.recv(4096).decode()
                if "200 Connection established" not in response:
                    print(f"Proxy {proxy_ip}:{
                          proxy_port} failed to establish connection: {response}")
                    return False

                print(f"Establishing TLS with SNI for domain: {domain}")
                with context.wrap_socket(proxy_sock, server_hostname=domain) as tls_sock:
                    tls_sock.do_handshake()
                    print("TLS handshake completed.")
                    return True
        else:
            print(f"Connecting directly to {ip}:{port}")
            with socket.create_connection((ip, port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as tls_sock:
                    tls_sock.do_handshake()
                    print("TLS handshake completed.")
                    return True
    except ssl.SSLError as ssl_error:
        print(f"SSL error: {ssl_error}")
    except Exception as e:
        print(f"TLS connection failed to {ip}:{port} {
              'through proxy ' + proxy if proxy else ''} - {e}")
    return False


def update_results(results, domain, ip, success):
    """Updates the results dictionary with the given domain, IP, and success status."""
    if domain not in results:
        results[domain] = {}

    if ip not in results[domain]:
        results[domain][ip] = {"last_successful": None, "successful": False}

    if success:
        results[domain][ip]["last_successful"] = datetime.now().isoformat()
        results[domain][ip]["successful"] = True
    else:
        results[domain][ip]["successful"] = False


# =========================
# 4) Information Saving Functions
# =========================

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


# =========================
# 5) Main
# =========================

def main():
    ensure_results_file()
    results = load_results()
    proxies = detect_proxies()

    for base_domain in domain_list:
        print(f"\nTesting domain: {base_domain}")
        a_records = resolve_dns(base_domain)
        if not a_records:
            print(f"No IPs to test for {base_domain}.")
            continue

        for ip in a_records:
            if proxies:
                for proxy in proxies:
                    success = test_tls_connection(ip, base_domain, proxy)
                    update_results(results, base_domain, ip, success)
            else:
                success = test_tls_connection(ip, base_domain)
                update_results(results, base_domain, ip, success)

    save_results(results)
    print(f"Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
