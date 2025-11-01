#!/usr/bin/env python3
"""
Scan IP ranges from JSON file to find which IPs have port 443 open

Usage:
    python3 scan_port_443.py <json_file> [options]

Options:
    --timeout SECONDS           Connection timeout (default: 2)
    --threads NUM               Number of concurrent threads (default: 50)
    --output FILE               Save results to file (default: port_443_results.json)
    --geo-filter                Filter to US IPs only, prioritize by distance from Chicago
    --geo-db PATH               Path to GeoLite2 City database (.mmdb file)
    --max-distance MILES        Max distance from Chicago in miles (default: no limit)
    --latency-sample N          Sample N IPs per region for latency testing (default: 0)
    --progressive-scan          Expand distance incrementally until first hit found
    --distance-increment MILES  Miles to expand per iteration (default: 100)
    --max-progressive-distance  Max distance for progressive scan (default: 3000)
    --use-tls                   Perform TLS handshake (more realistic for CDN testing)

Examples:
    # Standard scan with geo-filtering
    python3 scan_port_443.py ip_ranges.json --geo-filter --max-distance 500 --threads 100

    # Progressive scan with TLS handshake (recommended for CDN testing)
    python3 scan_port_443.py ip_ranges.json --geo-filter --max-distance 200 \\
        --progressive-scan --threads 10 --timeout 5 --use-tls --geo-db GeoLite2-City.mmdb
"""

import json
import sys
import socket
import ssl
import ipaddress
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
import math
import os
import urllib.request
import tarfile
import tempfile
from pathlib import Path

# Chicago coordinates
CHICAGO_LAT = 41.8781
CHICAGO_LON = -87.6298

# Try to import geoip2 (optional dependency)
try:
    import geoip2.database
    import geoip2.errors
    GEOIP2_AVAILABLE = True
except ImportError:
    GEOIP2_AVAILABLE = False


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points on earth (in miles)
    """
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))

    # Radius of earth in miles
    r = 3956

    return c * r


def download_geolite2_db():
    """
    Note: MaxMind now requires registration for GeoLite2 downloads.
    This function provides instructions instead of auto-downloading.
    """
    print("\n" + "="*70)
    print("GEOLITE2 DATABASE REQUIRED")
    print("="*70)
    print("\nTo use geo-filtering, you need the GeoLite2 database:")
    print("\n1. Create free account at: https://www.maxmind.com/en/geolite2/signup")
    print("2. Download 'GeoLite2 City' database (MMDB format)")
    print("3. Extract and provide path with --geo-db option")
    print("\nAlternatively, use --geo-db to specify path to existing database")
    print("="*70 + "\n")
    return None


def get_ip_location(reader, ip_str):
    """
    Get geographic location for an IP address

    Returns:
        dict: {'country': str, 'region': str, 'city': str, 'lat': float, 'lon': float, 'distance': float}
        or None if not found
    """
    try:
        response = reader.city(ip_str)

        if response.location.latitude is None or response.location.longitude is None:
            return None

        distance = haversine_distance(
            CHICAGO_LAT, CHICAGO_LON,
            response.location.latitude, response.location.longitude
        )

        return {
            'country': response.country.iso_code,
            'region': response.subdivisions.most_specific.name if response.subdivisions else None,
            'city': response.city.name,
            'lat': response.location.latitude,
            'lon': response.location.longitude,
            'distance_miles': round(distance, 1)
        }
    except (geoip2.errors.AddressNotFoundError, AttributeError):
        return None


def test_latency(ip, timeout=2):
    """
    Test connection latency to an IP on port 443

    Returns:
        float: latency in milliseconds, or None if failed
    """
    ip_str = str(ip)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        start = time.time()
        result = sock.connect_ex((ip_str, 443))
        latency = (time.time() - start) * 1000  # Convert to ms
        sock.close()

        if result == 0:
            return latency
        return None
    except:
        return None
    finally:
        try:
            sock.close()
        except:
            pass


def test_port_443(ip, timeout=2, use_tls=False):
    """
    Test if port 443 is open on the given IP

    Args:
        ip: IP address to test
        timeout: Connection timeout in seconds
        use_tls: If True, perform TLS handshake (more realistic for CDN testing)

    Returns:
        dict: {'ip': str, 'open': bool, 'error': str or None}
    """
    ip_str = str(ip)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        # First establish TCP connection
        result = sock.connect_ex((ip_str, 443))

        if result != 0:
            sock.close()
            return {'ip': ip_str, 'open': False, 'error': f'Connection refused (code {result})'}

        # If TLS mode, attempt TLS handshake
        if use_tls:
            context = ssl.create_default_context()
            # Don't verify hostname/cert for scanning purposes
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            try:
                ssl_sock = context.wrap_socket(sock, server_hostname=ip_str)
                ssl_sock.close()
                return {'ip': ip_str, 'open': True, 'error': None}
            except ssl.SSLError as e:
                # TLS handshake failed, but TCP connected
                return {'ip': ip_str, 'open': False, 'error': f'TLS handshake failed: {e}'}
        else:
            # Just TCP connection test
            sock.close()
            return {'ip': ip_str, 'open': True, 'error': None}

    except socket.timeout:
        return {'ip': ip_str, 'open': False, 'error': 'Timeout'}
    except socket.gaierror as e:
        return {'ip': ip_str, 'open': False, 'error': f'DNS error: {e}'}
    except Exception as e:
        return {'ip': ip_str, 'open': False, 'error': str(e)}
    finally:
        try:
            sock.close()
        except:
            pass


def expand_cidr_ranges(cidr_list):
    """
    Expand CIDR ranges into individual IP addresses

    Args:
        cidr_list: List of CIDR strings (e.g., ["192.168.1.0/24", "10.0.0.0/16"])

    Returns:
        list: List of IPv4Address objects
    """
    all_ips = []
    ipv6_count = 0

    for cidr in cidr_list:
        try:
            # Skip IPv6 addresses
            if ':' in cidr:
                ipv6_count += 1
                continue

            # Handle individual IPs (no CIDR notation)
            if '/' not in cidr:
                # Just a single IP
                ip = ipaddress.ip_address(cidr)
                if isinstance(ip, ipaddress.IPv4Address):
                    all_ips.append(ip)
                continue

            # Handle CIDR ranges
            network = ipaddress.ip_network(cidr, strict=False)

            # Only process IPv4
            if isinstance(network, ipaddress.IPv4Network):
                # Convert to list - this can be memory intensive for large ranges
                all_ips.extend(list(network.hosts()))
        except ValueError as e:
            # Skip silently - likely IPv6 or invalid format
            continue

    if ipv6_count > 0:
        print(f"[+] Skipped {ipv6_count} IPv6 addresses (IPv4 only scan)")

    return all_ips


def filter_and_prioritize_ips(ip_list, geo_db_path, max_distance=None, latency_sample=0):
    """
    Filter IPs to US-only and prioritize by distance from Chicago

    Args:
        ip_list: List of IPv4Address objects
        geo_db_path: Path to GeoLite2 City database
        max_distance: Maximum distance from Chicago in miles (None for no limit)
        latency_sample: Number of IPs per region to sample for latency (0 to skip)

    Returns:
        list: Filtered and prioritized list of IPs with metadata
    """
    if not GEOIP2_AVAILABLE:
        print("\n[!] ERROR: geoip2 library not installed")
        print("[!] Install with: pip install geoip2")
        sys.exit(1)

    if not geo_db_path or not os.path.exists(geo_db_path):
        print(f"\n[!] ERROR: GeoLite2 database not found at: {geo_db_path}")
        download_geolite2_db()
        sys.exit(1)

    print(f"\n[+] Loading GeoLite2 database from: {geo_db_path}")

    try:
        reader = geoip2.database.Reader(geo_db_path)
    except Exception as e:
        print(f"[!] ERROR loading database: {e}")
        sys.exit(1)

    print(f"[+] Filtering {len(ip_list)} IPs for US-only, calculating distances from Chicago...")

    filtered_ips = []
    us_count = 0
    non_us_count = 0
    no_geo_count = 0

    for i, ip in enumerate(ip_list):
        if (i + 1) % 1000 == 0:
            print(f"    Processing {i+1}/{len(ip_list)} IPs...")

        location = get_ip_location(reader, str(ip))

        if location is None:
            no_geo_count += 1
            continue

        if location['country'] != 'US':
            non_us_count += 1
            continue

        # Check distance filter
        if max_distance and location['distance_miles'] > max_distance:
            continue

        us_count += 1
        filtered_ips.append({
            'ip': ip,
            'location': location
        })

    reader.close()

    print(f"\n[+] Geo-filtering results:")
    print(f"    • US IPs: {us_count}")
    print(f"    • Non-US IPs (filtered out): {non_us_count}")
    print(f"    • No geo data: {no_geo_count}")

    if max_distance:
        print(f"    • Within {max_distance} miles of Chicago: {len(filtered_ips)}")

    # Sort by distance from Chicago
    filtered_ips.sort(key=lambda x: x['location']['distance_miles'])

    # Show distribution by region
    regions = {}
    for ip_data in filtered_ips[:100]:  # Show top 100 regions
        region = ip_data['location']['region'] or 'Unknown'
        if region not in regions:
            regions[region] = {
                'count': 0,
                'distance': ip_data['location']['distance_miles']
            }
        regions[region]['count'] += 1

    print(f"\n[+] Top regions by proximity to Chicago:")
    for region, data in sorted(regions.items(), key=lambda x: x[1]['distance'])[:10]:
        print(f"    • {region}: {data['count']} IPs (~{data['distance']:.0f} miles)")

    # Latency sampling if requested
    if latency_sample > 0 and filtered_ips:
        print(f"\n[+] Sampling {latency_sample} IPs per region for latency testing...")

        # Group by region
        by_region = {}
        for ip_data in filtered_ips:
            region = ip_data['location']['region'] or 'Unknown'
            if region not in by_region:
                by_region[region] = []
            by_region[region].append(ip_data)

        # Sample and test latency
        latency_results = []
        for region, ips in by_region.items():
            sample_ips = ips[:latency_sample]
            print(f"    Testing {len(sample_ips)} IPs in {region}...")

            for ip_data in sample_ips:
                latency = test_latency(ip_data['ip'])
                if latency:
                    latency_results.append({
                        'region': region,
                        'latency': latency,
                        'distance': ip_data['location']['distance_miles']
                    })

        if latency_results:
            latency_results.sort(key=lambda x: x['latency'])
            print(f"\n[+] Lowest latency regions:")
            shown = set()
            for result in latency_results[:10]:
                if result['region'] not in shown:
                    print(f"    • {result['region']}: {result['latency']:.1f}ms "
                          f"(~{result['distance']:.0f} miles)")
                    shown.add(result['region'])

            # Re-sort filtered IPs by latency-weighted distance
            # Prioritize regions with good latency
            avg_latency = {}
            for result in latency_results:
                region = result['region']
                if region not in avg_latency:
                    avg_latency[region] = []
                avg_latency[region].append(result['latency'])

            region_latency = {
                region: sum(latencies) / len(latencies)
                for region, latencies in avg_latency.items()
            }

            # Re-sort: prefer low-latency regions
            def sort_key(ip_data):
                region = ip_data['location']['region'] or 'Unknown'
                base_latency = region_latency.get(region, 999999)
                return (base_latency, ip_data['location']['distance_miles'])

            filtered_ips.sort(key=sort_key)
            print(f"\n[+] Re-prioritized {len(filtered_ips)} IPs by latency + distance")

    return [ip_data['ip'] for ip_data in filtered_ips]


def scan_ips(ip_list, timeout=2, max_threads=50, stop_on_first=False, use_tls=False):
    """
    Scan list of IPs for port 443

    Args:
        ip_list: List of IP addresses to scan
        timeout: Connection timeout in seconds
        max_threads: Maximum concurrent threads
        stop_on_first: Stop scanning after first successful hit
        use_tls: Perform TLS handshake instead of just TCP connect

    Returns:
        dict: {'open': [list of open IPs], 'closed': [list of closed IPs]}
    """
    print(f"\n[+] Scanning {len(ip_list)} IPs with {max_threads} threads...")
    print(f"[+] Timeout: {timeout}s per connection")
    print(f"[+] Test mode: {'TLS handshake' if use_tls else 'TCP connect'}")
    if stop_on_first:
        print(f"[+] Will stop after first successful hit\n")
    else:
        print()

    results = {'open': [], 'closed': []}
    completed = 0
    start_time = time.time()
    executor_obj = ThreadPoolExecutor(max_workers=max_threads)

    try:
        # Submit all tasks
        future_to_ip = {
            executor_obj.submit(test_port_443, ip, timeout, use_tls): ip
            for ip in ip_list
        }

        # Process results as they complete
        for future in as_completed(future_to_ip):
            result = future.result()
            completed += 1

            if result['open']:
                results['open'].append(result['ip'])
                print(f"  [{completed}/{len(ip_list)}] ✓ {result['ip']} - OPEN")

                if stop_on_first:
                    print(f"\n[+] First successful connection found! Stopping scan...")
                    # Cancel remaining futures
                    for f in future_to_ip:
                        f.cancel()
                    break
            else:
                results['closed'].append(result['ip'])

            # Progress update every 50 IPs
            if completed % 50 == 0:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                remaining = len(ip_list) - completed
                eta = remaining / rate if rate > 0 else 0
                print(f"  [{completed}/{len(ip_list)}] Progress: {completed/len(ip_list)*100:.1f}% | "
                      f"Rate: {rate:.1f} IPs/s | ETA: {eta:.0f}s")

    finally:
        executor_obj.shutdown(wait=False)

    elapsed = time.time() - start_time
    print(f"\n[+] Scan complete in {elapsed:.1f}s")
    if completed > 0:
        print(f"[+] Rate: {completed/elapsed:.1f} IPs/s")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Scan IP ranges from JSON for open port 443",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "json_file",
        help="JSON file containing IP ranges (CIDR notation)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2,
        help="Connection timeout in seconds (default: 2)"
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=50,
        help="Number of concurrent threads (default: 50)"
    )
    parser.add_argument(
        "--output",
        default="port_443_results.json",
        help="Output file for results (default: port_443_results.json)"
    )
    parser.add_argument(
        "--geo-filter",
        action="store_true",
        help="Filter to US IPs only, prioritize by distance from Chicago"
    )
    parser.add_argument(
        "--geo-db",
        help="Path to GeoLite2 City database (.mmdb file)"
    )
    parser.add_argument(
        "--max-distance",
        type=float,
        help="Max distance from Chicago in miles (e.g., 500)"
    )
    parser.add_argument(
        "--latency-sample",
        type=int,
        default=0,
        help="Sample N IPs per region for latency testing (default: 0)"
    )
    parser.add_argument(
        "--progressive-scan",
        action="store_true",
        help="Start at --max-distance and expand by 100 miles until first hit found"
    )
    parser.add_argument(
        "--distance-increment",
        type=int,
        default=100,
        help="Miles to expand per iteration in progressive scan (default: 100)"
    )
    parser.add_argument(
        "--max-progressive-distance",
        type=int,
        default=3000,
        help="Maximum distance for progressive scan (default: 3000 miles)"
    )
    parser.add_argument(
        "--use-tls",
        action="store_true",
        help="Perform TLS handshake instead of just TCP connect (more realistic for CDN/HTTPS testing)"
    )

    args = parser.parse_args()

    print("="*70)
    print("PORT 443 SCANNER")
    print("="*70)

    # Read JSON file
    print(f"\n[+] Reading {args.json_file}...")
    try:
        with open(args.json_file, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"[!] Error: File '{args.json_file}' not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[!] Error: Invalid JSON in '{args.json_file}': {e}")
        sys.exit(1)

    # Handle different JSON structures
    cidr_list = []

    if isinstance(data, list):
        # Check if it's a list of objects (Azure format) or list of strings
        if data and isinstance(data[0], dict):
            # Azure format: list of objects with properties.addressPrefixes
            print(f"[+] Detected Azure JSON format")
            for entry in data:
                if 'properties' in entry and 'addressPrefixes' in entry['properties']:
                    name = entry.get('name', 'Unknown')
                    prefixes = entry['properties']['addressPrefixes']
                    print(f"[+] Extracting {len(prefixes)} ranges from '{name}'")
                    cidr_list.extend(prefixes)
        else:
            # Simple list of CIDR strings
            cidr_list = data

    elif isinstance(data, dict):
        # Try common keys for simple dictionary format
        if 'ranges' in data:
            cidr_list = data['ranges']
        elif 'cidrs' in data:
            cidr_list = data['cidrs']
        elif 'networks' in data:
            cidr_list = data['networks']
        elif 'ips' in data:
            cidr_list = data['ips']
        elif 'addressPrefixes' in data:
            cidr_list = data['addressPrefixes']
        else:
            print(f"[!] Error: Cannot find IP ranges in JSON. Keys: {list(data.keys())}")
            print("[!] Expected one of: 'ranges', 'cidrs', 'networks', 'ips', 'addressPrefixes'")
            print("[!] Or provide a JSON array directly")
            sys.exit(1)
    else:
        print(f"[!] Error: Unexpected JSON structure (type: {type(data)})")
        sys.exit(1)

    if not cidr_list:
        print("[!] Error: No IP ranges found in JSON")
        sys.exit(1)

    print(f"[+] Total CIDR ranges/IPs extracted: {len(cidr_list)}")

    # Expand CIDR ranges
    print(f"[+] Expanding CIDR ranges to individual IPs...")
    ip_list = expand_cidr_ranges(cidr_list)

    if not ip_list:
        print("[!] No valid IPs found after expanding ranges")
        sys.exit(1)

    print(f"[+] Total IPs to scan: {len(ip_list)}")

    # Progressive scanning mode
    if args.geo_filter and args.progressive_scan:
        if not args.max_distance:
            print("\n[!] ERROR: --progressive-scan requires --max-distance to be set")
            sys.exit(1)

        print("\n" + "="*70)
        print("PROGRESSIVE DISTANCE SCAN MODE")
        print("="*70)
        print(f"[+] Starting distance: {args.max_distance} miles from Chicago")
        print(f"[+] Increment: {args.distance_increment} miles per iteration")
        print(f"[+] Maximum distance: {args.max_progressive_distance} miles")
        print(f"[+] Scan settings: {args.threads} threads, {args.timeout}s timeout")

        all_scanned_ips = set()
        current_distance = args.max_distance
        results = {'open': [], 'closed': []}

        while current_distance <= args.max_progressive_distance:
            print("\n" + "="*70)
            print(f"SCANNING WITHIN {current_distance} MILES")
            print("="*70)

            # Filter IPs for current distance
            filtered = filter_and_prioritize_ips(
                ip_list,
                args.geo_db,
                max_distance=current_distance,
                latency_sample=0  # Skip latency sampling in progressive mode
            )

            # Remove already-scanned IPs
            new_ips = [ip for ip in filtered if str(ip) not in all_scanned_ips]

            if not new_ips:
                print(f"\n[+] No new IPs to scan at {current_distance} miles")
                current_distance += args.distance_increment
                continue

            print(f"\n[+] New IPs to scan in this iteration: {len(new_ips)}")
            print(f"[+] Previously scanned: {len(all_scanned_ips)}")

            # Mark these IPs as scanned
            for ip in new_ips:
                all_scanned_ips.add(str(ip))

            # Scan with stop_on_first=True
            scan_results = scan_ips(
                new_ips,
                timeout=args.timeout,
                max_threads=args.threads,
                stop_on_first=True,
                use_tls=args.use_tls
            )

            # Merge results
            results['open'].extend(scan_results['open'])
            results['closed'].extend(scan_results['closed'])

            # If we found an open IP, stop
            if scan_results['open']:
                print("\n" + "="*70)
                print("SUCCESS!")
                print("="*70)
                print(f"[+] Found working IP at {current_distance} miles from Chicago")
                print(f"[+] IP: {scan_results['open'][0]}")
                break

            # No hits, expand distance
            print(f"\n[+] No open ports found within {current_distance} miles")
            current_distance += args.distance_increment
        else:
            print("\n" + "="*70)
            print(f"[!] No open ports found within {args.max_progressive_distance} miles")
            print("="*70)

    # Standard geo-filtering (non-progressive)
    elif args.geo_filter:
        ip_list = filter_and_prioritize_ips(
            ip_list,
            args.geo_db,
            max_distance=args.max_distance,
            latency_sample=args.latency_sample
        )

        if not ip_list:
            print("\n[!] No IPs remaining after geo-filtering")
            sys.exit(1)

        print(f"\n[+] IPs to scan after geo-filtering: {len(ip_list)}")

        # Estimate time
        estimated_time = len(ip_list) * args.timeout / args.threads
        print(f"[+] Estimated time: {estimated_time:.0f}s (worst case)")

        # Scan
        results = scan_ips(ip_list, timeout=args.timeout, max_threads=args.threads, use_tls=args.use_tls)

    # No geo-filtering
    else:
        # Estimate time
        estimated_time = len(ip_list) * args.timeout / args.threads
        print(f"[+] Estimated time: {estimated_time:.0f}s (worst case)")

        # Scan
        results = scan_ips(ip_list, timeout=args.timeout, max_threads=args.threads, use_tls=args.use_tls)

    # Summary
    print("\n" + "="*70)
    print("RESULTS SUMMARY")
    print("="*70)
    print(f"Total IPs scanned: {len(ip_list)}")
    print(f"Port 443 OPEN: {len(results['open'])}")
    print(f"Port 443 CLOSED/FILTERED: {len(results['closed'])}")
    print(f"Success rate: {len(results['open'])/len(ip_list)*100:.2f}%")

    if results['open']:
        print(f"\nIPs with port 443 open:")
        for ip in sorted(results['open'], key=lambda x: ipaddress.ip_address(x)):
            print(f"  • {ip}")

    # Save results
    output_data = {
        'scan_date': datetime.now().isoformat(),
        'total_ips': len(ip_list),
        'open_count': len(results['open']),
        'closed_count': len(results['closed']),
        'open_ips': sorted(results['open'], key=lambda x: ipaddress.ip_address(x)),
        'closed_ips': sorted(results['closed'], key=lambda x: ipaddress.ip_address(x)),
        'scan_parameters': {
            'timeout': args.timeout,
            'threads': args.threads,
            'source_file': args.json_file
        }
    }

    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"\n[+] Results saved to: {args.output}")
    print("="*70)


if __name__ == "__main__":
    main()
