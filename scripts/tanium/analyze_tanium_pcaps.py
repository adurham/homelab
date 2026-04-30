#!/usr/bin/env python3
"""
Tanium Download PCAP Analysis Tool

Analyzes packet captures from Tanium download performance tests to identify
performance bottlenecks and network issues.

Usage:
    python3 analyze_tanium_pcaps.py --pcap-dir tanium_pcaps_20251030_014826
    python3 analyze_tanium_pcaps.py --pcap-dir tanium_pcaps_20251030_014826 --detailed
    python3 analyze_tanium_pcaps.py --pcap-file legacy_iteration_1.pcap --server-port 17472

Requires:
    - tshark (Wireshark command-line tool)
    - Python 3.6+

Analysis performed:
    - TCP Round-Trip Time (RTT) statistics
    - Packet loss and retransmission rates
    - TCP window sizes and scaling
    - Connection establishment time
    - Throughput over time
    - Server vs client behavior
"""

import subprocess
import json
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
import statistics
from multiprocessing import Pool, cpu_count


class PCAPAnalyzer:
    """Analyzes PCAP files for TCP performance metrics"""

    def __init__(self, pcap_file, server_port=None, quiet=False):
        self.pcap_file = pcap_file
        self.server_port = server_port
        self.metrics = {}
        self.quiet = quiet

        # Verify tshark is available
        try:
            subprocess.run(["tshark", "--version"], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            if not quiet:
                print("[!] Error: tshark not found. Please install Wireshark.")
            sys.exit(1)

    def _log(self, message):
        """Print message unless in quiet mode"""
        if not self.quiet:
            print(message)

    def _run_tshark(self, fields, display_filter=None):
        """Run tshark with specified fields and filter"""
        cmd = [
            "tshark",
            "-r", self.pcap_file,
            "-T", "fields",
            "-E", "separator=|",
            "-E", "header=y"
        ]

        for field in fields:
            cmd.extend(["-e", field])

        if display_filter:
            cmd.extend(["-Y", display_filter])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            self._log(f"[!] tshark error: {e.stderr}")
            return None

    def detect_server_port(self):
        """Auto-detect which port is the server port (17472 for legacy, 443 for CDN)"""
        if not self.quiet:
            self._log(f"  [*] Auto-detecting server port...")

        # First, check filename to determine expected mode
        basename = os.path.basename(self.pcap_file).lower()
        expected_port = None
        if 'cdn' in basename:
            expected_port = 443
            if not self.quiet:
                self._log(f"  [*] Filename indicates CDN mode, using port 443")
        elif 'legacy' in basename:
            expected_port = 17472
            if not self.quiet:
                self._log(f"  [*] Filename indicates Legacy mode, using port 17472")

        if expected_port:
            return expected_port

        # Fallback: Look for ports 17472 and 443 in traffic
        output = self._run_tshark(
            ["tcp.srcport", "tcp.dstport"],
            display_filter="tcp"
        )

        if not output:
            return None

        port_counts = defaultdict(int)
        for line in output.strip().split('\n')[1:]:  # Skip header
            if not line:
                continue
            parts = line.split('|')
            if len(parts) == 2:
                src_port = parts[0].strip()
                dst_port = parts[1].strip()
                if src_port in ['17472', '443']:
                    port_counts[src_port] += 1
                if dst_port in ['17472', '443']:
                    port_counts[dst_port] += 1

        if not port_counts:
            return None

        # Most common port is likely the server
        server_port = max(port_counts, key=port_counts.get)
        port_name = "Legacy" if server_port == "17472" else "CDN"
        self._log(f"  [+] Detected server port: {server_port} ({port_name})")
        return int(server_port)

    def analyze_basic_stats(self):
        """Get basic connection statistics"""
        self._log(f"  [*] Analyzing basic statistics...")

        # Get packet count and duration
        output = self._run_tshark(
            ["frame.number", "frame.time_relative", "frame.len"],
            display_filter="tcp"
        )

        if not output:
            return

        lines = output.strip().split('\n')[1:]  # Skip header
        if not lines:
            return

        packet_count = len(lines)
        last_line = lines[-1].split('|')

        try:
            duration = float(last_line[1])
            total_bytes = sum(int(line.split('|')[2]) for line in lines if line)

            self.metrics["basic"] = {
                "total_packets": packet_count,
                "duration_seconds": duration,
                "total_bytes": total_bytes,
                "avg_throughput_mbps": (total_bytes * 8) / (duration * 1_000_000) if duration > 0 else 0
            }
        except (ValueError, IndexError) as e:
            self._log(f"  [!] Error parsing basic stats: {e}")

    def analyze_rtt(self):
        """Analyze Round-Trip Time (RTT) from TCP handshake and data transfer"""
        self._log(f"  [*] Analyzing RTT...")

        # Get RTT measurements from tshark's TCP analysis
        output = self._run_tshark(
            ["frame.time_relative", "tcp.analysis.ack_rtt"],
            display_filter="tcp.analysis.ack_rtt"
        )

        if not output:
            self.metrics["rtt"] = {"samples": 0}
            return

        lines = output.strip().split('\n')[1:]  # Skip header
        rtt_values = []

        for line in lines:
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 2 and parts[1]:
                try:
                    rtt_ms = float(parts[1]) * 1000  # Convert to ms
                    rtt_values.append(rtt_ms)
                except ValueError:
                    continue

        if rtt_values:
            self.metrics["rtt"] = {
                "samples": len(rtt_values),
                "min_ms": min(rtt_values),
                "max_ms": max(rtt_values),
                "avg_ms": statistics.mean(rtt_values),
                "median_ms": statistics.median(rtt_values),
                "stddev_ms": statistics.stdev(rtt_values) if len(rtt_values) > 1 else 0,
                "p95_ms": self._percentile(rtt_values, 95),
                "p99_ms": self._percentile(rtt_values, 99)
            }
        else:
            self.metrics["rtt"] = {"samples": 0}

    def analyze_retransmissions(self):
        """Analyze packet retransmissions and loss"""
        self._log(f"  [*] Analyzing retransmissions...")

        # Count retransmissions
        output = self._run_tshark(
            ["frame.number"],
            display_filter="tcp.analysis.retransmission"
        )

        retrans_count = 0
        if output:
            lines = output.strip().split('\n')[1:]  # Skip header
            retrans_count = len([l for l in lines if l])

        # Get total TCP packets for percentage
        total_output = self._run_tshark(
            ["frame.number"],
            display_filter="tcp"
        )

        total_packets = 0
        if total_output:
            lines = total_output.strip().split('\n')[1:]
            total_packets = len([l for l in lines if l])

        # Check for fast retransmissions
        fast_retrans_output = self._run_tshark(
            ["frame.number"],
            display_filter="tcp.analysis.fast_retransmission"
        )

        fast_retrans_count = 0
        if fast_retrans_output:
            lines = fast_retrans_output.strip().split('\n')[1:]
            fast_retrans_count = len([l for l in lines if l])

        # Check for spurious retransmissions
        spurious_output = self._run_tshark(
            ["frame.number"],
            display_filter="tcp.analysis.spurious_retransmission"
        )

        spurious_count = 0
        if spurious_output:
            lines = spurious_output.strip().split('\n')[1:]
            spurious_count = len([l for l in lines if l])

        self.metrics["retransmissions"] = {
            "total_retransmissions": retrans_count,
            "fast_retransmissions": fast_retrans_count,
            "spurious_retransmissions": spurious_count,
            "total_tcp_packets": total_packets,
            "retransmission_rate_pct": (retrans_count / total_packets * 100) if total_packets > 0 else 0
        }

    def analyze_window_sizes(self):
        """Analyze TCP window sizes"""
        self._log(f"  [*] Analyzing TCP window sizes...")

        if not self.server_port:
            self.metrics["window_sizes"] = {"error": "Server port not specified"}
            return

        # Analyze receive window from server (shows client's advertised window)
        client_window_output = self._run_tshark(
            ["tcp.window_size"],
            display_filter=f"tcp.srcport == {self.server_port}"
        )

        # Analyze receive window from client (shows server's advertised window)
        server_window_output = self._run_tshark(
            ["tcp.window_size"],
            display_filter=f"tcp.dstport == {self.server_port}"
        )

        def parse_windows(output):
            if not output:
                return []
            lines = output.strip().split('\n')[1:]  # Skip header
            windows = []
            for line in lines:
                if line and line.strip():
                    try:
                        windows.append(int(line.strip()))
                    except ValueError:
                        continue
            return windows

        client_windows = parse_windows(client_window_output)
        server_windows = parse_windows(server_window_output)

        def calc_stats(windows, name):
            if not windows:
                return {f"{name}_samples": 0}
            return {
                f"{name}_samples": len(windows),
                f"{name}_min_bytes": min(windows),
                f"{name}_max_bytes": max(windows),
                f"{name}_avg_bytes": statistics.mean(windows),
                f"{name}_median_bytes": statistics.median(windows)
            }

        self.metrics["window_sizes"] = {
            **calc_stats(client_windows, "client_advertised"),
            **calc_stats(server_windows, "server_advertised")
        }

    def analyze_connection_time(self):
        """Analyze TCP connection establishment time"""
        self._log(f"  [*] Analyzing connection establishment...")

        # Find SYN and SYN-ACK packets
        output = self._run_tshark(
            ["frame.time_relative", "tcp.flags.syn", "tcp.flags.ack"],
            display_filter="tcp.flags.syn == 1"
        )

        if not output:
            self.metrics["connection"] = {"error": "No SYN packets found"}
            return

        lines = output.strip().split('\n')[1:]  # Skip header
        syn_time = None
        synack_time = None

        for line in lines:
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 3:
                try:
                    time = float(parts[0])
                    syn_flag = parts[1].strip()
                    ack_flag = parts[2].strip()

                    if syn_flag == '1' and ack_flag == '0':
                        syn_time = time
                    elif syn_flag == '1' and ack_flag == '1' and syn_time is not None:
                        synack_time = time
                        break
                except (ValueError, IndexError):
                    continue

        if syn_time is not None and synack_time is not None:
            handshake_time_ms = (synack_time - syn_time) * 1000
            self.metrics["connection"] = {
                "handshake_time_ms": handshake_time_ms,
                "syn_time": syn_time,
                "synack_time": synack_time
            }
        else:
            self.metrics["connection"] = {"error": "Could not find complete handshake"}

    def analyze_throughput_over_time(self, interval_seconds=1):
        """Calculate throughput over time intervals"""
        self._log(f"  [*] Analyzing throughput over time (interval: {interval_seconds}s)...")

        if not self.server_port:
            self.metrics["throughput_timeline"] = {"error": "Server port not specified"}
            return

        # Get data packets from server (downloads)
        output = self._run_tshark(
            ["frame.time_relative", "tcp.len"],
            display_filter=f"tcp.srcport == {self.server_port} and tcp.len > 0"
        )

        if not output:
            self.metrics["throughput_timeline"] = {"error": "No data packets found"}
            return

        lines = output.strip().split('\n')[1:]  # Skip header

        # Group by time intervals
        interval_data = defaultdict(int)
        for line in lines:
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 2:
                try:
                    time = float(parts[0])
                    tcp_len = int(parts[1])
                    interval = int(time / interval_seconds)
                    interval_data[interval] += tcp_len
                except (ValueError, IndexError):
                    continue

        # Calculate throughput for each interval
        throughput_timeline = []
        for interval in sorted(interval_data.keys()):
            bytes_transferred = interval_data[interval]
            mbps = (bytes_transferred * 8) / (interval_seconds * 1_000_000)
            throughput_timeline.append({
                "interval": interval,
                "time_start": interval * interval_seconds,
                "time_end": (interval + 1) * interval_seconds,
                "bytes": bytes_transferred,
                "mbps": mbps
            })

        if throughput_timeline:
            mbps_values = [t["mbps"] for t in throughput_timeline]
            self.metrics["throughput_timeline"] = {
                "interval_seconds": interval_seconds,
                "intervals": throughput_timeline,
                "stats": {
                    "min_mbps": min(mbps_values),
                    "max_mbps": max(mbps_values),
                    "avg_mbps": statistics.mean(mbps_values),
                    "median_mbps": statistics.median(mbps_values),
                    "stddev_mbps": statistics.stdev(mbps_values) if len(mbps_values) > 1 else 0
                }
            }
        else:
            self.metrics["throughput_timeline"] = {"intervals": []}

    def analyze_tcp_flags(self):
        """Analyze TCP flags for connection issues"""
        self._log(f"  [*] Analyzing TCP flags...")

        # Count resets
        rst_output = self._run_tshark(
            ["frame.number"],
            display_filter="tcp.flags.reset == 1"
        )
        rst_count = 0
        if rst_output:
            lines = rst_output.strip().split('\n')[1:]
            rst_count = len([l for l in lines if l])

        # Count duplicate ACKs
        dup_ack_output = self._run_tshark(
            ["frame.number"],
            display_filter="tcp.analysis.duplicate_ack"
        )
        dup_ack_count = 0
        if dup_ack_output:
            lines = dup_ack_output.strip().split('\n')[1:]
            dup_ack_count = len([l for l in lines if l])

        # Count zero windows
        zero_window_output = self._run_tshark(
            ["frame.number"],
            display_filter="tcp.analysis.zero_window"
        )
        zero_window_count = 0
        if zero_window_output:
            lines = zero_window_output.strip().split('\n')[1:]
            zero_window_count = len([l for l in lines if l])

        self.metrics["tcp_flags"] = {
            "resets": rst_count,
            "duplicate_acks": dup_ack_count,
            "zero_windows": zero_window_count
        }

    def analyze_server_response_latency(self):
        """Measure how long the SERVER takes to respond to requests (not RTT)"""
        self._log(f"  [*] Analyzing server response latency...")

        if not self.server_port:
            self.metrics["server_response_latency"] = {"error": "Server port not specified"}
            return

        # Get all TCP packets with timestamps, sequence numbers, and ports
        output = self._run_tshark(
            ["frame.time_relative", "tcp.srcport", "tcp.dstport", "tcp.len", "tcp.flags.syn", "tcp.flags.ack"]
        )

        if not output:
            self.metrics["server_response_latency"] = {"error": "No data"}
            return

        lines = output.strip().split('\n')[1:]  # Skip header

        # Track request/response pairs
        client_requests = []  # Time when client sends data to server
        server_responses = []  # Time when server sends data back

        for line in lines:
            if not line:
                continue
            parts = line.split('|')
            if len(parts) < 6:
                continue

            try:
                time = float(parts[0])
                src_port = parts[1].strip()
                dst_port = parts[2].strip()
                tcp_len = int(parts[3]) if parts[3] else 0
                syn = parts[4].strip()
                ack = parts[5].strip()

                # Skip handshake packets
                if syn == '1':
                    continue

                # Client sending request to server (dst_port = server_port)
                if dst_port == str(self.server_port) and tcp_len > 0:
                    client_requests.append(time)

                # Server sending data to client (src_port = server_port)
                elif src_port == str(self.server_port) and tcp_len > 0:
                    server_responses.append(time)

            except (ValueError, IndexError):
                continue

        # Calculate time between client requests and server responses
        response_delays = []

        # Sort both lists for efficient matching
        client_requests.sort()
        server_responses.sort()

        # Use pointer-based matching instead of nested loops
        req_idx = 0
        for resp_time in server_responses:
            # Move pointer forward to find most recent request before this response
            while req_idx < len(client_requests) - 1 and client_requests[req_idx + 1] < resp_time:
                req_idx += 1

            # If we found a request before this response
            if req_idx < len(client_requests) and client_requests[req_idx] < resp_time:
                delay = (resp_time - client_requests[req_idx]) * 1000  # Convert to ms
                if delay < 1000:  # Sanity check - ignore delays > 1 second
                    response_delays.append(delay)

        if response_delays:
            self.metrics["server_response_latency"] = {
                "samples": len(response_delays),
                "min_ms": min(response_delays),
                "max_ms": max(response_delays),
                "avg_ms": statistics.mean(response_delays),
                "median_ms": statistics.median(response_delays),
                "p95_ms": self._percentile(response_delays, 95),
                "p99_ms": self._percentile(response_delays, 99),
                "stddev_ms": statistics.stdev(response_delays) if len(response_delays) > 1 else 0
            }
        else:
            self.metrics["server_response_latency"] = {"samples": 0}

    def analyze_inter_packet_delay(self):
        """Measure delays between consecutive packets from the server"""
        self._log(f"  [*] Analyzing inter-packet delays from server...")

        if not self.server_port:
            self.metrics["inter_packet_delay"] = {"error": "Server port not specified"}
            return

        # Get data packets from server with timestamps
        output = self._run_tshark(
            ["frame.time_relative", "tcp.len"],
            display_filter=f"tcp.srcport == {self.server_port} and tcp.len > 0"
        )

        if not output:
            self.metrics["inter_packet_delay"] = {"samples": 0}
            return

        lines = output.strip().split('\n')[1:]  # Skip header

        packet_times = []
        for line in lines:
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 1:
                try:
                    time = float(parts[0])
                    packet_times.append(time)
                except ValueError:
                    continue

        if len(packet_times) < 2:
            self.metrics["inter_packet_delay"] = {"samples": 0}
            return

        # Calculate delays between consecutive packets
        inter_packet_delays = []
        for i in range(1, len(packet_times)):
            delay_ms = (packet_times[i] - packet_times[i-1]) * 1000
            inter_packet_delays.append(delay_ms)

        self.metrics["inter_packet_delay"] = {
            "samples": len(inter_packet_delays),
            "min_ms": min(inter_packet_delays),
            "max_ms": max(inter_packet_delays),
            "avg_ms": statistics.mean(inter_packet_delays),
            "median_ms": statistics.median(inter_packet_delays),
            "p95_ms": self._percentile(inter_packet_delays, 95),
            "p99_ms": self._percentile(inter_packet_delays, 99),
            "stddev_ms": statistics.stdev(inter_packet_delays) if len(inter_packet_delays) > 1 else 0
        }

    def analyze_burst_pattern(self, burst_threshold_ms=10):
        """
        Detect burst patterns in server sending behavior.
        A burst is defined as a series of packets sent with very short delays,
        followed by a longer gap. This indicates pacing/throttling.
        """
        self._log(f"  [*] Analyzing burst patterns...")

        if not self.server_port:
            self.metrics["burst_pattern"] = {"error": "Server port not specified"}
            return

        # Get data packets from server with timestamps
        output = self._run_tshark(
            ["frame.time_relative"],
            display_filter=f"tcp.srcport == {self.server_port} and tcp.len > 0"
        )

        if not output:
            self.metrics["burst_pattern"] = {"samples": 0}
            return

        lines = output.strip().split('\n')[1:]  # Skip header

        packet_times = []
        for line in lines:
            if not line:
                continue
            try:
                time = float(line.strip())
                packet_times.append(time)
            except ValueError:
                continue

        if len(packet_times) < 2:
            self.metrics["burst_pattern"] = {"samples": 0}
            return

        # Calculate inter-packet delays
        delays = []
        for i in range(1, len(packet_times)):
            delay_ms = (packet_times[i] - packet_times[i-1]) * 1000
            delays.append(delay_ms)

        # Detect bursts: periods of fast sending followed by gaps
        bursts = []
        current_burst = []
        burst_gaps = []

        for i, delay in enumerate(delays):
            if delay < burst_threshold_ms:
                # Fast packet, part of current burst
                current_burst.append(i)
            else:
                # Gap found
                if len(current_burst) > 0:
                    bursts.append(len(current_burst) + 1)  # +1 for first packet
                    burst_gaps.append(delay)
                    current_burst = []

        # Don't forget last burst
        if len(current_burst) > 0:
            bursts.append(len(current_burst) + 1)

        if bursts:
            self.metrics["burst_pattern"] = {
                "total_bursts": len(bursts),
                "avg_burst_size": statistics.mean(bursts),
                "min_burst_size": min(bursts),
                "max_burst_size": max(bursts),
                "avg_gap_ms": statistics.mean(burst_gaps) if burst_gaps else 0,
                "total_packets": len(packet_times)
            }
        else:
            self.metrics["burst_pattern"] = {
                "total_bursts": 0,
                "total_packets": len(packet_times)
            }

    def analyze_pacing_precision(self):
        """
        Analyze if inter-packet delays are too uniform/precise.
        Algorithmic pacing has very consistent delays.
        Organic TCP behavior has more natural variation.
        """
        self._log(f"  [*] Analyzing pacing precision...")

        if not self.server_port:
            self.metrics["pacing_precision"] = {"error": "Server port not specified"}
            return

        # Get data packets from server with timestamps
        output = self._run_tshark(
            ["frame.time_relative"],
            display_filter=f"tcp.srcport == {self.server_port} and tcp.len > 0"
        )

        if not output:
            self.metrics["pacing_precision"] = {"samples": 0}
            return

        lines = output.strip().split('\n')[1:]  # Skip header

        packet_times = []
        for line in lines:
            if not line:
                continue
            try:
                time = float(line.strip())
                packet_times.append(time)
            except ValueError:
                continue

        if len(packet_times) < 10:
            self.metrics["pacing_precision"] = {"samples": 0}
            return

        # Calculate inter-packet delays
        delays = []
        for i in range(1, len(packet_times)):
            delay_ms = (packet_times[i] - packet_times[i-1]) * 1000
            delays.append(delay_ms)

        # Filter out obvious bursts (very small delays) and gaps (very large delays)
        # Focus on the "typical" pacing delays
        filtered_delays = [d for d in delays if 0.01 < d < 10]

        if not filtered_delays:
            self.metrics["pacing_precision"] = {"samples": 0}
            return

        avg_delay = statistics.mean(filtered_delays)
        stddev = statistics.stdev(filtered_delays) if len(filtered_delays) > 1 else 0
        coefficient_of_variation = (stddev / avg_delay * 100) if avg_delay > 0 else 0

        # Check for clustering around specific values (sign of algorithmic pacing)
        delay_buckets = defaultdict(int)
        bucket_size = 0.1  # ms
        for delay in filtered_delays:
            bucket = round(delay / bucket_size) * bucket_size
            delay_buckets[bucket] += 1

        # Find most common delay values
        sorted_buckets = sorted(delay_buckets.items(), key=lambda x: x[1], reverse=True)
        top_3_buckets = sorted_buckets[:3] if len(sorted_buckets) >= 3 else sorted_buckets
        top_3_percentage = sum(count for _, count in top_3_buckets) / len(filtered_delays) * 100

        self.metrics["pacing_precision"] = {
            "samples": len(filtered_delays),
            "avg_delay_ms": avg_delay,
            "stddev_ms": stddev,
            "coefficient_of_variation": coefficient_of_variation,
            "top_3_clustering_pct": top_3_percentage
        }

    @staticmethod
    def _percentile(data, percentile):
        """Calculate percentile of a list"""
        sorted_data = sorted(data)
        index = (len(sorted_data) - 1) * percentile / 100
        floor_index = int(index)
        if floor_index + 1 < len(sorted_data):
            return sorted_data[floor_index] + (index - floor_index) * (
                sorted_data[floor_index + 1] - sorted_data[floor_index]
            )
        return sorted_data[floor_index]

    def run_full_analysis(self):
        """Run all analysis methods"""
        self._log(f"\n[+] Analyzing: {self.pcap_file}")

        # Auto-detect server port if not provided
        if not self.server_port:
            self.server_port = self.detect_server_port()

        self.analyze_basic_stats()
        self.analyze_connection_time()
        self.analyze_rtt()
        self.analyze_retransmissions()
        # self.analyze_window_sizes()  # Removed - window size is a symptom, not a cause
        self.analyze_tcp_flags()
        self.analyze_throughput_over_time()
        self.analyze_server_response_latency()
        self.analyze_inter_packet_delay()
        self.analyze_burst_pattern()
        self.analyze_pacing_precision()

        return self.metrics

    def print_summary(self):
        """Print analysis summary"""
        print(f"\n{'='*70}")
        print(f"ANALYSIS SUMMARY: {os.path.basename(self.pcap_file)}")
        print(f"{'='*70}")

        if "basic" in self.metrics:
            b = self.metrics["basic"]
            print(f"\n[Basic Statistics]")
            print(f"  Duration: {b['duration_seconds']:.2f} seconds")
            print(f"  Total Packets: {b['total_packets']}")
            print(f"  Total Bytes: {b['total_bytes'] / (1024*1024):.2f} MB")
            print(f"  Average Throughput: {b['avg_throughput_mbps']:.2f} Mbps")

        if "connection" in self.metrics and "handshake_time_ms" in self.metrics["connection"]:
            c = self.metrics["connection"]
            print(f"\n[Connection]")
            print(f"  TCP Handshake Time: {c['handshake_time_ms']:.2f} ms")

        if "rtt" in self.metrics and self.metrics["rtt"]["samples"] > 0:
            r = self.metrics["rtt"]
            print(f"\n[Round-Trip Time (RTT)]")
            print(f"  Samples: {r['samples']}")
            print(f"  Average: {r['avg_ms']:.2f} ms")
            print(f"  Median: {r['median_ms']:.2f} ms")
            print(f"  Min: {r['min_ms']:.2f} ms")
            print(f"  Max: {r['max_ms']:.2f} ms")
            print(f"  Std Dev: {r['stddev_ms']:.2f} ms")
            print(f"  95th percentile: {r['p95_ms']:.2f} ms")
            print(f"  99th percentile: {r['p99_ms']:.2f} ms")

        if "retransmissions" in self.metrics:
            r = self.metrics["retransmissions"]
            print(f"\n[Retransmissions]")
            print(f"  Total Retransmissions: {r['total_retransmissions']}")
            print(f"  Fast Retransmissions: {r['fast_retransmissions']}")
            print(f"  Spurious Retransmissions: {r['spurious_retransmissions']}")
            print(f"  Retransmission Rate: {r['retransmission_rate_pct']:.3f}%")

        # Window sizes section removed - it's a symptom, not a cause of performance issues

        if "tcp_flags" in self.metrics:
            f = self.metrics["tcp_flags"]
            print(f"\n[TCP Issues]")
            print(f"  Resets: {f['resets']}")
            print(f"  Duplicate ACKs: {f['duplicate_acks']}")
            print(f"  Zero Windows: {f['zero_windows']}")

        if "throughput_timeline" in self.metrics and "stats" in self.metrics["throughput_timeline"]:
            t = self.metrics["throughput_timeline"]["stats"]
            print(f"\n[Throughput Over Time]")
            print(f"  Interval: {self.metrics['throughput_timeline']['interval_seconds']}s")
            print(f"  Average: {t['avg_mbps']:.2f} Mbps")
            print(f"  Median: {t['median_mbps']:.2f} Mbps")
            print(f"  Min: {t['min_mbps']:.2f} Mbps")
            print(f"  Max: {t['max_mbps']:.2f} Mbps")
            print(f"  Std Dev: {t['stddev_mbps']:.2f} Mbps")

        if "server_response_latency" in self.metrics and self.metrics["server_response_latency"].get("samples", 0) > 0:
            s = self.metrics["server_response_latency"]
            print(f"\n[Server Response Latency] ⚠️ ROOT CAUSE INDICATOR")
            print(f"  How long does the server take to respond after receiving a request?")
            print(f"  Samples: {s['samples']}")
            print(f"  Average: {s['avg_ms']:.2f} ms")
            print(f"  Median: {s['median_ms']:.2f} ms")
            print(f"  Min: {s['min_ms']:.2f} ms")
            print(f"  Max: {s['max_ms']:.2f} ms")
            print(f"  95th percentile: {s['p95_ms']:.2f} ms")
            print(f"  99th percentile: {s['p99_ms']:.2f} ms")
            print(f"  Std Dev: {s['stddev_ms']:.2f} ms")

        if "inter_packet_delay" in self.metrics and self.metrics["inter_packet_delay"].get("samples", 0) > 0:
            i = self.metrics["inter_packet_delay"]
            print(f"\n[Inter-Packet Delays from Server] ⚠️ ROOT CAUSE INDICATOR")
            print(f"  How much time between consecutive data packets from server?")
            print(f"  Samples: {i['samples']}")
            print(f"  Average: {i['avg_ms']:.3f} ms")
            print(f"  Median: {i['median_ms']:.3f} ms")
            print(f"  Min: {i['min_ms']:.3f} ms")
            print(f"  Max: {i['max_ms']:.3f} ms")
            print(f"  95th percentile: {i['p95_ms']:.3f} ms")
            print(f"  99th percentile: {i['p99_ms']:.3f} ms")

        if "burst_pattern" in self.metrics and self.metrics["burst_pattern"].get("total_bursts", 0) > 0:
            b = self.metrics["burst_pattern"]
            print(f"\n[Burst Pattern Analysis] ⚠️ THROTTLING INDICATOR")
            print(f"  Detecting if server sends in bursts vs continuous stream...")
            print(f"  Total bursts: {b['total_bursts']}")
            print(f"  Average burst size: {b['avg_burst_size']:.1f} packets")
            print(f"  Average gap between bursts: {b['avg_gap_ms']:.2f} ms")
            if b['total_bursts'] > 100 and b['avg_gap_ms'] > 1:
                print(f"  🔴 THROTTLING: Server pacing data in bursts - algorithmic rate limiting")
            elif b['total_bursts'] > 10:
                print(f"  ⚠️  Moderate burst behavior detected")
            else:
                print(f"  ✓ Continuous sending")

        if "pacing_precision" in self.metrics and self.metrics["pacing_precision"].get("samples", 0) > 0:
            p = self.metrics["pacing_precision"]
            print(f"\n[Pacing Precision Analysis] ⚠️ THROTTLING INDICATOR")
            print(f"  Checking if delays are algorithmically precise vs organic...")
            print(f"  Average delay: {p['avg_delay_ms']:.3f} ms")
            print(f"  Coefficient of Variation: {p['coefficient_of_variation']:.1f}%")
            print(f"  Top 3 delay clustering: {p['top_3_clustering_pct']:.1f}%")
            if p['coefficient_of_variation'] < 20 and p['top_3_clustering_pct'] > 60:
                print(f"  🔴 THROTTLING: Highly precise/algorithmic pacing detected")
            elif p['coefficient_of_variation'] < 40:
                print(f"  ⚠️  Consistent pacing detected")
            else:
                print(f"  ✓ Natural TCP variation")


def _analyze_single_pcap(pcap_file):
    """Helper function for parallel processing - analyzes a single PCAP file"""
    try:
        # Use quiet mode to avoid interleaved output from parallel workers
        analyzer = PCAPAnalyzer(pcap_file, quiet=True)
        metrics = analyzer.run_full_analysis()

        # Determine category
        basename = os.path.basename(pcap_file).lower()
        if 'legacy' in basename:
            category = 'legacy'
        elif 'cdn' in basename:
            category = 'cdn'
        else:
            category = None

        return {
            "filename": os.path.basename(pcap_file),
            "category": category,
            "metrics": metrics,
            "success": True
        }
    except Exception as e:
        return {
            "filename": os.path.basename(pcap_file),
            "category": None,
            "error": str(e),
            "success": False
        }


class MultiPCAPAnalyzer:
    """Analyzes multiple PCAP files and generates comparison"""

    def __init__(self, pcap_dir, parallel=True):
        self.pcap_dir = pcap_dir
        self.results = {"legacy": [], "cdn": []}
        self.parallel = parallel

    def find_pcap_files(self):
        """Find all PCAP files in the directory"""
        if not os.path.exists(self.pcap_dir):
            print(f"[!] Error: Directory not found: {self.pcap_dir}")
            return []

        pcap_files = []
        for filename in os.listdir(self.pcap_dir):
            if filename.endswith('.pcap'):
                pcap_files.append(os.path.join(self.pcap_dir, filename))

        return sorted(pcap_files)

    def categorize_pcap(self, filename):
        """Determine if PCAP is legacy or CDN based on filename"""
        basename = os.path.basename(filename).lower()
        if 'legacy' in basename:
            return 'legacy'
        elif 'cdn' in basename:
            return 'cdn'
        return None

    def analyze_all(self):
        """Analyze all PCAP files in directory"""
        pcap_files = self.find_pcap_files()

        if not pcap_files:
            print(f"[!] No PCAP files found in {self.pcap_dir}")
            return

        print(f"[+] Found {len(pcap_files)} PCAP files")

        if self.parallel and len(pcap_files) > 1:
            # Parallel processing
            num_workers = min(cpu_count(), len(pcap_files))
            print(f"[+] Using {num_workers} parallel workers")
            print(f"[+] Analyzing {len(pcap_files)} files in parallel...\n")

            completed = 0
            with Pool(num_workers) as pool:
                # Use imap_unordered to get results as they complete
                for result in pool.imap_unordered(_analyze_single_pcap, pcap_files):
                    completed += 1
                    if result["success"] and result["category"]:
                        self.results[result["category"]].append({
                            "filename": result["filename"],
                            "metrics": result["metrics"]
                        })
                        print(f"  [{completed}/{len(pcap_files)}] ✓ {result['filename']}")
                    elif not result["success"]:
                        print(f"  [{completed}/{len(pcap_files)}] ✗ {result['filename']}: {result.get('error', 'Unknown error')}")
                    sys.stdout.flush()

            print(f"\n[+] All files analyzed!")
        else:
            # Sequential processing
            if not self.parallel:
                print(f"[+] Running in sequential mode")

            for pcap_file in pcap_files:
                category = self.categorize_pcap(pcap_file)
                if not category:
                    print(f"[!] Skipping unknown category: {pcap_file}")
                    continue

                analyzer = PCAPAnalyzer(pcap_file)
                metrics = analyzer.run_full_analysis()
                analyzer.print_summary()

                self.results[category].append({
                    "filename": os.path.basename(pcap_file),
                    "metrics": metrics
                })

        self.generate_comparison()

    def generate_comparison(self):
        """Generate comparison between Legacy and CDN"""
        print(f"\n\n{'#'*70}")
        print(f"# LEGACY vs CDN COMPARISON")
        print(f"{'#'*70}")

        for mode in ['legacy', 'cdn']:
            mode_results = self.results[mode]
            if not mode_results:
                continue

            print(f"\n[{mode.upper()}] Summary across {len(mode_results)} captures:")

            # Aggregate metrics
            throughputs = []
            rtts = []
            retrans_rates = []
            handshake_times = []
            server_response_latencies = []
            inter_packet_delays = []
            burst_counts = []
            burst_gaps = []
            pacing_covs = []
            pacing_clusters = []

            for result in mode_results:
                m = result["metrics"]

                if "basic" in m:
                    throughputs.append(m["basic"]["avg_throughput_mbps"])

                if "rtt" in m and m["rtt"]["samples"] > 0:
                    rtts.append(m["rtt"]["avg_ms"])

                if "retransmissions" in m:
                    retrans_rates.append(m["retransmissions"]["retransmission_rate_pct"])

                if "connection" in m and "handshake_time_ms" in m["connection"]:
                    handshake_times.append(m["connection"]["handshake_time_ms"])

                if "server_response_latency" in m and m["server_response_latency"].get("samples", 0) > 0:
                    server_response_latencies.append(m["server_response_latency"]["avg_ms"])

                if "inter_packet_delay" in m and m["inter_packet_delay"].get("samples", 0) > 0:
                    inter_packet_delays.append(m["inter_packet_delay"]["avg_ms"])

                if "burst_pattern" in m and m["burst_pattern"].get("total_bursts", 0) > 0:
                    burst_counts.append(m["burst_pattern"]["total_bursts"])
                    if m["burst_pattern"].get("avg_gap_ms", 0) > 0:
                        burst_gaps.append(m["burst_pattern"]["avg_gap_ms"])

                if "pacing_precision" in m and m["pacing_precision"].get("samples", 0) > 0:
                    pacing_covs.append(m["pacing_precision"]["coefficient_of_variation"])
                    pacing_clusters.append(m["pacing_precision"]["top_3_clustering_pct"])

            if throughputs:
                print(f"  Throughput: {statistics.mean(throughputs):.2f} Mbps "
                      f"(±{statistics.stdev(throughputs) if len(throughputs) > 1 else 0:.2f})")

            if rtts:
                print(f"  RTT: {statistics.mean(rtts):.2f} ms "
                      f"(±{statistics.stdev(rtts) if len(rtts) > 1 else 0:.2f})")

            if retrans_rates:
                print(f"  Retransmission Rate: {statistics.mean(retrans_rates):.3f}% "
                      f"(±{statistics.stdev(retrans_rates) if len(retrans_rates) > 1 else 0:.3f})")

            if handshake_times:
                print(f"  Handshake Time: {statistics.mean(handshake_times):.2f} ms "
                      f"(±{statistics.stdev(handshake_times) if len(handshake_times) > 1 else 0:.2f})")

            if server_response_latencies:
                print(f"  Server Response Latency: {statistics.mean(server_response_latencies):.2f} ms "
                      f"(±{statistics.stdev(server_response_latencies) if len(server_response_latencies) > 1 else 0:.2f})")

            if inter_packet_delays:
                print(f"  Inter-Packet Delay: {statistics.mean(inter_packet_delays):.3f} ms "
                      f"(±{statistics.stdev(inter_packet_delays) if len(inter_packet_delays) > 1 else 0:.3f})")

            if burst_counts:
                print(f"  Burst Count: {statistics.mean(burst_counts):.0f} bursts "
                      f"(±{statistics.stdev(burst_counts) if len(burst_counts) > 1 else 0:.0f})")
                if burst_gaps:
                    print(f"  Burst Gap: {statistics.mean(burst_gaps):.2f} ms "
                          f"(±{statistics.stdev(burst_gaps) if len(burst_gaps) > 1 else 0:.2f})")

            if pacing_covs:
                print(f"  Pacing CoV: {statistics.mean(pacing_covs):.1f}% "
                      f"(±{statistics.stdev(pacing_covs) if len(pacing_covs) > 1 else 0:.1f})")
                if pacing_clusters:
                    print(f"  Pacing Clustering: {statistics.mean(pacing_clusters):.1f}% "
                          f"(±{statistics.stdev(pacing_clusters) if len(pacing_clusters) > 1 else 0:.1f})")

        # Generate diagnosis
        self.generate_diagnosis()

        # Save detailed results
        self.save_results()

    def generate_diagnosis(self):
        """Generate diagnosis of performance issues"""
        print(f"\n\n{'#'*70}")
        print(f"# COMPREHENSIVE EVIDENCE ANALYSIS")
        print(f"{'#'*70}\n")

        cdn_results = self.results.get('cdn', [])
        legacy_results = self.results.get('legacy', [])

        if not cdn_results:
            print("[!] No CDN results to diagnose")
            return

        if not legacy_results:
            print("[!] No Legacy baseline for comparison")
            return

        # Collect CDN metrics
        cdn_throughputs = []
        cdn_rtts = []
        cdn_retrans_rates = []
        cdn_server_response_latencies = []
        cdn_inter_packet_delays = []
        cdn_burst_counts = []
        cdn_burst_gaps = []
        cdn_pacing_covs = []
        cdn_pacing_clusters = []

        # Collect Legacy metrics for comparison
        legacy_results = self.results.get('legacy', [])
        legacy_throughputs = []
        legacy_rtts = []
        legacy_retrans_rates = []
        legacy_server_response_latencies = []
        legacy_inter_packet_delays = []
        legacy_burst_counts = []
        legacy_burst_gaps = []
        legacy_pacing_covs = []
        legacy_pacing_clusters = []

        for result in cdn_results:
            m = result["metrics"]

            if "basic" in m:
                cdn_throughputs.append(m["basic"]["avg_throughput_mbps"])

            if "rtt" in m and m["rtt"]["samples"] > 0:
                cdn_rtts.append(m["rtt"]["avg_ms"])

            if "retransmissions" in m:
                cdn_retrans_rates.append(m["retransmissions"]["retransmission_rate_pct"])

            if "server_response_latency" in m and m["server_response_latency"].get("samples", 0) > 0:
                cdn_server_response_latencies.append(m["server_response_latency"]["avg_ms"])

            if "inter_packet_delay" in m and m["inter_packet_delay"].get("samples", 0) > 0:
                cdn_inter_packet_delays.append(m["inter_packet_delay"]["avg_ms"])

            if "burst_pattern" in m and m["burst_pattern"].get("total_bursts", 0) > 0:
                cdn_burst_counts.append(m["burst_pattern"]["total_bursts"])
                if m["burst_pattern"].get("avg_gap_ms", 0) > 0:
                    cdn_burst_gaps.append(m["burst_pattern"]["avg_gap_ms"])

            if "pacing_precision" in m and m["pacing_precision"].get("samples", 0) > 0:
                cdn_pacing_covs.append(m["pacing_precision"]["coefficient_of_variation"])
                cdn_pacing_clusters.append(m["pacing_precision"]["top_3_clustering_pct"])

        for result in legacy_results:
            m = result["metrics"]

            if "basic" in m:
                legacy_throughputs.append(m["basic"]["avg_throughput_mbps"])

            if "rtt" in m and m["rtt"]["samples"] > 0:
                legacy_rtts.append(m["rtt"]["avg_ms"])

            if "retransmissions" in m:
                legacy_retrans_rates.append(m["retransmissions"]["retransmission_rate_pct"])

            if "server_response_latency" in m and m["server_response_latency"].get("samples", 0) > 0:
                legacy_server_response_latencies.append(m["server_response_latency"]["avg_ms"])

            if "inter_packet_delay" in m and m["inter_packet_delay"].get("samples", 0) > 0:
                legacy_inter_packet_delays.append(m["inter_packet_delay"]["avg_ms"])

            if "burst_pattern" in m and m["burst_pattern"].get("total_bursts", 0) > 0:
                legacy_burst_counts.append(m["burst_pattern"]["total_bursts"])
                if m["burst_pattern"].get("avg_gap_ms", 0) > 0:
                    legacy_burst_gaps.append(m["burst_pattern"]["avg_gap_ms"])

            if "pacing_precision" in m and m["pacing_precision"].get("samples", 0) > 0:
                legacy_pacing_covs.append(m["pacing_precision"]["coefficient_of_variation"])
                legacy_pacing_clusters.append(m["pacing_precision"]["top_3_clustering_pct"])

        # =================================================================
        # PART 1: COMPLETE METRICS COMPARISON TABLE
        # =================================================================
        print("="*70)
        print("COMPLETE METRICS COMPARISON")
        print("="*70)
        print("\nShowing ALL measured metrics side-by-side:\n")

        # Calculate all aggregate metrics
        cdn_avg_throughput = statistics.mean(cdn_throughputs) if cdn_throughputs else None
        legacy_avg_throughput = statistics.mean(legacy_throughputs) if legacy_throughputs else None

        cdn_avg_rtt = statistics.mean(cdn_rtts) if cdn_rtts else None
        legacy_avg_rtt = statistics.mean(legacy_rtts) if legacy_rtts else None

        cdn_avg_retrans = statistics.mean(cdn_retrans_rates) if cdn_retrans_rates else None
        legacy_avg_retrans = statistics.mean(legacy_retrans_rates) if legacy_retrans_rates else None

        cdn_avg_response = statistics.mean(cdn_server_response_latencies) if cdn_server_response_latencies else None
        legacy_avg_response = statistics.mean(legacy_server_response_latencies) if legacy_server_response_latencies else None

        cdn_avg_delay = statistics.mean(cdn_inter_packet_delays) if cdn_inter_packet_delays else None
        legacy_avg_delay = statistics.mean(legacy_inter_packet_delays) if legacy_inter_packet_delays else None

        cdn_avg_bursts = statistics.mean(cdn_burst_counts) if cdn_burst_counts else None
        legacy_avg_bursts = statistics.mean(legacy_burst_counts) if legacy_burst_counts else None

        cdn_avg_gap = statistics.mean(cdn_burst_gaps) if cdn_burst_gaps else None
        legacy_avg_gap = statistics.mean(legacy_burst_gaps) if legacy_burst_gaps else None

        cdn_avg_cov = statistics.mean(cdn_pacing_covs) if cdn_pacing_covs else None
        legacy_avg_cov = statistics.mean(legacy_pacing_covs) if legacy_pacing_covs else None

        cdn_avg_cluster = statistics.mean(cdn_pacing_clusters) if cdn_pacing_clusters else None
        legacy_avg_cluster = statistics.mean(legacy_pacing_clusters) if legacy_pacing_clusters else None

        # Print comparison table
        def print_metric(name, legacy_val, cdn_val, unit="", ratio_format=""):
            """Print a metric comparison row"""
            if legacy_val is None or cdn_val is None:
                return

            ratio = cdn_val / legacy_val if legacy_val > 0 else 0
            ratio_str = f"{ratio:.1f}x" if ratio_format == "ratio" else f"{ratio:.1%}" if ratio_format == "percent" else ""

            # Determine if this is better/worse/neutral
            indicator = ""
            if name in ["Throughput", "Server Response (lower better)"]:
                if ratio < 0.9:
                    indicator = " ⚠️"
                elif ratio < 0.5:
                    indicator = " 🔴"
            elif name in ["RTT", "Retransmissions", "Inter-Packet Delay", "Burst Count"]:
                if ratio > 1.5:
                    indicator = " ⚠️"
                if ratio > 3:
                    indicator = " 🔴"

            print(f"  {name:30} Legacy: {legacy_val:>10.2f}{unit:>6}   CDN: {cdn_val:>10.2f}{unit:>6}   {ratio_str:>8}{indicator}")

        print("Network Quality Metrics:")
        print_metric("Throughput", legacy_avg_throughput, cdn_avg_throughput, "Mbps", "ratio")
        print_metric("RTT", legacy_avg_rtt, cdn_avg_rtt, "ms", "ratio")
        print_metric("Retransmissions", legacy_avg_retrans, cdn_avg_retrans, "%", "ratio")

        print("\nServer Behavior Metrics:")
        print_metric("Server Response Latency", legacy_avg_response, cdn_avg_response, "ms", "ratio")
        print_metric("Inter-Packet Delay", legacy_avg_delay, cdn_avg_delay, "ms", "ratio")
        print_metric("Burst Count", legacy_avg_bursts, cdn_avg_bursts, "bursts", "ratio")
        print_metric("Burst Gap", legacy_avg_gap, cdn_avg_gap, "ms", "ratio")

        print("\nPacing Analysis Metrics:")
        print_metric("Pacing CoV (variation)", legacy_avg_cov, cdn_avg_cov, "%", "ratio")
        print_metric("Pacing Clustering", legacy_avg_cluster, cdn_avg_cluster, "%", "ratio")

        print("\n" + "="*70)
        print("EVIDENCE INTERPRETATION")
        print("="*70)
        print()

        # =================================================================
        # PART 2: EVIDENCE THAT SUPPORTS THROTTLING
        # =================================================================
        print("Evidence SUPPORTING Rate Limiting Hypothesis:")
        print("-" * 70)

        supporting_evidence = []

        if cdn_avg_throughput and legacy_avg_throughput and cdn_avg_throughput < legacy_avg_throughput * 0.5:
            throughput_ratio = (cdn_avg_throughput / legacy_avg_throughput) * 100
            supporting_evidence.append(
                f"✓ Throughput reduced to {throughput_ratio:.0f}% of Legacy ({cdn_avg_throughput:.1f} vs {legacy_avg_throughput:.1f} Mbps)"
            )

        if cdn_avg_bursts and legacy_avg_bursts and cdn_avg_bursts > 100:
            burst_ratio = cdn_avg_bursts / legacy_avg_bursts
            supporting_evidence.append(
                f"✓ Extreme burst count: {cdn_avg_bursts:.0f} bursts vs {legacy_avg_bursts:.0f} ({burst_ratio:.0f}x more)"
            )
            if cdn_avg_bursts > 500:
                supporting_evidence.append(
                    f"  → {cdn_avg_bursts:.0f} distinct bursts cannot occur naturally in TCP"
                )

        if cdn_avg_gap and cdn_avg_gap < 50:
            supporting_evidence.append(
                f"✓ Consistent gap timing: {cdn_avg_gap:.1f}ms between bursts"
            )
            supporting_evidence.append(
                f"  → Suggests token bucket refill interval of ~{cdn_avg_gap:.0f}ms"
            )

        if cdn_avg_delay and legacy_avg_delay and cdn_avg_delay > legacy_avg_delay * 3:
            delay_ratio = cdn_avg_delay / legacy_avg_delay
            supporting_evidence.append(
                f"✓ Inter-packet delays are {delay_ratio:.1f}x slower ({cdn_avg_delay:.3f}ms vs {legacy_avg_delay:.3f}ms)"
            )

        if cdn_avg_rtt and legacy_avg_rtt and cdn_avg_rtt < 10 and legacy_avg_rtt < 10:
            supporting_evidence.append(
                f"✓ Network RTT is excellent for both ({cdn_avg_rtt:.2f}ms CDN, {legacy_avg_rtt:.2f}ms Legacy)"
            )
            supporting_evidence.append(
                f"  → Rules out network latency as the bottleneck"
            )

        if supporting_evidence:
            for evidence in supporting_evidence:
                print(evidence)
        else:
            print("  (None identified)")

        print()

        # =================================================================
        # PART 3: EVIDENCE THAT ARGUES AGAINST THROTTLING
        # =================================================================
        print("Evidence AGAINST or NOT FITTING Rate Limiting Hypothesis:")
        print("-" * 70)

        against_evidence = []

        if cdn_avg_response and legacy_avg_response and cdn_avg_response < legacy_avg_response:
            against_evidence.append(
                f"✗ CDN responds FASTER initially ({cdn_avg_response:.2f}ms vs {legacy_avg_response:.2f}ms)"
            )
            against_evidence.append(
                f"  → Suggests CDN server is not resource-constrained"
            )

        if cdn_avg_cov and cdn_avg_cov > 100:
            against_evidence.append(
                f"✗ High pacing variation (CoV: {cdn_avg_cov:.1f}%)"
            )
            against_evidence.append(
                f"  → Algorithmic rate limiters typically have low CoV (<20%)"
            )
            against_evidence.append(
                f"  → This suggests imprecise pacing or additional variability sources"
            )

        if cdn_avg_cov and legacy_avg_cov and cdn_avg_cov > legacy_avg_cov:
            cov_ratio = cdn_avg_cov / legacy_avg_cov
            against_evidence.append(
                f"✗ CDN has MORE timing variation than Legacy ({cdn_avg_cov:.1f}% vs {legacy_avg_cov:.1f}%, {cov_ratio:.1f}x)"
            )
            against_evidence.append(
                f"  → Opposite of what precise algorithmic throttling would show"
            )

        if cdn_avg_cluster and legacy_avg_cluster and cdn_avg_cluster < legacy_avg_cluster:
            against_evidence.append(
                f"✗ CDN has LESS clustering than Legacy ({cdn_avg_cluster:.1f}% vs {legacy_avg_cluster:.1f}%)"
            )
            against_evidence.append(
                f"  → Algorithmic pacing should show high clustering (>80%)"
            )

        if cdn_avg_retrans and cdn_avg_retrans < 1.0:
            against_evidence.append(
                f"✗ Network is very clean (retransmissions: {cdn_avg_retrans:.3f}%)"
            )
            against_evidence.append(
                f"  → No evidence of packet loss or network congestion"
            )

        if against_evidence:
            for evidence in against_evidence:
                print(evidence)
        else:
            print("  (None identified)")

        print()

        # =================================================================
        # PART 4: NEUTRAL / AMBIGUOUS EVIDENCE
        # =================================================================
        print("Neutral or Ambiguous Evidence:")
        print("-" * 70)

        neutral_evidence = []

        if cdn_avg_rtt and legacy_avg_rtt and cdn_avg_rtt > legacy_avg_rtt * 2:
            rtt_ratio = cdn_avg_rtt / legacy_avg_rtt
            if cdn_avg_rtt < 10:
                neutral_evidence.append(
                    f"• CDN RTT is {rtt_ratio:.1f}x higher, but absolute value too low to matter ({cdn_avg_rtt:.2f}ms)"
                )

        if cdn_avg_gap and cdn_burst_gaps:
            cdn_gap_stddev = statistics.stdev(cdn_burst_gaps) if len(cdn_burst_gaps) > 1 else 0
            gap_cov = (cdn_gap_stddev / cdn_avg_gap * 100) if cdn_avg_gap > 0 else 0
            if 30 <= gap_cov <= 50:
                neutral_evidence.append(
                    f"• Burst gaps have moderate variability (CoV: {gap_cov:.0f}%)"
                )
                neutral_evidence.append(
                    f"  → Could be consistent pacing + network jitter, or less precise algorithm"
                )

        if neutral_evidence:
            for evidence in neutral_evidence:
                print(evidence)
        else:
            print("  (None identified)")

        print()
        print("="*70)
        print("OVERALL ASSESSMENT")
        print("="*70)
        print()

        # Now continue with the confidence assessment and diagnosis
        issues_found = []

        # Track evidence indicators for confidence scoring
        evidence_indicators = []

        # Calculate RTT ratio if both available (for ruling out network latency)
        rtt_ratio = None
        if cdn_rtts and legacy_rtts:
            cdn_avg_rtt = statistics.mean(cdn_rtts)
            legacy_avg_rtt = statistics.mean(legacy_rtts)
            rtt_ratio = cdn_avg_rtt / legacy_avg_rtt if legacy_avg_rtt > 0 else 1

        # ROOT CAUSE ANALYSIS: Check CDN server behavior
        # We look for multiple independent indicators to avoid bias

        # 1. Check Burst Pattern (PRIMARY THROTTLING INDICATOR)
        # Threshold: >100 bursts over typical 30-60s download means ~2-3 bursts/second,
        # which is characteristic of token bucket with ~20ms refill interval (50 Hz pacing)
        burst_pattern_detected = False
        if cdn_burst_counts and legacy_burst_counts:
            cdn_avg_bursts = statistics.mean(cdn_burst_counts)
            legacy_avg_bursts = statistics.mean(legacy_burst_counts)
            burst_ratio = cdn_avg_bursts / legacy_avg_bursts if legacy_avg_bursts > 0 else 0

            # Require both high absolute count AND significant ratio difference
            if cdn_avg_bursts > 100 and burst_ratio > 3:
                burst_pattern_detected = True
                evidence_indicators.append("burst_pattern")

                # Very high burst counts are extremely strong evidence even without other indicators
                if cdn_avg_bursts > 500 and burst_ratio > 50:
                    evidence_indicators.append("extreme_burst_count")

                # Check if gaps are consistent (additional evidence for algorithmic behavior)
                gap_consistency_note = ""
                gap_cov = None
                if cdn_burst_gaps:
                    cdn_avg_gap = statistics.mean(cdn_burst_gaps)
                    cdn_gap_stddev = statistics.stdev(cdn_burst_gaps) if len(cdn_burst_gaps) > 1 else 0
                    gap_cov = (cdn_gap_stddev / cdn_avg_gap * 100) if cdn_avg_gap > 0 else 0
                    if gap_cov < 30:
                        gap_consistency_note = f" with consistent {cdn_avg_gap:.1f}ms gaps (CoV: {gap_cov:.0f}%)"
                    else:
                        gap_consistency_note = f" with {cdn_avg_gap:.1f}ms gaps (variable, CoV: {gap_cov:.0f}%)"

                # Build explanation based on gap consistency
                explanation_list = [
                    "CDN server sends data in many small bursts with gaps between them",
                    "Legacy server sends continuously without significant burst behavior",
                ]

                if gap_cov is not None and gap_cov > 50:
                    explanation_list.append(
                        f"Gap timing is variable (CoV: {gap_cov:.0f}%) - suggests rate limiting "
                        "combined with other factors (buffering, network jitter, etc.)"
                    )
                elif gap_cov is not None and gap_cov < 30:
                    explanation_list.append(
                        f"Gap timing is very consistent (CoV: {gap_cov:.0f}%) - characteristic of "
                        "precise algorithmic rate limiting"
                    )

                explanation_list.extend([
                    f"Burst count ({cdn_avg_bursts:.0f}) is extreme and cannot occur naturally",
                    "Natural TCP dynamics do not produce this many distinct bursts"
                ])

                issues_found.append({
                    "issue": "🔴 LIKELY CAUSE: Server Burst Pacing/Rate Limiting",
                    "severity": "CRITICAL",
                    "details": f"CDN bursts: {cdn_avg_bursts:.0f} vs Legacy: {legacy_avg_bursts:.0f} ({burst_ratio:.1f}x more){gap_consistency_note}",
                    "explanation": explanation_list,
                    "likely_causes": [
                        "Token bucket or leaky bucket rate limiting algorithm",
                        "CDN configured with per-connection bandwidth limits",
                        "Application-level pacing to manage server load"
                    ],
                    "alternative_explanations": [
                        "Severe CPU constraints causing periodic stalls (less likely given burst count)",
                        "Buffering strategy for streaming optimization (possible but uncommon)"
                    ]
                })

        # 2. Check Pacing Precision (ALGORITHMIC THROTTLING INDICATOR)
        # Low CoV (<20%) + high clustering (>60%) is very hard to achieve naturally
        algorithmic_pacing_detected = False
        if cdn_pacing_covs and cdn_pacing_clusters:
            cdn_avg_cov = statistics.mean(cdn_pacing_covs)
            cdn_avg_cluster = statistics.mean(cdn_pacing_clusters)

            # Compare to legacy if available
            legacy_cov_comparison = ""
            if legacy_pacing_covs:
                legacy_avg_cov = statistics.mean(legacy_pacing_covs)
                cov_ratio = legacy_avg_cov / cdn_avg_cov if cdn_avg_cov > 0 else 1
                if cov_ratio > 3:
                    legacy_cov_comparison = f" (Legacy CoV: {legacy_avg_cov:.1f}%, {cov_ratio:.1f}x more variable)"

            if cdn_avg_cov < 20 and cdn_avg_cluster > 60:
                algorithmic_pacing_detected = True
                evidence_indicators.append("algorithmic_pacing")

                issues_found.append({
                    "issue": "🔴 STRONG EVIDENCE: Algorithmic Pacing Detected",
                    "severity": "CRITICAL",
                    "details": f"CoV: {cdn_avg_cov:.1f}%, Clustering: {cdn_avg_cluster:.1f}%{legacy_cov_comparison}",
                    "explanation": [
                        "Inter-packet delays are too precise and clustered to be natural",
                        "Natural TCP has high variation due to network jitter, scheduling, etc.",
                        f"{cdn_avg_cluster:.0f}% of delays fall into just 3 time buckets",
                        "This precision is characteristic of software timers/rate limiters"
                    ],
                    "likely_causes": [
                        "Software-based pacing algorithm (rate limiter)",
                        "Token bucket implementation with precise timing"
                    ],
                    "alternative_explanations": [
                        "Hardware pacing (NIC-level) - possible but uncommon",
                        "Very consistent network path - unlikely given typical internet variability"
                    ]
                })

        # 3. Check Inter-Packet Delays (PRIMARY ROOT CAUSE INDICATOR)
        # Only flag if delays are high AND not explained by network latency
        slow_delivery_detected = False
        if cdn_inter_packet_delays and legacy_inter_packet_delays:
            cdn_avg_delay = statistics.mean(cdn_inter_packet_delays)
            legacy_avg_delay = statistics.mean(legacy_inter_packet_delays)
            delay_ratio = cdn_avg_delay / legacy_avg_delay if legacy_avg_delay > 0 else 0

            # Threshold: 3x slower is significant
            # But check if this is explained by network RTT differences
            if delay_ratio > 3:
                network_explains_delay = False
                rtt_note = ""

                if rtt_ratio is not None:
                    # Only consider RTT as an explanation if BOTH ratio is high AND absolute values are significant
                    # Sub-10ms RTTs should not bottleneck throughput regardless of ratio
                    if rtt_ratio > 2 and cdn_avg_rtt > 10:
                        # Network path has significantly higher latency that matters
                        network_explains_delay = True
                        rtt_note = f" (Note: CDN RTT is {rtt_ratio:.1f}x higher at {cdn_avg_rtt:.1f}ms, which contributes to slower delivery)"
                    elif cdn_avg_rtt < 10 and legacy_avg_rtt < 10:
                        # Both RTTs are too small to matter
                        rtt_note = f" (RTT: {cdn_avg_rtt:.2f}ms vs {legacy_avg_rtt:.2f}ms - both very low, NOT a bottleneck)"
                        evidence_indicators.append("slow_delivery_not_network")
                    else:
                        # RTT is similar, so delays are NOT due to network latency
                        rtt_note = f" (RTT similar: {cdn_avg_rtt:.1f}ms vs {legacy_avg_rtt:.1f}ms, so NOT network latency)"
                        evidence_indicators.append("slow_delivery_not_network")

                slow_delivery_detected = True

                severity = "CRITICAL" if not network_explains_delay else "HIGH"
                issue_prefix = "🔴 LIKELY CAUSE:" if not network_explains_delay else "⚠️  OBSERVED:"

                issues_found.append({
                    "issue": f"{issue_prefix} CDN Server Slow at Sustained Data Delivery",
                    "severity": severity,
                    "details": f"CDN inter-packet delay: {cdn_avg_delay:.3f}ms vs Legacy: {legacy_avg_delay:.3f}ms ({delay_ratio:.1f}x slower){rtt_note}",
                    "explanation": [
                        "Server is slow to send consecutive data packets",
                        "This measures actual sending behavior, not network transit time",
                        "Small TCP windows are a SYMPTOM of slow delivery, not the cause"
                    ] + (["NOT explained by network latency (RTT is similar)"] if not network_explains_delay else ["Partially explained by higher network latency to CDN endpoint"]),
                    "likely_causes": [
                        "Server-side rate limiting or throttling configuration",
                        "Application-level bandwidth management",
                        "Server resource constraints (CPU, disk I/O)" if network_explains_delay else "Rate limiting algorithm (not resource constraint)"
                    ] + (["CDN deliberately limiting per-connection bandwidth"] if not network_explains_delay else []),
                    "alternative_explanations": [] if not network_explains_delay else [
                        "Geographic distance to CDN causing inherent delays",
                        "CDN routing through congested or distant path"
                    ]
                })

        # 4. Check Server Response Latency (INITIAL RESPONSE)
        if cdn_server_response_latencies and legacy_server_response_latencies:
            cdn_avg_response = statistics.mean(cdn_server_response_latencies)
            legacy_avg_response = statistics.mean(legacy_server_response_latencies)
            response_ratio = cdn_avg_response / legacy_avg_response if legacy_avg_response > 0 else 0

            # Only flag if significantly slower (>10ms absolute AND >2x ratio)
            if cdn_avg_response > 10 and response_ratio > 2:
                issues_found.append({
                    "issue": "⚠️  CDN Server Slower to Initially Respond",
                    "severity": "MEDIUM",
                    "details": f"CDN response time: {cdn_avg_response:.2f}ms vs Legacy: {legacy_avg_response:.2f}ms ({response_ratio:.1f}x)",
                    "explanation": [
                        "CDN takes longer to respond to initial requests",
                        "Different from sustained delivery (measured separately above)",
                        "May indicate processing overhead or distance"
                    ],
                    "likely_causes": [
                        "Geographic distance to CDN endpoint",
                        "CDN load balancing/routing overhead",
                        "CDN server under load"
                    ]
                })

        # 5. Check for packet loss (network quality indicator)
        if cdn_retrans_rates:
            avg_retrans = statistics.mean(cdn_retrans_rates)
            if avg_retrans > 1.0:
                issues_found.append({
                    "issue": "⚠️  Elevated Packet Loss",
                    "severity": "MEDIUM",
                    "details": f"Retransmission rate: {avg_retrans:.3f}% (healthy is <1%)",
                    "explanation": [
                        "Packets are being lost and retransmitted",
                        "This is a NETWORK PATH issue, not server behavior",
                        "Can exacerbate other performance issues"
                    ],
                    "likely_causes": [
                        "Network path congestion",
                        "Firewall/middlebox dropping packets",
                        "Physical network issues (WiFi, bad cables)"
                    ]
                })

        # 6. Throughput check (outcome/symptom, not root cause)
        if cdn_throughputs:
            avg_throughput = statistics.mean(cdn_throughputs)
            if avg_throughput < 100:
                issues_found.append({
                    "issue": "📊 Low CDN Throughput (SYMPTOM)",
                    "severity": "HIGH",
                    "details": f"Average throughput: {avg_throughput:.2f} Mbps (expected >100 Mbps)",
                    "explanation": [
                        "This is the OUTCOME/SYMPTOM, not the root cause",
                        "Root causes are identified in the issues above",
                        "Fixing the underlying causes will improve throughput"
                    ]
                })

        # Print confidence summary first
        if evidence_indicators:
            print("="*70)
            print("CONFIDENCE ASSESSMENT")
            print("="*70)
            print(f"\nEvidence indicators detected: {len(evidence_indicators)}")
            for indicator in evidence_indicators:
                indicator_name = {
                    "burst_pattern": "✓ Burst pacing pattern (>100 bursts)",
                    "extreme_burst_count": "✓ EXTREME burst count (>500 bursts, >50x baseline)",
                    "algorithmic_pacing": "✓ Algorithmic precision (low CoV, high clustering)",
                    "slow_delivery_not_network": "✓ Slow delivery NOT explained by network RTT"
                }.get(indicator, f"✓ {indicator}")
                print(f"  {indicator_name}")

            # Determine overall confidence
            # Give special weight to extreme burst count - it's very hard to explain naturally
            has_extreme_bursts = "extreme_burst_count" in evidence_indicators

            if len(evidence_indicators) >= 3:
                confidence = "VERY HIGH"
                confidence_note = "Multiple independent indicators confirm rate limiting"
            elif len(evidence_indicators) == 2:
                if has_extreme_bursts:
                    confidence = "VERY HIGH"
                    confidence_note = "Extreme burst count plus additional evidence strongly suggests rate limiting"
                else:
                    confidence = "HIGH"
                    confidence_note = "Two independent indicators suggest rate limiting"
            elif len(evidence_indicators) == 1:
                if has_extreme_bursts:
                    confidence = "HIGH"
                    confidence_note = "Extreme burst count alone is strong evidence (>500 bursts cannot occur naturally)"
                else:
                    confidence = "MODERATE"
                    confidence_note = "Single indicator present, but not conclusive alone"
            else:
                confidence = "LOW"
                confidence_note = "No strong indicators of algorithmic throttling"

            print(f"\nOverall Confidence: {confidence}")
            print(f"  {confidence_note}")
            print()

        # Print findings
        if issues_found:
            print("="*70)
            print("DETAILED FINDINGS")
            print("="*70)
            print()

            for i, issue in enumerate(issues_found, 1):
                print(f"[Issue #{i}] {issue['issue']}")
                print(f"  Severity: {issue['severity']}")
                print(f"  Details: {issue['details']}")

                if 'explanation' in issue:
                    print(f"  Explanation:")
                    for exp in issue['explanation']:
                        print(f"    • {exp}")

                # Handle new field names (likely_causes instead of causes)
                if 'likely_causes' in issue:
                    print(f"  Likely Causes:")
                    for cause in issue['likely_causes']:
                        print(f"    • {cause}")
                elif 'causes' in issue:
                    print(f"  Possible Causes:")
                    for cause in issue['causes']:
                        print(f"    • {cause}")

                if 'alternative_explanations' in issue and issue['alternative_explanations']:
                    print(f"  Alternative Explanations:")
                    for alt in issue['alternative_explanations']:
                        print(f"    • {alt}")

                print()  # Blank line between issues
        else:
            print("[+] No significant performance issues detected!")
            print("    CDN performance appears to be within expected parameters.")

    def save_results(self):
        """Save detailed results to JSON file"""
        output_file = f"pcap_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        output_data = {
            "analysis_time": datetime.now().isoformat(),
            "pcap_directory": self.pcap_dir,
            "results": self.results
        }

        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)

        print(f"\n[+] Detailed results saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Tanium download packet captures for performance issues"
    )

    # Mutually exclusive: either analyze a directory or a single file
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--pcap-dir",
        help="Directory containing PCAP files from performance test"
    )
    group.add_argument(
        "--pcap-file",
        help="Single PCAP file to analyze"
    )

    parser.add_argument(
        "--server-port",
        type=int,
        help="Server port number (17472 for legacy, 443 for CDN). Auto-detected if not specified."
    )

    parser.add_argument(
        "--output",
        help="Output file for JSON results (default: auto-generated)"
    )

    parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="Disable parallel processing (use sequential mode)"
    )

    args = parser.parse_args()

    try:
        if args.pcap_dir:
            # Analyze directory
            analyzer = MultiPCAPAnalyzer(args.pcap_dir, parallel=not args.no_parallel)
            analyzer.analyze_all()
        else:
            # Analyze single file
            analyzer = PCAPAnalyzer(args.pcap_file, args.server_port)
            metrics = analyzer.run_full_analysis()
            analyzer.print_summary()

            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(metrics, f, indent=2)
                print(f"\n[+] Results saved to: {args.output}")

    except KeyboardInterrupt:
        print("\n[!] Analysis interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
