# Tanium Client Download Performance Test

Python script to test and compare Tanium Client download performance between:
- **Legacy mode**: Downloads via port 17472
- **CDN mode**: Downloads via port 443

## Part of a 2-Step Workflow

This script is **Step 1** of the performance analysis workflow:

1. **Generate Test Data** (this script): `tanium_download_perf_test.py`
   - Runs performance tests
   - Captures network traffic (optional with `--capture-traffic`)
   - Creates directory with PCAPs: `tanium_pcaps_YYYYMMDD_HHMMSS/`

2. **Analyze Results**: `analyze_tanium_pcaps.py`
   - Analyzes captured packets
   - Identifies throttling, latency, and performance issues
   - See: `ANALYZE_TANIUM_PCAPS_README.md` for details

## Features

- Runs configurable number of iterations (default: 5) for each mode
- **Captures network packets** for detailed analysis (with `--capture-traffic`)
- Clears Downloads directory between each test to avoid cache hits
- Automatically starts/stops Tanium Client service
- Toggles CDN configuration between test phases
- Measures download duration and throughput (Mbps)
- Outputs results to console and JSON file
- Cross-platform support (Linux, macOS, Windows)

## Requirements

- Python 3.x (or 2.7)
- Tanium Client installed
- Administrative/sudo privileges (for service control)
- Access to Tanium Client directory
- **tcpdump** (for packet capture with `--capture-traffic`)

## Usage

### Basic Usage (Timing Only)
```bash
python3 tanium_download_perf_test.py \
  --tc-dir /opt/Tanium/TaniumClient \
  --file-url https://your-tanium-server/path/to/test-file.bin \
  --iterations 5
```

### Recommended: With Packet Capture (For Deep Analysis)
```bash
python3 tanium_download_perf_test.py \
  --tc-dir /opt/Tanium/TaniumClient \
  --file-url https://your-tanium-server/path/to/test-file.bin \
  --iterations 5 \
  --capture-traffic
```

This creates a directory `tanium_pcaps_YYYYMMDD_HHMMSS/` with packet captures for analysis.

### Arguments

- `--tc-dir`: Path to Tanium Client installation directory (auto-detected if not specified)
- `--file-url`: URL of the file to download for testing (required)
- `--file-hash`: SHA-256 hash of file (alternative to --file-url, constructs URL as https://127.0.0.1/cache/<HASH>)
- `--iterations`: Number of test runs per mode (default: 5)
- `--capture-traffic`: **Capture network packets for detailed analysis** (recommended)
- `--verbose`: Show SOAP request/response XML (optional)

### Examples

**Linux (with packet capture)**
```bash
sudo python3 tanium_download_perf_test.py \
  --tc-dir /opt/Tanium/TaniumClient \
  --file-url https://tanium-server.corp.com/downloads/test-100mb.bin \
  --capture-traffic
```

**macOS (with packet capture)**
```bash
sudo python3 tanium_download_perf_test.py \
  --tc-dir /Library/Tanium/TaniumClient \
  --file-url https://tanium-server.corp.com/downloads/test-100mb.bin \
  --capture-traffic
```

**Windows (run as Administrator, with packet capture)**
```powershell
python tanium_download_perf_test.py ^
  --tc-dir "C:\Program Files\Tanium\Tanium Client" ^
  --file-url https://tanium-server.corp.com/downloads/test-100mb.bin ^
  --capture-traffic
```

**Using file hash instead of URL**
```bash
sudo python3 tanium_download_perf_test.py \
  --file-hash a1b2c3d4e5f6... \
  --capture-traffic
```

## How It Works

1. **Phase 1: Legacy Testing**
   - Stops Tanium Client service
   - Sets `EnableCDNDownloads=0` in TaniumClient.ini
   - Starts Tanium Client service
   - For each iteration:
     - Clears Downloads directory
     - Requests file via SOAP API (localhost:17473)
     - Monitors download completion
     - Measures duration and throughput

2. **Phase 2: CDN Testing**
   - Stops Tanium Client service
   - Sets `EnableCDNDownloads=1` in TaniumClient.ini
   - Starts Tanium Client service
   - Repeats same iterations as Phase 1

3. **Results**
   - Console output shows real-time progress
   - Summary statistics (avg/min/max duration, throughput)
   - Comparison between modes (% improvement)
   - Detailed JSON file saved with timestamp

## Output

### Console Output
```
Starting Tanium Client Download Performance Test
File: https://example.com/test-file.bin
Iterations per mode: 5

############################################################
# Phase 1: Legacy Downloads (Port 17472)
############################################################
...

############################################################
# Phase 2: CDN Downloads (Port 443)
############################################################
...

############################################################
# Test Results Summary
############################################################

Legacy (Port 17472):
  Completed: 5/5
  Avg Duration: 45.32s
  Min Duration: 43.21s
  Max Duration: 47.89s
  Avg Throughput: 176.54 Mbps

CDN (Port 443):
  Completed: 5/5
  Avg Duration: 28.67s
  Min Duration: 27.12s
  Max Duration: 30.45s
  Avg Throughput: 278.92 Mbps

Comparison:
  Duration improvement: -36.7%
  Throughput improvement: +58.0%

[+] Detailed results saved to: tanium_perf_test_20250129_143052.json
```

### JSON Output
```json
{
  "test_info": {
    "file_url": "https://example.com/test-file.bin",
    "iterations": 5,
    "timestamp": "2025-01-29T14:30:52.123456"
  },
  "results": [
    {
      "iteration": 1,
      "mode": "Legacy",
      "status": "Completed",
      "duration": 45.32,
      "file_size": 104857600,
      "throughput_mbps": 176.54,
      "timestamp": "2025-01-29T14:31:37.123456"
    },
    ...
  ],
  "summary": {
    "legacy": {
      "count": 5,
      "avg_duration": 45.32,
      "avg_throughput": 176.54,
      "min_duration": 43.21,
      "max_duration": 47.89
    },
    "cdn": {
      "count": 5,
      "avg_duration": 28.67,
      "avg_throughput": 278.92,
      "min_duration": 27.12,
      "max_duration": 30.45
    }
  }
}
```

## Output Files

### Without --capture-traffic
- **Console**: Real-time progress and summary statistics
- **JSON file**: `tanium_perf_test_YYYYMMDD_HHMMSS.json` with detailed timing data

### With --capture-traffic (Recommended)
- **Console**: Real-time progress and summary statistics
- **JSON file**: `tanium_perf_test_YYYYMMDD_HHMMSS.json` with detailed timing data
- **PCAP directory**: `tanium_pcaps_YYYYMMDD_HHMMSS/` containing:
  - `legacy_iteration_1.pcap` through `legacy_iteration_N.pcap`
  - `cdn_iteration_1.pcap` through `cdn_iteration_N.pcap`

## Complete Analysis Workflow

**Step 1: Run this script with packet capture**
```bash
sudo python3 tanium_download_perf_test.py \
  --file-url https://your-server/test-file.bin \
  --capture-traffic
```

Output: `tanium_pcaps_20250130_143052/` (directory with PCAPs)

**Step 2: Analyze the packet captures**
```bash
python3 analyze_tanium_pcaps.py --pcap-dir tanium_pcaps_20250130_143052/
```

Output:
- Console analysis comparing CDN vs Legacy
- Diagnosis of throttling, latency, and performance issues
- JSON file with detailed metrics

**Step 3: Review results**
See `ANALYZE_TANIUM_PCAPS_README.md` for:
- Understanding each metric
- Interpreting results
- Diagnosing root causes
- Recommendations for Tanium support

## Notes

- Script requires sudo/admin privileges to control the Tanium Client service
- Ensure the test file URL is accessible from the Tanium Client
- The script assumes TaniumClient.ini is in the tc-dir (will be created if missing)
- Each test iteration clears the Downloads directory to avoid cached results
- Results are calculated only for successfully completed downloads
- **Packet capture requires tcpdump** and may require additional permissions

## Troubleshooting

- **Permission denied**: Run with sudo (Linux/macOS) or as Administrator (Windows)
- **Service control fails**: Check service name matches your platform
- **SOAP session error**: Ensure Tanium Client is running and soap_session file exists
- **Download timeout**: Increase timeout in code or choose smaller test file
- **tcpdump not found**: Install tcpdump package (e.g., `apt install tcpdump`, `brew install tcpdump`)
- **Packet capture fails**: Ensure sudo/admin rights and tcpdump is in PATH
