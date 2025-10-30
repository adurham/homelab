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
    server_response_latencies = []
    inter_packet_delays = []

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

        # Server behavior metrics (ROOT CAUSE INDICATORS)
        if 'server_response_latency' in m and m['server_response_latency'].get('samples', 0) > 0:
            server_response_latencies.append(m['server_response_latency']['avg_ms'])

        if 'inter_packet_delay' in m and m['inter_packet_delay'].get('samples', 0) > 0:
            inter_packet_delays.append(m['inter_packet_delay']['avg_ms'])

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

    if server_response_latencies:
        print(f"\n⚠️ Server Response Latency (ROOT CAUSE INDICATOR):")
        print(f"  Average: {statistics.mean(server_response_latencies):.2f} ms")
        print(f"  Min: {min(server_response_latencies):.2f} ms")
        print(f"  Max: {max(server_response_latencies):.2f} ms")

    if inter_packet_delays:
        print(f"\n⚠️ Inter-Packet Delay (ROOT CAUSE INDICATOR):")
        print(f"  Average: {statistics.mean(inter_packet_delays):.3f} ms")
        print(f"  Min: {min(inter_packet_delays):.3f} ms")
        print(f"  Max: {max(inter_packet_delays):.3f} ms")


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

    # ROOT CAUSE INDICATORS
    legacy_inter_packet_delays = [r['metrics']['inter_packet_delay']['avg_ms']
                                   for r in legacy_results if 'inter_packet_delay' in r['metrics'] and r['metrics']['inter_packet_delay'].get('samples', 0) > 0]
    cdn_inter_packet_delays = [r['metrics']['inter_packet_delay']['avg_ms']
                                for r in cdn_results if 'inter_packet_delay' in r['metrics'] and r['metrics']['inter_packet_delay'].get('samples', 0) > 0]

    legacy_server_response = [r['metrics']['server_response_latency']['avg_ms']
                               for r in legacy_results if 'server_response_latency' in r['metrics'] and r['metrics']['server_response_latency'].get('samples', 0) > 0]
    cdn_server_response = [r['metrics']['server_response_latency']['avg_ms']
                            for r in cdn_results if 'server_response_latency' in r['metrics'] and r['metrics']['server_response_latency'].get('samples', 0) > 0]

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
    print("ROOT CAUSE DIAGNOSIS")
    print("="*80)

    issues = []

    # ROOT CAUSE ANALYSIS: Check Inter-Packet Delays (PRIMARY INDICATOR)
    if cdn_inter_packet_delays and legacy_inter_packet_delays:
        cdn_avg_delay = statistics.mean(cdn_inter_packet_delays)
        legacy_avg_delay = statistics.mean(legacy_inter_packet_delays)
        ratio = cdn_avg_delay / legacy_avg_delay if legacy_avg_delay > 0 else 0

        print(f"\n🔍 Inter-Packet Delay Analysis:")
        print(f"  Legacy: {legacy_avg_delay:.3f} ms")
        print(f"  CDN: {cdn_avg_delay:.3f} ms")
        print(f"  Ratio: {ratio:.1f}x slower")

        if ratio > 3:  # CDN is 3x slower at sending consecutive packets
            issues.append({
                'severity': 'CRITICAL',
                'issue': '🔴 ROOT CAUSE: CDN Server Slow at Sustained Data Delivery',
                'details': f'CDN inter-packet delay is {ratio:.1f}x slower than Legacy',
                'explanation': [
                    'The CDN server is slow to send consecutive data packets',
                    'This indicates the server is pausing/throttling between sends',
                    'NOT a network latency issue - the server itself is slow',
                    'Small TCP windows are a SYMPTOM of this, not the cause'
                ],
                'causes': [
                    'CDN server rate limiting or throttling configuration',
                    'CDN server buffer/queue management issues',
                    'CDN application-level delays (slow disk I/O, CPU)',
                    'CDN deliberately limiting bandwidth per connection'
                ],
                'recommendations': [
                    'Contact Tanium to investigate CDN server configuration',
                    'Check if CDN has per-connection rate limits',
                    'Request CDN server logs/metrics for this time period',
                    'Workaround: Use multiple parallel connections',
                    'Verify CDN is not under heavy load'
                ]
            })

    # Check Server Response Latency (Initial Response)
    if cdn_server_response and legacy_server_response:
        cdn_avg_response = statistics.mean(cdn_server_response)
        legacy_avg_response = statistics.mean(legacy_server_response)
        response_ratio = cdn_avg_response / legacy_avg_response if legacy_avg_response > 0 else 0

        print(f"\n🔍 Server Response Latency:")
        print(f"  Legacy: {legacy_avg_response:.2f} ms")
        print(f"  CDN: {cdn_avg_response:.2f} ms")
        print(f"  Ratio: {response_ratio:.1f}x slower" if response_ratio >= 1 else f"  Ratio: {1/response_ratio:.1f}x faster")

        if cdn_avg_response > 10 and response_ratio > 2:
            issues.append({
                'severity': 'MEDIUM',
                'issue': 'CDN Server Slow to Initially Respond',
                'details': f'CDN takes {response_ratio:.1f}x longer to respond to requests',
                'explanation': [
                    'CDN takes longer to respond to initial requests',
                    'Different from sustained delivery issues'
                ],
                'causes': [
                    'CDN processing overhead',
                    'Geographic distance to CDN endpoint',
                    'CDN under load'
                ]
            })

    # Check for packet loss (secondary issue)
    if cdn_retrans:
        cdn_retrans_avg = statistics.mean(cdn_retrans)
        if cdn_retrans_avg > 1.0:
            issues.append({
                'severity': 'MEDIUM',
                'issue': 'Elevated Packet Loss',
                'details': f'Retransmission rate: {cdn_retrans_avg:.3f}% (should be <1%)',
                'explanation': [
                    'Some packets being lost/retransmitted',
                    'This exacerbates the slow server issue'
                ],
                'causes': [
                    'Network path congestion to CDN',
                    'Firewall/middlebox issues'
                ],
                'recommendations': [
                    'Run MTR to CDN endpoint to identify packet loss location',
                    'Check firewall logs'
                ]
            })

    # Throughput check (outcome, not cause)
    if cdn_throughput:
        cdn_avg = statistics.mean(cdn_throughput)
        if cdn_avg < 100:
            issues.append({
                'severity': 'HIGH',
                'issue': 'Low CDN Throughput (SYMPTOM)',
                'details': f'Average throughput: {cdn_avg:.2f} Mbps (expected >100 Mbps)',
                'explanation': [
                    'This is the OUTCOME of the slow server behavior above',
                    'Fixing the server inter-packet delays will fix this'
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
