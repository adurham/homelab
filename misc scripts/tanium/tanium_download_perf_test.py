#!/usr/bin/env python3
r"""
Tanium Client Download Performance Test
Tests legacy (port 17472) vs CDN (port 443) download performance

Usage:
    # Test with file hash (auto-detect Tanium Client directory)
    # Hash will be converted to: https://127.0.0.1/cache/<HASH>
    python3 tanium_download_perf_test.py \
        --file-hash 384fe56a74ea62f97343af920d9c13573517df093991e3a379ed7ed81827815e \
        --iterations 5

    # Test with URL and custom directory
    python3 tanium_download_perf_test.py --tc-dir /custom/path/TaniumClient \
        --file-url https://example.com/file.zip \
        --iterations 5

    # Capture network traffic for analysis
    python3 tanium_download_perf_test.py \
        --file-hash 384fe56a74ea62f97343af920d9c13573517df093991e3a379ed7ed81827815e \
        --capture-traffic

Default paths:
    Windows: C:\Program Files (x86)\Tanium\Tanium Client
    Linux:   /opt/Tanium/TaniumClient
    macOS:   /Library/Tanium/TaniumClient

Note: --capture-traffic requires tcpdump (Linux/macOS) or tshark (Windows) and may require sudo/admin privileges.
"""
from __future__ import division
from __future__ import print_function
import sys
sys.dont_write_bytecode = True

# Python v2 and v3 compatibility
PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3
if PY2:
    from urllib2 import URLError
    from urllib2 import urlopen
    from urllib2 import Request as url_request
    from StringIO import StringIO
    from urlparse import urlparse
elif PY3:
    long = int
    from urllib.error import URLError
    from urllib.request import urlopen
    from urllib.request import Request as url_request
    from io import StringIO
    from urllib.parse import urlparse
else:
    msg = "Don't know how to run on Python v{0}.{1}."
    raise NotImplementedError(msg.format(sys.version_info))

import time
import os
import sys
import shutil
import argparse
import json
import xml.etree.ElementTree as ET
import xml.dom.minidom
import platform
import subprocess
from datetime import datetime

# SSL context setup
import ssl
if PY2:
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
elif PY3:
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ssl_ctx.maximum_version = ssl.TLSVersion.TLSv1_2
ssl_ctx.verify_flags = ssl.CERT_NONE
ssl_ctx.check_hostname = False


class PrettyPrintET(ET.ElementTree):
    def pretty_print(self):
        return xml.dom.minidom.parseString(
            ET.tostring(self.getroot())
        ).toprettyxml(indent=" " * 3, newl="\n     ")


class TaniumClientController:
    """Controls Tanium Client service and configuration"""

    @staticmethod
    def get_default_tc_dir():
        """Get default Tanium Client directory based on OS"""
        system = platform.system()

        if system == "Windows":
            return "C:\\Program Files (x86)\\Tanium\\Tanium Client"
        elif system == "Linux":
            return "/opt/Tanium/TaniumClient"
        elif system == "Darwin":  # macOS
            return "/Library/Tanium/TaniumClient"
        else:
            return None

    def __init__(self, tc_dir=None):
        # Auto-detect if not provided
        if tc_dir is None:
            tc_dir = self.get_default_tc_dir()
            if tc_dir is None:
                raise ValueError("Could not auto-detect Tanium Client directory for this OS. Please specify with --tc-dir")
            print(f"  [+] Auto-detected Tanium Client directory: {tc_dir}")

        self.tc_dir = tc_dir
        self.downloads_dir = os.path.join(tc_dir, "Downloads")
        self.soap_session_path = os.path.join(tc_dir, "soap_session")
        self.platform = platform.system()
        self.linux_service_name = None
        self.tcpdump_process = None

        # Validate paths
        if not os.path.exists(self.tc_dir):
            raise ValueError(f"Tanium Client directory not found: {self.tc_dir}")
        if not os.path.exists(self.soap_session_path):
            raise ValueError(f"soap_session file not found: {self.soap_session_path}")

        # Detect Linux service name if on Linux
        if self.platform == "Linux":
            self.linux_service_name = self._detect_linux_service_name()

    def _detect_linux_service_name(self):
        """Detect the Tanium Client service name on Linux"""
        try:
            # List all services and grep for tanium (case-insensitive)
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--all"],
                capture_output=True,
                text=True,
                check=True
            )

            # Look for tanium service in the output
            for line in result.stdout.split('\n'):
                if 'tanium' in line.lower() and '.service' in line:
                    # Extract service name (e.g., "taniumclient.service" -> "taniumclient")
                    parts = line.split()
                    if parts:
                        service_name = parts[0].replace('.service', '')
                        print(f"  [+] Detected Linux service name: {service_name}")
                        return service_name

            # Fallback to common name
            print(f"  [!] Could not detect service name, using default: taniumclient")
            return "taniumclient"

        except subprocess.CalledProcessError:
            print(f"  [!] Could not detect service name, using default: taniumclient")
            return "taniumclient"

    def get_soap_session(self):
        """Read the SOAP session token"""
        with open(self.soap_session_path, "r") as f:
            return f.read().strip()

    def stop_service(self):
        """Stop the Tanium Client service"""
        print(f"  [+] Stopping Tanium Client service...")
        try:
            if self.platform == "Windows":
                subprocess.run(["net", "stop", "Tanium Client"],
                             check=True, capture_output=True)
            elif self.platform == "Linux":
                subprocess.run(["sudo", "systemctl", "stop", self.linux_service_name],
                             check=True, capture_output=True)
            elif self.platform == "Darwin":  # macOS
                subprocess.run(["sudo", "launchctl", "bootout", "system",
                              "/Library/LaunchDaemons/com.tanium.taniumclient.plist"],
                             check=True, capture_output=True)
            time.sleep(2)  # Give it time to stop
            return True
        except subprocess.CalledProcessError as e:
            print(f"  [!] Warning: Failed to stop service: {e}")
            return False

    def start_service(self):
        """Start the Tanium Client service"""
        print(f"  [+] Starting Tanium Client service...")
        try:
            if self.platform == "Windows":
                subprocess.run(["net", "start", "Tanium Client"],
                             check=True, capture_output=True)
            elif self.platform == "Linux":
                subprocess.run(["sudo", "systemctl", "start", self.linux_service_name],
                             check=True, capture_output=True)
            elif self.platform == "Darwin":  # macOS
                subprocess.run(["sudo", "launchctl", "bootstrap", "system",
                              "/Library/LaunchDaemons/com.tanium.taniumclient.plist"],
                             check=True, capture_output=True)
            time.sleep(5)  # Give it time to start
            return True
        except subprocess.CalledProcessError as e:
            print(f"  [!] Warning: Failed to start service: {e}")
            return False

    def clear_downloads(self):
        """Clear the Downloads directory"""
        print(f"  [+] Clearing Downloads directory: {self.downloads_dir}")
        if os.path.exists(self.downloads_dir):
            try:
                shutil.rmtree(self.downloads_dir)
                os.makedirs(self.downloads_dir)
                print(f"  [+] Downloads directory cleared")
                return True
            except Exception as e:
                print(f"  [!] Error clearing downloads: {e}")
                return False
        else:
            os.makedirs(self.downloads_dir)
            return True

    def get_cdn_config(self):
        """
        Get the current EnableCDNDownloads configuration value

        Returns:
            str: Current value ('0' or '1') or None if not set/error
        """
        # Determine TaniumClient executable path
        if self.platform == "Windows":
            tanium_client_exe = os.path.join(self.tc_dir, "TaniumClient.exe")
        else:
            tanium_client_exe = os.path.join(self.tc_dir, "TaniumClient")

        try:
            result = subprocess.run(
                [tanium_client_exe, "config", "get", "EnableCDNDownloads"],
                capture_output=True,
                text=True,
                check=True
            )
            # Output format is typically "EnableCDNDownloads=X" or just "X"
            output = result.stdout.strip()
            if "=" in output:
                return output.split("=", 1)[1].strip()
            else:
                return output
        except subprocess.CalledProcessError:
            return None
        except Exception as e:
            print(f"  [!] Warning: Could not get EnableCDNDownloads value: {e}")
            return None

    def set_cdn_config(self, enabled):
        """
        Set the EnableCDNDownloads configuration using TaniumClient config set

        Args:
            enabled: True to enable CDN, False to disable
        """
        value = "1" if enabled else "0"

        # Check current value
        current_value = self.get_cdn_config()
        if current_value == value:
            print(f"  [+] EnableCDNDownloads already set to {value} (CDN {'enabled' if enabled else 'disabled'})")
            return

        # Determine TaniumClient executable path
        if self.platform == "Windows":
            tanium_client_exe = os.path.join(self.tc_dir, "TaniumClient.exe")
        else:
            tanium_client_exe = os.path.join(self.tc_dir, "TaniumClient")

        # Set the configuration
        try:
            subprocess.run(
                [tanium_client_exe, "config", "set", "EnableCDNDownloads", value],
                capture_output=True,
                text=True,
                check=True
            )
            if current_value is None:
                print(f"  [+] Set EnableCDNDownloads={value} (CDN {'enabled' if enabled else 'disabled'})")
            else:
                print(f"  [+] Updated EnableCDNDownloads from {current_value} to {value} (CDN {'enabled' if enabled else 'disabled'})")
        except subprocess.CalledProcessError as e:
            print(f"  [!] Error setting EnableCDNDownloads: {e}")
            print(f"  [!] stderr: {e.stderr}")
        except Exception as e:
            print(f"  [!] Error setting EnableCDNDownloads: {e}")

    def start_tcpdump(self, output_file, filter_expr=""):
        """
        Start tcpdump capture

        Args:
            output_file: Path to save the pcap file
            filter_expr: Optional tcpdump filter expression (e.g., "port 443 or port 17472")

        Returns:
            bool: True if started successfully
        """
        print(f"  [+] Starting packet capture: {output_file}", flush=True)

        # Build tcpdump command
        if self.platform == "Windows":
            # Windows uses windump or tshark, but let's use tshark for consistency
            cmd = ["tshark", "-w", output_file, "-q"]
            if filter_expr:
                cmd.append(filter_expr)
        else:
            # Linux/macOS use tcpdump
            cmd = ["sudo", "tcpdump", "-w", output_file, "-U", "-i", "any"]
            if filter_expr:
                cmd.append(filter_expr)

        try:
            self.tcpdump_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1)  # Give it a moment to start
            print(f"  [+] Packet capture started (PID: {self.tcpdump_process.pid})", flush=True)
            return True
        except FileNotFoundError:
            print(f"  [!] Warning: tcpdump/tshark not found, skipping packet capture", flush=True)
            self.tcpdump_process = None
            return False
        except Exception as e:
            print(f"  [!] Warning: Failed to start packet capture: {e}", flush=True)
            self.tcpdump_process = None
            return False

    def stop_tcpdump(self):
        """
        Stop tcpdump capture

        Returns:
            bool: True if stopped successfully
        """
        if self.tcpdump_process is None:
            return False

        print(f"  [+] Stopping packet capture...", flush=True)
        try:
            self.tcpdump_process.terminate()
            self.tcpdump_process.wait(timeout=5)
            print(f"  [+] Packet capture stopped", flush=True)
            self.tcpdump_process = None
            return True
        except subprocess.TimeoutExpired:
            print(f"  [!] Warning: Packet capture did not stop gracefully, killing...", flush=True)
            self.tcpdump_process.kill()
            self.tcpdump_process = None
            return False
        except Exception as e:
            print(f"  [!] Warning: Failed to stop packet capture: {e}", flush=True)
            self.tcpdump_process = None
            return False


class TaniumAPIClient:
    """Handles SOAP API requests to Tanium Client"""

    BASE_REQ = """
<soapenv:Envelope
 xmlns:urn="urn:TaniumSOAP"
 xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:tanium_soap_request>
      <session />
      <command />
      <object_list />
    </urn:tanium_soap_request>
  </soapenv:Body>
</soapenv:Envelope>
"""

    def __init__(self, controller, verbose=False):
        self.controller = controller
        self.verbose = verbose
        self.api_url = "http://127.0.0.1:17473"

    def make_request(self, xml_et):
        """Make an HTTPS request to the local Tanium Client API"""
        req = url_request(self.api_url)
        req.get_method = lambda: 'POST'

        xml_data = ET.tostring(xml_et.getroot(), method="xml")
        if self.verbose:
            print("\nRequest:\n{0}".format(xml_et.pretty_print()))

        reply = urlopen(req, data=xml_data, context=ssl_ctx)
        reply_data = reply.read().decode()
        ret = PrettyPrintET()
        ret.parse(StringIO(reply_data))

        if self.verbose:
            print("\nReply:\n{0}".format(ret.pretty_print()))

        return ret

    def create_base_xml(self):
        """Create base SOAP XML with session"""
        base = PrettyPrintET()
        base.parse(StringIO(self.BASE_REQ))
        soap_session_token = self.controller.get_soap_session()
        if soap_session_token:
            base.find(".//session").text = soap_session_token
        return base

    def download_file(self, file_identifier, timeout=3600, is_hash=False):
        """
        Request a file download

        Args:
            file_identifier: Either a URL or a SHA-256 hash
            timeout: Download timeout in seconds
            is_hash: True if file_identifier is a hash, False if it's a URL

        Returns:
            tuple: (success: bool, file_name: str)
        """
        base = self.create_base_xml()
        base.find(".//command").text = "AddObject"

        # Add download object
        obj_l = base.find(".//object_list")
        new_dld = ET.fromstring("<download />")

        if is_hash:
            # Download by hash - construct 127.0.0.1 cache URL
            url = f"https://127.0.0.1/cache/{file_identifier}"
            new_url = ET.fromstring(f"<url>{url}</url>")
            new_dld.append(new_url)

            # Also include the hash element for verification
            hash_et = ET.fromstring(f"<hash>{file_identifier}</hash>")
            new_dld.append(hash_et)

            file_name = file_identifier  # Use hash as identifier
        else:
            # Download by URL
            new_url = ET.fromstring(f"<url>{file_identifier}</url>")
            new_dld.append(new_url)
            # Derive file name from URL
            file_name = urlparse(file_identifier).path.split("/")[-1]

        name_et = ET.fromstring(f"<name>{file_name}</name>")
        new_dld.append(name_et)

        # Add timeout
        to_et = ET.fromstring(f"<timeout_seconds>{timeout}</timeout_seconds>")
        new_dld.append(to_et)

        obj_l.append(new_dld)

        try:
            reply = self.make_request(base)
            return True, file_name
        except (ConnectionError, URLError) as e:
            print(f"  [!] Download request failed: {e}")
            return False, None

    def monitor_download(self, file_identifier, is_hash=False):
        """
        Monitor download progress until complete

        Args:
            file_identifier: Either a URL or a SHA-256 hash
            is_hash: True if file_identifier is a hash, False if it's a URL

        Returns:
            tuple: (status: str, path: str, duration: float, file_size: int)
        """
        base = self.create_base_xml()
        base.find(".//command").text = "GetObject"

        # Add download object
        obj_l = base.find(".//object_list")
        new_dld = ET.fromstring("<download />")

        if is_hash:
            # Monitor by hash - construct 127.0.0.1 cache URL
            url = f"https://127.0.0.1/cache/{file_identifier}"
            new_url = ET.fromstring(f"<url>{url}</url>")
            new_dld.append(new_url)

            # Also include the hash element
            hash_et = ET.fromstring(f"<hash>{file_identifier}</hash>")
            new_dld.append(hash_et)

            file_name = file_identifier
        else:
            # Monitor by URL
            new_url = ET.fromstring(f"<url>{file_identifier}</url>")
            new_dld.append(new_url)
            file_name = urlparse(file_identifier).path.split("/")[-1]

        name_et = ET.fromstring(f"<name>{file_name}</name>")
        new_dld.append(name_et)
        obj_l.append(new_dld)

        start_time = time.time()
        max_wait_time = 3600  # 1 hour timeout

        while True:
            try:
                # Check for timeout
                elapsed = time.time() - start_time
                if elapsed > max_wait_time:
                    print()  # Move to new line after progress updates
                    print(f"  [!] Monitoring timed out after {max_wait_time} seconds")
                    return "Timeout", None, elapsed, 0

                reply = self.make_request(base)

                # Parse reply
                result_object = reply.find(".//result_object")
                if result_object is None:
                    print(f"    [!] No result_object in reply, retrying...")
                    time.sleep(2)
                    continue

                downloads = result_object.findall(".//download")
                if not downloads:
                    print(f"    [!] No download objects found in reply, retrying...")
                    time.sleep(2)
                    continue

                for dld in downloads:
                    status = dld.find(".//status").text if dld.find(".//status") is not None else "Unknown"
                    path = dld.find(".//path").text if dld.find(".//path") is not None else None

                    if status in ("Completed", "TimedOut", "NotFound", "Failed"):
                        duration = time.time() - start_time

                        # Get file size
                        file_size = 0
                        if status == "Completed" and path and os.path.exists(path):
                            file_size = os.path.getsize(path)

                        print()  # Move to new line after progress updates
                        return status, path, duration, file_size

                    # Still in progress
                    print(f"\r    Status: {status} (elapsed: {elapsed:.1f}s)", end='', flush=True)

                time.sleep(2)  # Poll every 2 seconds

            except (ConnectionError, URLError) as e:
                print()  # Move to new line after progress updates
                print(f"  [!] Monitoring failed: {e}")
                return "Error", None, time.time() - start_time, 0


class PerformanceTest:
    """Runs the performance test"""

    def __init__(self, file_identifier, tc_dir=None, iterations=5, verbose=False, is_hash=False, capture_traffic=False):
        self.controller = TaniumClientController(tc_dir)
        self.api_client = TaniumAPIClient(self.controller, verbose)
        self.file_identifier = file_identifier
        self.is_hash = is_hash
        self.iterations = iterations
        self.capture_traffic = capture_traffic
        self.results = []

        # Create pcap directory if capturing traffic
        if self.capture_traffic:
            self.pcap_dir = f"tanium_pcaps_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.makedirs(self.pcap_dir, exist_ok=True)
            print(f"  [+] Packet captures will be saved to: {self.pcap_dir}")

    def run_single_test(self, iteration, cdn_enabled):
        """Run a single download test"""
        mode = "CDN" if cdn_enabled else "Legacy"
        print(f"\n{'='*60}", flush=True)
        print(f"[{mode}] Iteration {iteration + 1}/{self.iterations}", flush=True)
        print(f"{'='*60}", flush=True)

        # Start packet capture if enabled
        pcap_file = None
        if self.capture_traffic:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            pcap_file = os.path.join(
                self.pcap_dir,
                f"{mode.lower()}_iteration_{iteration + 1}_{timestamp}.pcap"
            )
            # Filter for Tanium ports: 17472 (legacy) and 443 (CDN)
            self.controller.start_tcpdump(pcap_file, "port 443 or port 17472")

        # Request download
        identifier_type = "hash" if self.is_hash else "URL"
        print(f"  [+] Requesting download ({identifier_type}): {self.file_identifier}", flush=True)
        success, file_name = self.api_client.download_file(self.file_identifier, is_hash=self.is_hash)

        if not success:
            # Stop capture if it was started
            if self.capture_traffic:
                self.controller.stop_tcpdump()

            return {
                "iteration": iteration + 1,
                "mode": mode,
                "status": "Failed",
                "duration": 0,
                "file_size": 0,
                "throughput_mbps": 0,
                "pcap_file": pcap_file
            }

        # Monitor download
        print(f"  [+] Monitoring download...", flush=True)
        status, path, duration, file_size = self.api_client.monitor_download(self.file_identifier, is_hash=self.is_hash)

        # Stop packet capture if enabled
        if self.capture_traffic:
            self.controller.stop_tcpdump()

        # Calculate throughput
        throughput_mbps = 0
        if status == "Completed" and duration > 0:
            throughput_mbps = (file_size * 8) / (duration * 1000000)  # Mbps

        result = {
            "iteration": iteration + 1,
            "mode": mode,
            "status": status,
            "duration": duration,
            "file_size": file_size,
            "throughput_mbps": throughput_mbps,
            "timestamp": datetime.now().isoformat()
        }

        if self.capture_traffic:
            result["pcap_file"] = pcap_file

        print(f"\n  Results:", flush=True)
        print(f"    Status: {status}", flush=True)
        print(f"    Duration: {duration:.2f} seconds", flush=True)
        print(f"    File Size: {file_size / (1024*1024):.2f} MB", flush=True)
        print(f"    Throughput: {throughput_mbps:.2f} Mbps", flush=True)
        if self.capture_traffic and pcap_file:
            print(f"    Packet capture: {pcap_file}", flush=True)

        return result

    def run_tests(self, cdn_enabled):
        """Run all iterations for a mode"""
        mode = "CDN" if cdn_enabled else "Legacy"
        print(f"\n{'#'*60}")
        print(f"# Starting {mode} Tests")
        print(f"{'#'*60}")

        for i in range(self.iterations):
            # Stop service, clear downloads, then restart
            self.controller.stop_service()
            self.controller.clear_downloads()
            self.controller.start_service()
            time.sleep(2)  # Wait for service to stabilize

            # Run test
            result = self.run_single_test(i, cdn_enabled)
            self.results.append(result)

            time.sleep(2)  # Brief pause between iterations

    def run_full_test(self):
        """Run complete test suite: Legacy then CDN"""
        print(f"\nStarting Tanium Client Download Performance Test")
        identifier_type = "Hash" if self.is_hash else "URL"
        print(f"File {identifier_type}: {self.file_identifier}")
        print(f"Iterations per mode: {self.iterations}")

        # Test 1: Legacy mode (CDN disabled)
        print(f"\n\n{'#'*60}")
        print(f"# Phase 1: Legacy Downloads (Port 17472)")
        print(f"{'#'*60}")
        self.controller.set_cdn_config(False)

        self.run_tests(cdn_enabled=False)

        # Test 2: CDN mode
        print(f"\n\n{'#'*60}")
        print(f"# Phase 2: CDN Downloads (Port 443)")
        print(f"{'#'*60}")
        self.controller.set_cdn_config(True)

        self.run_tests(cdn_enabled=True)

        # Generate report
        self.generate_report()

    def generate_report(self):
        """Generate and display test results"""
        print(f"\n\n{'#'*60}")
        print(f"# Test Results Summary")
        print(f"{'#'*60}")

        # Separate results by mode
        legacy_results = [r for r in self.results if r["mode"] == "Legacy"]
        cdn_results = [r for r in self.results if r["mode"] == "CDN"]

        def calculate_stats(results):
            completed = [r for r in results if r["status"] == "Completed"]
            if not completed:
                return {
                    "count": 0,
                    "avg_duration": 0,
                    "avg_throughput": 0,
                    "min_duration": 0,
                    "max_duration": 0,
                    "stddev_duration": 0,
                    "stddev_throughput": 0
                }

            durations = [r["duration"] for r in completed]
            throughputs = [r["throughput_mbps"] for r in completed]

            avg_duration = sum(durations) / len(durations)
            avg_throughput = sum(throughputs) / len(throughputs)

            # Calculate standard deviation
            if len(durations) > 1:
                variance_duration = sum((x - avg_duration) ** 2 for x in durations) / len(durations)
                stddev_duration = variance_duration ** 0.5

                variance_throughput = sum((x - avg_throughput) ** 2 for x in throughputs) / len(throughputs)
                stddev_throughput = variance_throughput ** 0.5
            else:
                stddev_duration = 0
                stddev_throughput = 0

            return {
                "count": len(completed),
                "avg_duration": avg_duration,
                "avg_throughput": avg_throughput,
                "min_duration": min(durations),
                "max_duration": max(durations),
                "stddev_duration": stddev_duration,
                "stddev_throughput": stddev_throughput
            }

        legacy_stats = calculate_stats(legacy_results)
        cdn_stats = calculate_stats(cdn_results)

        print(f"\nLegacy (Port 17472):")
        print(f"  Completed: {legacy_stats['count']}/{len(legacy_results)}")
        if legacy_stats['count'] > 0:
            print(f"  Duration:")
            print(f"    Average: {legacy_stats['avg_duration']:.2f}s")
            print(f"    Min: {legacy_stats['min_duration']:.2f}s")
            print(f"    Max: {legacy_stats['max_duration']:.2f}s")
            print(f"    Std Dev: {legacy_stats['stddev_duration']:.2f}s")
            print(f"  Throughput:")
            print(f"    Average: {legacy_stats['avg_throughput']:.2f} Mbps")
            print(f"    Std Dev: {legacy_stats['stddev_throughput']:.2f} Mbps")

        print(f"\nCDN (Port 443):")
        print(f"  Completed: {cdn_stats['count']}/{len(cdn_results)}")
        if cdn_stats['count'] > 0:
            print(f"  Duration:")
            print(f"    Average: {cdn_stats['avg_duration']:.2f}s")
            print(f"    Min: {cdn_stats['min_duration']:.2f}s")
            print(f"    Max: {cdn_stats['max_duration']:.2f}s")
            print(f"    Std Dev: {cdn_stats['stddev_duration']:.2f}s")
            print(f"  Throughput:")
            print(f"    Average: {cdn_stats['avg_throughput']:.2f} Mbps")
            print(f"    Std Dev: {cdn_stats['stddev_throughput']:.2f} Mbps")

        # Calculate comparison
        if legacy_stats['count'] > 0 and cdn_stats['count'] > 0:
            duration_diff_pct = ((legacy_stats['avg_duration'] - cdn_stats['avg_duration']) /
                                legacy_stats['avg_duration'] * 100)
            throughput_diff_pct = ((cdn_stats['avg_throughput'] - legacy_stats['avg_throughput']) /
                                  legacy_stats['avg_throughput'] * 100)

            print(f"\nCDN vs Legacy Comparison:")
            if duration_diff_pct > 0:
                print(f"  Duration: CDN is {duration_diff_pct:.1f}% faster")
            elif duration_diff_pct < 0:
                print(f"  Duration: CDN is {abs(duration_diff_pct):.1f}% slower")
            else:
                print(f"  Duration: Same performance")

            if throughput_diff_pct > 0:
                print(f"  Throughput: CDN is {throughput_diff_pct:.1f}% higher")
            elif throughput_diff_pct < 0:
                print(f"  Throughput: CDN is {abs(throughput_diff_pct):.1f}% lower")
            else:
                print(f"  Throughput: Same performance")

        # Save to file
        output_file = f"tanium_perf_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        test_data = {
            "test_info": {
                "file_identifier": self.file_identifier,
                "is_hash": self.is_hash,
                "iterations": self.iterations,
                "capture_traffic": self.capture_traffic,
                "timestamp": datetime.now().isoformat()
            },
            "results": self.results,
            "summary": {
                "legacy": legacy_stats,
                "cdn": cdn_stats
            }
        }

        if self.capture_traffic:
            test_data["test_info"]["pcap_directory"] = self.pcap_dir

        with open(output_file, "w") as f:
            json.dump(test_data, f, indent=2)

        print(f"\n[+] Detailed results saved to: {output_file}")
        if self.capture_traffic:
            print(f"[+] Packet captures saved to: {self.pcap_dir}/")


def main():
    parser = argparse.ArgumentParser(
        description="Test Tanium Client download performance: Legacy vs CDN"
    )
    parser.add_argument(
        "--tc-dir",
        required=False,
        default=None,
        help="Path to Tanium Client directory (auto-detected if not specified)"
    )

    # Mutually exclusive group for file specification
    file_group = parser.add_mutually_exclusive_group(required=True)
    file_group.add_argument(
        "--file-url",
        help="URL of file to download for testing"
    )
    file_group.add_argument(
        "--file-hash",
        help="SHA-256 hash of file to download for testing (constructs URL as https://127.0.0.1/cache/<HASH>)"
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Number of iterations per mode (default: 5)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show verbose SOAP request/response XML"
    )
    parser.add_argument(
        "--capture-traffic",
        action="store_true",
        help="Capture network traffic (tcpdump) for each test iteration"
    )

    args = parser.parse_args()

    # Determine file identifier and type
    if args.file_hash:
        file_identifier = args.file_hash
        is_hash = True
    else:
        file_identifier = args.file_url
        is_hash = False

    # Run the test
    test = PerformanceTest(
        file_identifier=file_identifier,
        tc_dir=args.tc_dir,
        iterations=args.iterations,
        verbose=args.verbose,
        is_hash=is_hash,
        capture_traffic=args.capture_traffic
    )

    try:
        test.run_full_test()
    except KeyboardInterrupt:
        print("\n\n[!] Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
