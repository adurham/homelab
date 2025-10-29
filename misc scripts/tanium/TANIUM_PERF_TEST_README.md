# Tanium Client Download Performance Test

Python script to test and compare Tanium Client download performance between:
- **Legacy mode**: Downloads via port 17472
- **CDN mode**: Downloads via port 443

## Features

- Runs configurable number of iterations (default: 5) for each mode
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

## Usage

```bash
python3 tanium_download_perf_test.py \
  --tc-dir /opt/Tanium/TaniumClient \
  --file-url https://your-tanium-server/path/to/test-file.bin \
  --iterations 5 \
  --verbose
```

### Arguments

- `--tc-dir`: Path to Tanium Client installation directory (required)
- `--file-url`: URL of the file to download for testing (required)
- `--iterations`: Number of test runs per mode (default: 5)
- `--verbose`: Show SOAP request/response XML (optional)

### Example

```bash
# Linux
sudo python3 tanium_download_perf_test.py \
  --tc-dir /opt/Tanium/TaniumClient \
  --file-url https://tanium-server.corp.com/downloads/test-100mb.bin

# macOS
sudo python3 tanium_download_perf_test.py \
  --tc-dir /Library/Tanium/TaniumClient \
  --file-url https://tanium-server.corp.com/downloads/test-100mb.bin

# Windows (run as Administrator)
python tanium_download_perf_test.py ^
  --tc-dir "C:\Program Files\Tanium\Tanium Client" ^
  --file-url https://tanium-server.corp.com/downloads/test-100mb.bin
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

## Notes

- Script requires sudo/admin privileges to control the Tanium Client service
- Ensure the test file URL is accessible from the Tanium Client
- The script assumes TaniumClient.ini is in the tc-dir (will be created if missing)
- Each test iteration clears the Downloads directory to avoid cached results
- Results are calculated only for successfully completed downloads

## Troubleshooting

- **Permission denied**: Run with sudo (Linux/macOS) or as Administrator (Windows)
- **Service control fails**: Check service name matches your platform
- **SOAP session error**: Ensure Tanium Client is running and soap_session file exists
- **Download timeout**: Increase timeout in code or choose smaller test file
