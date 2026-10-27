#!/usr/bin/env python3
"""Sample BLE RSSI (dBm) for the Yale/August locks from Home Assistant and push
it to VictoriaMetrics, so "did moving the antenna help?" becomes a graph rather
than a guess.

Read-only: it reuses HA's own passive Bluetooth scanner state (the integration
diagnostics), so it never starts a scan of its own and cannot disturb yalexs_ble.

Usage:  ha_ble_rssi.py            (cron/timer, every 5 min)
Metric: ha_ble_rssi_dbm{address="..",name=".."}
"""
import json
import sys
import urllib.request

HA = "http://192.168.86.2:8123"
VM = "http://172.16.0.42:8428"
TOKEN_FILE = "/etc/ha-ble-rssi/token"
BT_ENTRY_FILE = "/etc/ha-ble-rssi/bluetooth_entry_id"
# Yale/August devices in this house all use the 78:9C:85 OUI. Set PREFIX="" to
# export every discovered device instead.
PREFIX = "78:9C:85"


def read(path):
    with open(path) as fh:
        return fh.read().strip()


def gather():
    tok = read(TOKEN_FILE)
    entry = read(BT_ENTRY_FILE)
    url = f"{HA}/api/diagnostics/config_entry/{entry}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    doc = json.load(urllib.request.urlopen(req, timeout=60))

    found = {}

    def walk(node):
        if isinstance(node, dict):
            addr = str(node.get("address") or "").upper()
            if addr and "rssi" in node and addr.startswith(PREFIX):
                try:
                    rssi = int(node["rssi"])
                except (TypeError, ValueError):
                    rssi = None
                if rssi is not None:
                    # last writer wins; HA keeps a single live record per device
                    found[addr] = (node.get("name") or "", rssi)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return found


def push(found):
    if not found:
        print("ha-ble-rssi: no lock advertisements in HA's scanner state", file=sys.stderr)
        return 1
    lines = []
    for addr, (name, rssi) in found.items():
        safe = name.replace("\\", "").replace('"', "")
        lines.append(f'ha_ble_rssi_dbm{{address="{addr}",name="{safe}"}} {rssi}')
    body = "\n".join(lines) + "\n"
    req = urllib.request.Request(f"{VM}/api/v1/import/prometheus", data=body.encode(),
                                 headers={"Content-Type": "text/plain"})
    urllib.request.urlopen(req, timeout=20).read()
    print("ha-ble-rssi:", "; ".join(f"{a} {r}dBm" for a, (_, r) in found.items()))
    return 0


if __name__ == "__main__":
    sys.exit(push(gather()))
