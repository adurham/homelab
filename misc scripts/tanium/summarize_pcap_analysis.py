#!/usr/bin/env python3
"""
Summarize PCAP analysis results and generate diagnosis
"""

import json
import sys
import statistics


def summarize_analysis(json_file):
    """Parse and summarize PCAP analysis JSON"""

    with open(json_file, 'r') as f:
        data = json.load(f)

    print("="*80)
    print("TANIUM DOWNLOAD PCAP ANALYSIS SUMMARY")
    print("="*80)

    # Extract results for each mode
    legacy_results = data.get('results', {}).get('legacy', [])
    cdn_results = data.get('results', {}).get('cdn', [])

    print(f"\nFiles analyzed:")
    print(f"  Legacy: {len(legacy_results)}")
    print(f"  CDN: {len(cdn_results)}")

    # Analyze Legacy
    if legacy_results:
        print("\n" + "="*80)
        print("LEGACY (Port 17472) ANALYSIS")
        print("="*80)
        analyze_mode(legacy_results)

    # Analyze CDN
    if cdn_results:
        print("\n" + "="*80)
        print("CDN (Port 443) ANALYSIS")
        print("="*80)
        analyze_mode(cdn_results)

    # Comparison
    if legacy_results and cdn_results:
        print("\n" + "="*80)
        print("COMPARISON & DIAGNOSIS")
        print("="*80)
        compare_and_diagnose(legacy_results, cdn_results)


def analyze_mode(results):
    """Analyze metrics for a mode (legacy or cdn)"""

    # Collect metrics
    throughputs = []
    rtts = []
    retrans_rates = []
    handshake_times = []
    client_windows = []
    server_windows = []
    dup_acks = []
    zero_windows = []

    for result in results:
        m = result.get('metrics', {})

        # Basic stats
        if 'basic' in m:
            throughputs.append(m['basic']['avg_throughput_mbps'])

        # RTT
        if 'rtt' in m and m['rtt'].get('samples', 0) > 0:
            rtts.append(m['rtt']['avg_ms'])

        # Retransmissions
        if 'retransmissions' in m:
            retrans_rates.append(m['retransmissions']['retransmission_rate_pct'])

        # Connection
        if 'connection' in m and 'handshake_time_ms' in m['connection']:
            handshake_times.append(m['connection']['handshake_time_ms'])

        # Window sizes
        if 'window_sizes' in m:
            if 'client_advertised_avg_bytes' in m['window_sizes']:
                client_windows.append(m['window_sizes']['client_advertised_avg_bytes'])
            if 'server_advertised_avg_bytes' in m['window_sizes']:
                server_windows.append(m['window_sizes']['server_advertised_avg_bytes'])

        # TCP flags
        if 'tcp_flags' in m:
            dup_acks.append(m['tcp_flags'].get('duplicate_acks', 0))
            zero_windows.append(m['tcp_flags'].get('zero_windows', 0))

    # Print summary
    if throughputs:
        print(f"\nThroughput:")
        print(f"  Average: {statistics.mean(throughputs):.2f} Mbps")
        print(f"  Min: {min(throughputs):.2f} Mbps")
        print(f"  Max: {max(throughputs):.2f} Mbps")
        if len(throughputs) > 1:
            print(f"  Std Dev: {statistics.stdev(throughputs):.2f} Mbps")

    if rtts:
        print(f"\nRound-Trip Time (RTT):")
        print(f"  Average: {statistics.mean(rtts):.2f} ms")
        print(f"  Min: {min(rtts):.2f} ms")
        print(f"  Max: {max(rtts):.2f} ms")
        if len(rtts) > 1:
            print(f"  Std Dev: {statistics.stdev(rtts):.2f} ms")

    if handshake_times:
        print(f"\nTCP Handshake Time:")
        print(f"  Average: {statistics.mean(handshake_times):.2f} ms")

    if retrans_rates:
        print(f"\nRetransmissions:")
        print(f"  Average Rate: {statistics.mean(retrans_rates):.3f}%")
        print(f"  Max Rate: {max(retrans_rates):.3f}%")

    if server_windows:
        print(f"\nTCP Window Sizes:")
        print(f"  Server advertised: {statistics.mean(server_windows)/1024:.2f} KB avg")
    if client_windows:
        print(f"  Client advertised: {statistics.mean(client_windows)/1024:.2f} KB avg")

    if dup_acks:
        print(f"\nTCP Issues:")
        print(f"  Duplicate ACKs: {statistics.mean(dup_acks):.1f} avg per capture")
    if zero_windows:
        print(f"  Zero Windows: {statistics.mean(zero_windows):.1f} avg per capture")


def compare_and_diagnose(legacy_results, cdn_results):
    """Compare legacy vs CDN and generate diagnosis"""

    # Extract key metrics
    legacy_throughput = [r['metrics']['basic']['avg_throughput_mbps']
                         for r in legacy_results if 'basic' in r['metrics']]
    cdn_throughput = [r['metrics']['basic']['avg_throughput_mbps']
                      for r in cdn_results if 'basic' in r['metrics']]

    legacy_rtt = [r['metrics']['rtt']['avg_ms']
                  for r in legacy_results if 'rtt' in r['metrics'] and r['metrics']['rtt'].get('samples', 0) > 0]
    cdn_rtt = [r['metrics']['rtt']['avg_ms']
               for r in cdn_results if 'rtt' in r['metrics'] and r['metrics']['rtt'].get('samples', 0) > 0]

    legacy_retrans = [r['metrics']['retransmissions']['retransmission_rate_pct']
                      for r in legacy_results if 'retransmissions' in r['metrics']]
    cdn_retrans = [r['metrics']['retransmissions']['retransmission_rate_pct']
                   for r in cdn_results if 'retransmissions' in r['metrics']]

    cdn_windows = [r['metrics']['window_sizes']['server_advertised_avg_bytes']
                   for r in cdn_results if 'window_sizes' in r['metrics'] and 'server_advertised_avg_bytes' in r['metrics']['window_sizes']]

    # Print comparison
    print(f"\nPerformance Comparison:")
    if legacy_throughput and cdn_throughput:
        legacy_avg = statistics.mean(legacy_throughput)
        cdn_avg = statistics.mean(cdn_throughput)
        diff_pct = ((legacy_avg - cdn_avg) / cdn_avg) * 100
        print(f"  Legacy: {legacy_avg:.2f} Mbps")
        print(f"  CDN: {cdn_avg:.2f} Mbps")
        print(f"  Legacy is {diff_pct:.1f}% faster than CDN")

    if legacy_rtt and cdn_rtt:
        legacy_rtt_avg = statistics.mean(legacy_rtt)
        cdn_rtt_avg = statistics.mean(cdn_rtt)
        print(f"\nLatency:")
        print(f"  Legacy RTT: {legacy_rtt_avg:.2f} ms")
        print(f"  CDN RTT: {cdn_rtt_avg:.2f} ms")
        print(f"  CDN has {cdn_rtt_avg - legacy_rtt_avg:.2f} ms more latency")

    # Diagnosis
    print("\n" + "="*80)
    print("DIAGNOSIS - Why is CDN slower than expected?")
    print("="*80)

    issues = []

    # Issue 1: Check CDN throughput
    if cdn_throughput:
        cdn_avg = statistics.mean(cdn_throughput)
        if cdn_avg < 100:
            issues.append({
                'severity': 'HIGH',
                'issue': 'CDN throughput below 100 Mbps target',
                'details': f'Average CDN throughput is {cdn_avg:.2f} Mbps'
            })

    # Issue 2: Check RTT
    if cdn_rtt:
        cdn_rtt_avg = statistics.mean(cdn_rtt)
        if cdn_rtt_avg > 50:
            issues.append({
                'severity': 'MEDIUM' if cdn_rtt_avg < 100 else 'HIGH',
                'issue': 'High CDN latency',
                'details': f'Average CDN RTT is {cdn_rtt_avg:.2f} ms',
                'causes': [
                    'CDN endpoint may be geographically distant',
                    'Routing inefficiencies to CDN',
                    'Internet/ISP latency'
                ]
            })

    # Issue 3: Check retransmissions
    if cdn_retrans:
        cdn_retrans_avg = statistics.mean(cdn_retrans)
        if cdn_retrans_avg > 1.0:
            issues.append({
                'severity': 'HIGH' if cdn_retrans_avg > 3.0 else 'MEDIUM',
                'issue': 'High packet loss on CDN connection',
                'details': f'Retransmission rate is {cdn_retrans_avg:.3f}% (should be <1%)',
                'causes': [
                    'Network congestion',
                    'Lossy path to CDN',
                    'Firewall/middlebox issues'
                ]
            })

    # Issue 4: Bandwidth-Delay Product
    if cdn_rtt and cdn_windows:
        cdn_rtt_avg = statistics.mean(cdn_rtt) / 1000  # Convert to seconds
        cdn_window_avg = statistics.mean(cdn_windows)
        max_throughput_mbps = (cdn_window_avg * 8) / (cdn_rtt_avg * 1_000_000)

        if max_throughput_mbps < 100:
            issues.append({
                'severity': 'HIGH',
                'issue': 'TCP window size limiting throughput (Bandwidth-Delay Product)',
                'details': f'RTT: {cdn_rtt_avg*1000:.2f} ms, Window: {cdn_window_avg/1024:.2f} KB',
                'explanation': [
                    f'Maximum theoretical throughput = Window / RTT = {max_throughput_mbps:.2f} Mbps',
                    f'This limits CDN downloads to ~{max_throughput_mbps:.0f} Mbps regardless of available bandwidth',
                    f'To achieve 100 Mbps with {cdn_rtt_avg*1000:.2f} ms RTT, need window size of {(100 * 1_000_000 * cdn_rtt_avg / 8) / 1024:.0f} KB'
                ],
                'recommendations': [
                    'Enable TCP window scaling on CDN server (may not be configurable)',
                    'Increase TCP receive buffers on client:',
                    '  - net.ipv4.tcp_rmem = "4096 87380 16777216"',
                    '  - net.core.rmem_max = 16777216',
                    'Consider using multiple parallel connections to work around window limit'
                ]
            })

    # Print issues
    if issues:
        for i, issue in enumerate(issues, 1):
            print(f"\n[Issue #{i}] {issue['issue']}")
            print(f"Severity: {issue['severity']}")
            print(f"Details: {issue['details']}")

            if 'causes' in issue:
                print("Possible Causes:")
                for cause in issue['causes']:
                    print(f"  - {cause}")

            if 'explanation' in issue:
                print("Explanation:")
                for exp in issue['explanation']:
                    print(f"  - {exp}")

            if 'recommendations' in issue:
                print("Recommendations:")
                for rec in issue['recommendations']:
                    print(f"  - {rec}")
    else:
        print("\n[+] No significant issues detected!")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 summarize_pcap_analysis.py <pcap_analysis.json>")
        sys.exit(1)

    summarize_analysis(sys.argv[1])
