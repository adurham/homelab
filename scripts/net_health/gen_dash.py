#!/usr/bin/env python3
"""Generate the 'Network & Wi-Fi Health' Grafana dashboard (provisioned file) from the netheal_* textfile metrics."""
import json
import sys

DS = {"type": "prometheus", "uid": "victoriametrics"}
panels = []
_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def stat(title, expr, x, unit="none", steps=None, decimals=None, w=4, mappings=None, desc=""):
    steps = steps or [{"color": "green", "value": None}]
    p = {"id": nid(), "type": "stat", "title": title, "description": desc, "datasource": DS,
         "gridPos": {"h": 4, "w": w, "x": x, "y": 0},
         "targets": [{"expr": expr, "refId": "A", "datasource": DS, "instant": True}],
         "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals, "mappings": mappings or [],
                                      "thresholds": {"mode": "absolute", "steps": steps}, "color": {"mode": "thresholds"}}, "overrides": []},
         "options": {"colorMode": "background", "graphMode": "area", "justifyMode": "auto", "orientation": "auto", "textMode": "auto",
                     "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}}
    panels.append(p)


def ts(title, targets, x, y, w=12, h=8, unit="none", desc="", min_=None, max_=None, stack=False, thresholds=None):
    p = {"id": nid(), "type": "timeseries", "title": title, "description": desc, "datasource": DS,
         "gridPos": {"h": h, "w": w, "x": x, "y": y},
         "targets": [{"expr": e, "legendFormat": lf, "refId": chr(65 + i), "datasource": DS} for i, (e, lf) in enumerate(targets)],
         "fieldConfig": {"defaults": {"unit": unit, "min": min_, "max": max_, "custom": {"drawStyle": "line", "lineWidth": 1, "fillOpacity": 12 if stack else 0,
                                                                                       "showPoints": "auto", "spanNulls": 7200000,
                                                                                       "stacking": {"mode": "normal" if stack else "none", "group": "A"}},
                                      "color": {"mode": "palette-classic"},
                                      "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]}}, "overrides": []},
         "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull", "max"]}, "tooltip": {"mode": "multi", "sort": "desc"}}}
    panels.append(p)


# ---- top row: the numbers you glance at
stat("WAN down (Ookla)", 'homeassistant_sensor_data_rate_mbit_per_s{entity="sensor.ookla_speedtest"}', 0, unit="Mbits",
     steps=[{"color": "red", "value": None}, {"color": "orange", "value": 300}, {"color": "green", "value": 600}],
     desc="Hourly Ookla test run by Home Assistant (same series as the Internet Speed dashboard).")
stat("WAN up (Ookla)", 'homeassistant_sensor_data_rate_mbit_per_s{entity="sensor.ookla_speedtest_upload"}', 4, unit="Mbits",
     steps=[{"color": "red", "value": None}, {"color": "orange", "value": 300}, {"color": "green", "value": 600}])
stat("Active problem flags", "netheal_flags", 8, steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
     desc="Number of flags the hourly check raised in its latest run (details in ~/.hermes/cache/net-health/hourly.jsonl).")
stat("Health check last ran", "time() - netheal_last_run_timestamp_seconds", 12, unit="s", decimals=0,
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 5400}, {"color": "red", "value": 9000}],
     desc="Collector liveness: it should run hourly; orange after 90 min, red after 2.5 h.")

# ---- wired side
ts("Mesh nodes + gateway: ping avg (ms)", [('netheal_ping_avg_ms{target=~"router .1|Basement .63|GameRoom .51|MainBedroom .99|AT&T gw"}', "{{target}}")],
   0, 4, unit="ms", desc="Measured on the HA Green (wired probes moved there 2026-11-23): its own reply path to the router is ~10 ms, the mesh nodes stay under 2 ms; a climb means the wired side (switch/cable/node), not Wi-Fi.")
ts("Packet loss (%) to every target", [("netheal_ping_loss_percent", "{{target}}")], 12, 4, unit="percent", min_=0,
   desc="20 pings each, every hour. Anything above 0 on a wired target is worth a look.")

# ---- the air
ts("5 GHz ch149 airtime (%) as heard from the basement",
   [("netheal_air_total_percent", "total decoded"), ("netheal_air_nodes_percent", "mesh nodes"), ("netheal_air_node_multicast_percent", "nodes' multicast re-sends"),
    ("netheal_air_responses_percent", "ACK/CTS")], 0, 28, unit="percent", min_=0,
   desc="45 s monitor capture each hour on ch149/80 MHz. Was 35% total / 11% multicast before the ecobee /29 fix, ~25% / 3-6% after.")
ts("Airtime by transmitter (top 5 each hour, %)", [("netheal_air_transmitter_percent", "{{who}}")], 12, 28, unit="percent", min_=0, stack=True,
   desc="Who is using the channel. A new name here that is not a mesh node is the thing to investigate.")

# ---- broadcast / LAN hygiene
ts("LAN broadcast+multicast frames per second", [("netheal_lan_multicast_pps", "all sources"), ("netheal_lan_source_pps", "{{who}}")], 0, 36, unit="pps", min_=0,
   desc="Wired 45 s census. Every node re-sends each of these over the air at the slowest speed. The ecobee was 63-95/s here before the 2026-11-19 fix; it should now be ~2.5/s. Home Assistant (Nmap Tracker) sits near 7-11/s.")
ts("Retry % of the top-5 transmitters", [("netheal_air_transmitter_retry_percent", "{{who}}")], 12, 36, unit="percent", min_=0, max_=100,
   desc="High retries on a device with real airtime = it has a bad link (weak signal, far node).")
ts("DNS lookup time (ms)", [("netheal_dns_query_ms", "{{server}}")], 0, 44, unit="ms", min_=0)
ts("Router uptime (hours) / DHCP offers", [("netheal_router_uptime_seconds / 3600", "router uptime h"), ("netheal_dhcp_offers", "DHCP offers (expect 1)")], 12, 44, unit="none", min_=0,
   desc="Uptime dropping to near 0 = the Nest rebooted. DHCP offers other than 1 = a rogue or dead DHCP server.")

dash = {
    "uid": "network-health", "title": "Network & Wi-Fi Health", "tags": ["network", "wifi", "homelab"], "schemaVersion": 39, "version": 1,
    "editable": True, "graphTooltip": 1, "refresh": "5m", "time": {"from": "now-24h", "to": "now"}, "timezone": "browser",
    "description": "Hourly health check: cabled probes run on the Home Assistant box (/config/scripts/net_wired.py), Wi-Fi capture on the basement workstation (net_health.py) -> node_exporter textfile netheal.prom. "
                   "Collector: ~/.hermes/scripts/net_health.py. Process notes: docs/ecobee-lan-scan.md.",
    "panels": panels, "templating": {"list": []}, "annotations": {"list": []}, "links": [],
}
out = sys.argv[1] if len(sys.argv) > 1 else "network_health.json"
for _p in panels:  # the Mac panels used to sit at y=12..27; nothing may point at the Mac now
    if _p["gridPos"]["y"] >= 28:
        _p["gridPos"]["y"] -= 16
json.dump(dash, open(out, "w"), indent=2)
print("wrote", out, "panels:", len(panels))
