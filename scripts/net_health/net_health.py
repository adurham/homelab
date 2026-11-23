#!/usr/bin/env python3
"""Hourly Wi-Fi / LAN health check for the house (no LLM). Scheduled by HOME ASSISTANT (sensor.network_health runs
`ssh ... run` -> `--json` below); see homelab/scripts/net_health/README.md. `--verbose` is the manual human-readable run.

Measurements are split by the owner's rule (2026-11-23): Home Assistant owns everything that is
physically cabled, the workstation is allowed to measure Wi-Fi only.
  * HA (`/config/scripts/net_wired.py`, sensor.network_health_wired): ping loss / latency to the 4 mesh
    nodes, AT&T gateway, WAN and both DNS servers; DNS query time; router uptime + mesh channel; one real
    DHCP DISCOVER (offer count); 45 s wired multicast/broadcast census (top sources, ARP share)
  * workstation (~50 s): per-BSSID channel of every `4D4C` radio, and the 5 GHz ch149/80 MHz monitor
    capture on the idle AX210 -> decoded airtime %, top transmitters, retries, mesh-node multicast airtime
  * the WAN speed test Home Assistant already runs (Ookla via the HA REST API) is only read back
Appends one JSON line to ~/.hermes/cache/net-health/hourly.jsonl. Prints (so cron delivers) ONLY when the set of
flags changes, i.e. new problem / cleared problem; silent when nothing changed. `--verbose` always prints.
`--parse-only <air.pcap>` re-runs the airtime analysis on an existing capture.
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import shutil
import statistics as st
import struct
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict

HOME = os.path.expanduser("~")
DATA = HOME + "/.hermes/cache/net-health"
RUN = DATA + "/run"
ROOT_SH = HOME + "/.hermes/scripts/net_health_root.sh"
CAP_SECONDS = 45

NODES = {  # 5 GHz BSSID -> name
    "b8:7b:d4:ae:96:df": "router(.1)",
    "b8:7b:d4:ae:97:1b": "Basement pt",
    "bc:df:58:be:4f:91": "MainBedroom pt",
    "bc:df:58:be:4d:1b": "GameRoom pt",
}
SLOW_MS = {"router .1": 25, "AT&T gw": 60}

WIRED = ("router .1", "Basement .63", "GameRoom .51", "MainBedroom .99", "AT&T gw", "DNS .4", "DNS .5")
# The three indoor Nest cams report the SAME DHCP hostname ("nest-cam-indoor"), so the reports
# name them by the AP they are proven to transmit to (receiver address on their uplink frames).
STATIC_NAMES = {"b8:7b:d4:da:5e:17": "foyer-cam", "b8:7b:d4:e8:b2:bf": "basement-cam",
                "3c:31:74:55:a4:2c": "catroom-cam", "18:b4:30:e7:52:8e": "doorbell-cam",
                "1c:53:f9:34:4c:ce": "backyard-cam", "3c:31:74:bf:75:b2": "driveway-cam",
                "44:61:32:df:66:47": "ecobee", "ac:67:84:8c:8d:6f": "Kitchen Hub Max", "98:b6:e9:26:cf:f6": "Switch(.60)",
                "94:83:c4:d7:ea:9e": "GL.iNet(.104)", "1a:78:57:3e:42:5c": "MacBook"}


def sh(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except Exception as e:  # noqa: BLE001
        return "ERR %s" % e


def norm_mac(m):
    """Some captured frames carry the group bit set on the first octet of a node's own address; fold it."""
    b = [int(x, 16) for x in m.split(":")]
    b[0] &= ~1
    return ":".join("%02x" % x for x in b)


# ---------------------------------------------------------------- names
def kea_names():
    out = {}
    try:
        req = urllib.request.Request("http://192.168.86.4:8000/", data=json.dumps({"command": "config-get", "service": ["dhcp4"]}).encode(),
                                     headers={"Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req, timeout=6))
        for s in d[0]["arguments"]["Dhcp4"]["subnet4"]:
            for h in s.get("reservations", []):
                out[h["hw-address"].lower()] = h.get("hostname") or h["ip-address"]
    except Exception:  # noqa: BLE001
        pass
    return out


def arp_map():
    m = {}
    for ln in sh(["/usr/sbin/ip", "-4", "neigh"]).splitlines() or sh(["ip", "-4", "neigh"]).splitlines():
        p = ln.split()
        if "lladdr" in p and p[0].startswith("192.168.86."):  # not the docker bridges' 172.17.x neighbours
            m[p[p.index("lladdr") + 1].lower()] = p[0]
    return m


class Namer:
    def __init__(self):
        self.kea, self.arp = kea_names(), arp_map()

    def __call__(self, mac):
        mac = mac.lower()
        n = norm_mac(mac)
        if n in NODES:
            return NODES[n]
        if mac in STATIC_NAMES:
            return STATIC_NAMES[mac]
        if mac in self.kea:
            return self.kea[mac]
        if mac in self.arp:
            return "ip " + self.arp[mac]
        return mac


# ---------------------------------------------------------------- active probes
def ha_api(path):
    """Read one HA REST endpoint with the token in ~/.hermes/.env (same source ha_ookla uses)."""
    env = {}
    for ln in open(HOME + "/.hermes/.env"):
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    rq = urllib.request.Request(env["HASS_URL"].rstrip("/") + path, headers={"Authorization": "Bearer " + env["HASS_TOKEN"]})
    return json.load(urllib.request.urlopen(rq, timeout=15))


def ha_wired():
    """Everything cabled is measured on the HA box; this only reads the result back."""
    try:
        d = ha_api("/api/states/sensor.network_health_wired")
        a = d.get("attributes", {})
        age = (time.time() - dt.datetime.fromisoformat(d["last_updated"]).timestamp()) / 60
        return {"ping": a.get("ping") or {}, "dns_ms": a.get("dns_ms") or {}, "router": a.get("router") or {},
                "dhcp": a.get("dhcp") or {}, "mc": a.get("mc") or {}, "age_min": round(age)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:60], "ping": {}, "dns_ms": {}, "router": {}, "dhcp": {}, "mc": {}, "age_min": None}


def name_mc(mc, namer):
    """HA's census reports source MACs; name them here where the Kea reservations are."""
    out = {"span_s": mc.get("span_s"), "total_pps": mc.get("total_pps"), "arp_share": mc.get("arp_share"), "top": []}
    if mc.get("error"):
        return {"error": mc["error"]}
    for t in mc.get("top", []):
        out["top"].append({"who": namer(t["mac"]), "mac": t["mac"], "pps": t["pps"]})
    return out


def node_channels():
    out = sh(["nmcli", "-t", "--escape", "no", "-f", "BSSID,SSID,CHAN,FREQ,SIGNAL", "dev", "wifi", "list", "--rescan", "yes"], timeout=30)
    res = {}
    for ln in out.splitlines():
        p = ln.split(":")
        if len(p) < 9:
            continue
        ssid = ":".join(p[6:-3])
        if ssid != "4D4C":
            continue
        res[":".join(p[:6]).lower()] = {"chan": int(p[-3]) if p[-3].isdigit() else p[-3], "sig": p[-1]}
    return res




def ha_ookla():
    """The hourly Ookla test Home Assistant already runs (it feeds the 'Internet Speed' Grafana dashboard)."""
    try:
        env = {}
        for ln in open(HOME + "/.hermes/.env"):
            if "=" in ln and not ln.startswith("#"):
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        out = {}
        for key, ent in (("down", "sensor.ookla_speedtest"), ("up", "sensor.ookla_speedtest_upload"), ("ping", "sensor.ookla_speedtest_ping")):
            rq = urllib.request.Request(env["HASS_URL"].rstrip("/") + "/api/states/" + ent, headers={"Authorization": "Bearer " + env["HASS_TOKEN"]})
            d = json.load(urllib.request.urlopen(rq, timeout=8))
            out[key] = round(float(d["state"]), 1)
            if key == "down":
                out["age_h"] = round((time.time() - dt.datetime.fromisoformat(d["last_updated"]).timestamp()) / 3600, 1)
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:40]}


# ---------------------------------------------------------------- Prometheus textfile (-> VictoriaMetrics -> Grafana)
PROM_PATH = "/var/lib/prometheus/node-exporter/netheal.prom"


def _lbl(**kw):
    return "{" + ",".join('%s="%s"' % (k, re.sub(r'[\\"\n]', "_", str(v))) for k, v in kw.items()) + "}"


def write_prom(r):
    m = {}

    def g(name, help_, value, **labels):
        if value is None:
            return
        m.setdefault(name, (help_, []))[1].append("%s%s %s" % (name, _lbl(**labels) if labels else "", value))

    g("netheal_last_run_timestamp_seconds", "Unix time the hourly network health check last completed.", r["ts"])
    g("netheal_flags", "Number of active problem flags in the last run.", len(r["flags"]))
    for k, v in r["ping"].items():
        g("netheal_ping_avg_ms", "Average ping to a network target (20 probes).", v.get("avg"), target=k)
        g("netheal_ping_max_ms", "Worst ping to a network target.", v.get("max"), target=k)
        g("netheal_ping_loss_percent", "Packet loss to a network target.", v.get("loss"), target=k)
    for k, v in r["dns_ms"].items():
        g("netheal_dns_query_ms", "Recursive DNS lookup time via a LAN resolver.", v, server=k)
    g("netheal_router_uptime_seconds", "Nest router uptime (a drop means it rebooted).", r["router"].get("uptime"))
    g("netheal_dhcp_offers", "DHCP OFFERs received for one DISCOVER (expected 1).", r["dhcp_offers"])
    a = r.get("air", {})
    if a and not a.get("error"):
        g("netheal_air_total_percent", "Decoded airtime share of 5 GHz ch149/80 as heard from the basement.", a["total_air_pct"])
        g("netheal_air_nodes_percent", "Airtime used by the four mesh nodes themselves.", a["nodes_air_pct"])
        g("netheal_air_node_multicast_percent", "Airtime the mesh nodes spend re-sending multicast/broadcast.", a["nodes_mc_air_pct"])
        g("netheal_air_responses_percent", "Airtime used by ACK/CTS responses.", a["responses_pct"])
        g("netheal_air_stations_heard", "Distinct transmitters (>=20 frames) heard on ch149.", a["stations_heard"])
        for t in a["top"][:5]:
            g("netheal_air_transmitter_percent", "Airtime share of one of the top-5 transmitters.", t["air_pct"], who=t["who"])
            g("netheal_air_transmitter_retry_percent", "Retry rate of one of the top-5 transmitters.", t["retry_pct"], who=t["who"])
        for n, v in a["beacons_per_s"].items():
            g("netheal_air_beacons_per_second", "Beacons per second heard from a mesh node.", v, node=n)
    mc = r.get("mc", {})
    if mc and not mc.get("error"):
        g("netheal_lan_multicast_pps", "Wired LAN multicast+broadcast frames per second.", mc["total_pps"])
        g("netheal_lan_arp_share_percent", "Share of LAN multicast that is ARP.", mc["arp_share"])
        for t in mc["top"][:5]:
            g("netheal_lan_source_pps", "Multicast/broadcast frames per second from one of the top-5 sources.", t["pps"], who=t["who"])


    lines = []
    for name, (help_, vals) in m.items():
        lines += ["# HELP %s %s" % (name, help_), "# TYPE %s gauge" % name] + vals
    tmp = PROM_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, PROM_PATH)


# ---------------------------------------------------------------- capture analysis
SIZES = {0: (8, 8), 1: (1, 1), 2: (1, 1), 3: (2, 4), 4: (2, 2), 5: (1, 1), 6: (1, 1), 7: (2, 2), 8: (2, 2), 9: (2, 2), 10: (1, 1), 11: (1, 1),
         12: (1, 1), 13: (1, 1), 14: (2, 2), 15: (2, 2), 16: (1, 1), 17: (1, 1), 18: (4, 8), 19: (1, 3), 20: (4, 8), 21: (2, 12), 22: (8, 12), 23: (2, 12)}
HE_BASE = [8.6, 17.2, 25.8, 34.4, 51.6, 68.8, 77.4, 86.0, 103.2, 114.7, 129.0, 143.4]
HT_BASE = [6.5, 13.0, 19.5, 26.0, 39.0, 52.0, 58.5, 65.0]
VHT_BASE = [6.5, 13.0, 19.5, 26.0, 39.0, 52.0, 58.5, 65.0, 78.0, 86.7]
BW_F = {0: 1.0, 1: 2.08, 2: 4.2, 3: 8.4}


def parse_rt(p):
    rl = struct.unpack("<H", p[2:4])[0]
    w0 = struct.unpack("<I", p[4:8])[0]
    o, w = 8, w0
    while w & 0x80000000 and o + 4 <= rl:
        w = struct.unpack("<I", p[o:o + 4])[0]
        o += 4
    out = {"rl": rl}
    for bit in range(24):
        if not (w0 >> bit) & 1:
            continue
        al, sz = SIZES[bit]
        o = (o + al - 1) // al * al
        if o + sz > rl:
            break
        d = p[o:o + sz]
        if bit == 0:
            out["tsft"] = struct.unpack("<Q", d)[0]
        elif bit == 2:
            out["rate"] = d[0] * 0.5
        elif bit == 5:
            out["rssi"] = struct.unpack("b", d)[0]
        elif bit == 19:
            out["mcs"] = (d[0], d[1], d[2])
        elif bit == 20:
            out["ampdu"] = struct.unpack("<I", d[:4])[0]
        elif bit == 21:
            out["vht"] = d
        elif bit == 23:
            out["he"] = struct.unpack("<6H", d)
        o += sz
    return out


def rate_and_pre(rt):
    if "he" in rt:
        d = rt["he"]
        mcs, nss, bw, gi = (d[2] >> 8) & 0xF, max(d[5] & 0xF, 1), d[4] & 0xF, (d[4] >> 4) & 3
        return max(HE_BASE[min(mcs, 11)] * BW_F.get(bw, 4.2) * nss * (1.0, 0.9, 0.8, 0.8)[gi], 6.0), 44.0
    if "vht" in rt:
        d = rt["vht"]
        nss, mcs = max(d[4] & 0xF, 1), d[4] >> 4
        return max(VHT_BASE[min(mcs, 9)] * nss * BW_F.get({0: 0, 1: 1, 4: 2, 11: 3}.get(d[3], 2), 4.2), 6.0), 40.0
    if "mcs" in rt:
        _, fl, mcs = rt["mcs"]
        return max(HT_BASE[mcs % 8] * (mcs // 8 + 1) * (2.08 if (fl & 3) == 1 else 1) * (1.11 if fl & 4 else 1), 6.5), 36.0
    if rt.get("rate", 0) > 0:
        return rt["rate"], (192.0 if rt["rate"] <= 11 else 20.0)
    return 24.0, 20.0


def analyze_air(path, namer):
    blob = open(path, "rb").read()
    if len(blob) < 64:
        return {"error": "empty capture"}
    per = defaultdict(lambda: {"f": 0, "r": 0, "air": 0.0})
    node_mc = defaultdict(float)
    beacons = Counter()
    amp = set()
    resp = 0.0
    t0 = t1 = None
    off, nrec = 24, 0
    while off + 16 <= len(blob):
        s, u, incl, orig = struct.unpack("<IIII", blob[off:off + 16])
        off += 16
        p = blob[off:off + incl]
        off += incl
        if len(p) < 12:
            continue
        try:
            rt = parse_rt(p)
        except Exception:  # noqa: BLE001
            continue
        rl = rt["rl"]
        if len(p) < rl + 10:
            continue
        ts = s + u / 1e6
        t0 = ts if t0 is None else t0
        t1 = ts
        nrec += 1
        fc = struct.unpack("<H", p[rl:rl + 2])[0]
        ftype, sub, flags = (fc >> 2) & 3, (fc >> 4) & 15, fc >> 8
        rate, pre = rate_and_pre(rt)
        flen = max(orig - rl, 14)
        if "ampdu" in rt:
            key = (rt["ampdu"], rt.get("tsft", 0) >> 12)
            air = (flen + 4) * 8 / rate
            if key not in amp:
                amp.add(key)
                air += pre
        else:
            air = pre + flen * 8 / rate
        if ftype == 1 and sub in (13, 12):
            resp += air
            continue
        if len(p) < rl + (16 if ftype == 1 else 24):
            continue
        ta = norm_mac(":".join("%02x" % b for b in p[rl + 10:rl + 16]))
        e = per[ta]
        e["f"] += 1
        e["air"] += air
        if ftype in (0, 2) and flags & 8:
            e["r"] += 1
        if ta in NODES:
            if ftype == 0 and sub == 8:
                beacons[ta] += 1
            if ftype == 2 and p[rl + 4] & 1:
                node_mc[ta] += air
    span = max((t1 or 0) - (t0 or 0), 1.0)
    wall = span * 1e6
    top = []
    for m, e in sorted(per.items(), key=lambda kv: -kv[1]["air"])[:6]:
        top.append({"who": namer(m), "mac": m, "air_pct": round(100 * e["air"] / wall, 1), "frames": e["f"],
                    "retry_pct": round(100.0 * e["r"] / max(e["f"], 1), 1)})
    nodes_air = sum(e["air"] for m, e in per.items() if m in NODES)
    non_node = [x for x in per.items() if x[0] not in NODES]
    offenders = [{"who": namer(m), "air_pct": round(100 * e["air"] / wall, 1), "frames": e["f"], "retry_pct": round(100.0 * e["r"] / max(e["f"], 1), 1)}
                 for m, e in non_node if (e["air"] / wall > 0.08 or (e["air"] / wall > 0.03 and e["f"] >= 300 and e["r"] / e["f"] > 0.50))]
    return {"span_s": round(span), "records": nrec,
            "total_air_pct": round(100 * (sum(e["air"] for e in per.values()) + resp) / wall, 1),
            "nodes_air_pct": round(100 * nodes_air / wall, 1),
            "nodes_mc_air_pct": round(100 * sum(node_mc.values()) / wall, 1),
            "responses_pct": round(100 * resp / wall, 1), "top": top, "offenders": offenders,
            "beacons_per_s": {NODES[k]: round(beacons[k] / span, 1) for k in NODES},
            "stations_heard": sum(1 for _, e in non_node if e["f"] >= 20)}


def make_flags(r, prev):
    f = []
    for name in WIRED:
        p = r["ping"].get(name, {})
        if p.get("loss", 0) >= 2:
            f.append("%s ping loss %.0f%%" % (name, p["loss"]))
        elif p.get("avg") is not None and p["avg"] > SLOW_MS.get(name, 8):
            f.append("%s slow: %.1f ms avg" % (name, p["avg"]))
    w = r["ping"].get("WAN 1.1.1.1", {})
    if w.get("loss", 0) >= 2:
        f.append("WAN loss %.0f%%" % w["loss"])
    elif w.get("avg") and w["avg"] > 90:
        f.append("WAN slow: %.0f ms" % w["avg"])
    for k, v in r["dns_ms"].items():
        if v is None:
            f.append("DNS %s no answer" % k)
        elif v > 250:
            f.append("DNS %s slow: %d ms" % (k, v))
    rs = r["router"]
    if rs.get("error"):
        f.append("router status unreachable")
    elif prev.get("router_uptime") is not None and rs.get("uptime") is not None and rs["uptime"] < prev["router_uptime"] - 60:
        f.append("router REBOOTED (uptime %ss)" % rs["uptime"])
    if r["dhcp_offers"] is not None and r["dhcp_offers"] != 1:
        f.append("DHCP answered with %d offers (expected 1)" % r["dhcp_offers"])
    ch = {k: v["chan"] for k, v in r["node_channels"].items()}
    if prev.get("node_channels") and ch and ch != prev["node_channels"]:
        moved = [k for k in ch if prev["node_channels"].get(k) not in (None, ch[k])]
        if moved:
            f.append("radio channel changed: " + ", ".join("%s %s->%s" % (k[-8:], prev["node_channels"][k], ch[k]) for k in moved[:3]))
    if r.get("wired_age_min") is None:
        f.append("HA wired sensor unreadable" + (": " + r["wired_error"] if r.get("wired_error") else ""))
    elif r["wired_age_min"] > 90:
        f.append("HA wired sensor is stale (%d min old)" % r["wired_age_min"])
    mc = r.get("mc", {})
    if mc.get("total_pps", 0) > 60:
        f.append("LAN multicast/broadcast high: %s/s" % mc["total_pps"])
    for t in mc.get("top", []):
        if t["pps"] > 15 and t["who"] != "amd-workstation":  # the workstation's own scans/pings are not a finding
            f.append("broadcast flood: %s %.0f/s" % (t["who"], t["pps"]))
    a = r.get("air", {})
    if a.get("error"):
        f.append("airtime capture failed: " + a["error"])
    else:
        if a.get("total_air_pct", 0) > 55:
            f.append("5 GHz ch149 busy: %.0f%% airtime" % a["total_air_pct"])
        if a.get("nodes_mc_air_pct", 0) > 8:
            f.append("mesh multicast airtime %.1f%% (normal 3-6%%)" % a["nodes_mc_air_pct"])
        for o in a.get("offenders", []):
            f.append("airtime offender: %s %.0f%% air, %.0f%% retries (%d frames)" % (o["who"], o["air_pct"], o["retry_pct"], o["frames"]))
        for name, bps in a.get("beacons_per_s", {}).items():
            if bps < 3:
                f.append("no beacons heard from %s (%.1f/s)" % (name, bps))


    n = r.get("wan", {})
    if n and not n.get("error"):
        if n.get("age_h", 0) > 3:
            f.append("HA Ookla speed test is stale (%.0f h old)" % n["age_h"])
        elif n.get("down", 1e9) < 300 or n.get("up", 1e9) < 300:
            f.append("WAN speed low: %s down / %s up Mbps" % (n.get("down"), n.get("up")))
    return f


def flag_key(text):
    """Stable identity of a flag: the same problem with different numbers must not look like a new problem."""
    t = re.sub(r"-?\d+(?:\.\d+)?\s?(?:%|ms|/s|s)\b", "#", text)
    return re.sub(r"\(\d+ frames\)", "(#)", t)


def new_devices(prev, namer):
    seen = set(prev.get("macs", []))
    now = set(namer.arp.keys())
    new = sorted(now - seen) if seen else []
    return new, sorted(now | seen)


# ---------------------------------------------------------------- main
def collect(parse_only=None):
    os.makedirs(DATA, exist_ok=True)
    state_path = DATA + "/state.json"
    prev = json.load(open(state_path)) if os.path.exists(state_path) else {}
    namer = Namer()
    r = {"ts": int(time.time()), "when": time.strftime("%a %H:%M")}
    if parse_only:
        air_pcap = parse_only[0]
        r.update(ping={}, dns_ms={}, router={}, node_channels={}, dhcp_offers=None, mc={})
    else:
        r["node_channels"] = node_channels()
        wired = ha_wired()
        r["wired_age_min"] = wired.get("age_min")
        r["ping"] = wired.get("ping") or {}
        r["dns_ms"] = wired.get("dns_ms") or {}
        r["router"] = wired.get("router") or {}
        r["dhcp_offers"] = (wired.get("dhcp") or {}).get("offers")
        r["mc"] = name_mc(wired.get("mc") or {}, namer)
        if wired.get("error"):
            r["wired_error"] = wired["error"]
        os.makedirs(RUN, exist_ok=True)
        cmd = ["/usr/bin/docker", "run", "--rm", "--privileged", "--pid=host", "--network=host", "-v", "/:/host", "debian:12",
               "chroot", "/host", "/bin/bash", ROOT_SH, RUN, str(CAP_SECONDS)]
        root = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            root.wait(timeout=CAP_SECONDS + 90)
        except subprocess.TimeoutExpired:
            root.kill()
        air_pcap = RUN + "/air.pcap"
        r["wan"] = ha_ookla()
    try:
        r["air"] = analyze_air(air_pcap, namer)
    except Exception as e:  # noqa: BLE001
        r["air"] = {"error": "parse %s" % str(e)[:50]}
    if os.path.exists(RUN + "/root.log") and "TUNE_FAILED" in open(RUN + "/root.log").read():
        r["air"] = {"error": "monitor interface would not tune to ch149"}
    flags = make_flags(r, prev)
    nd, macs = new_devices(prev, namer)
    r["new_devices"] = [namer(m) for m in nd]
    for m in nd:
        flags.append("new device on the LAN: %s" % namer(m))
    r["flags"] = flags
    if not parse_only:
        with open(DATA + "/hourly.jsonl", "a") as f:
            f.write(json.dumps(r) + "\n")
        try:
            write_prom(r)  # -> node_exporter textfile -> VictoriaMetrics -> Grafana
        except Exception as e:  # noqa: BLE001
            r["prom_error"] = str(e)[:80]
            flags.append("Grafana metrics write failed: " + r["prom_error"])
            r["flags"] = flags
        json.dump({"flags": [flag_key(x) for x in flags], "router_uptime": r["router"].get("uptime"), "node_channels": {k: v["chan"] for k, v in r["node_channels"].items()} or prev.get("node_channels"),
                   "macs": macs, "ts": r["ts"]}, open(state_path, "w"))
        shutil.rmtree(RUN, ignore_errors=True)
    return r, prev


def render(r, full=False):
    L = []
    pg = r["ping"]
    if pg:
        L.append("ping avg/loss: " + ", ".join("%s %s ms/%s%%" % (k, "%.1f" % v["avg"] if v.get("avg") is not None else "-", int(v["loss"])) for k, v in pg.items()))
    a, mc = r.get("air", {}), r.get("mc", {})
    if a and not a.get("error"):
        L.append("5GHz ch149 airtime %s%% (mesh nodes %s%%, node multicast %s%%, ACK/CTS %s%%); %d stations heard" % (
            a["total_air_pct"], a["nodes_air_pct"], a["nodes_mc_air_pct"], a["responses_pct"], a["stations_heard"]))
        L.append("top airtime: " + "; ".join("%s %.0f%% (retry %.0f%%)" % (t["who"], t["air_pct"], t["retry_pct"]) for t in a["top"][:4]))
    elif a:
        L.append("airtime: " + a.get("error", "?"))
    if mc and not mc.get("error"):
        L.append("LAN multicast %s/s (ARP %s%%): " % (mc["total_pps"], mc["arp_share"]) + "; ".join("%s %.1f/s" % (t["who"], t["pps"]) for t in mc["top"][:3]))


    n = r.get("wan") or {}
    if n and not n.get("error"):
        L.append("WAN (HA Ookla, %.1f h old): %s down / %s up Mbps, ping %s ms" % (n.get("age_h", -1), n.get("down"), n.get("up"), n.get("ping")))
    if r.get("router"):
        L.append("router: " + str(r["router"]) + "  DHCP offers: %s  DNS ms: %s" % (r.get("dhcp_offers"), r.get("dns_ms")))
    return L


def summary(r):
    a, mc, n = r.get("air", {}), r.get("mc", {}), r.get("wan", {})
    nodes = [r["ping"][k] for k in ("router .1", "Basement .63", "GameRoom .51", "MainBedroom .99") if k in r["ping"]]
    return {"ts": r["ts"], "when": r["when"], "flags": r["flags"], "nflags": len(r["flags"]),
            "air_total_pct": a.get("total_air_pct"), "air_node_mc_pct": a.get("nodes_mc_air_pct"),
            "lan_mc_pps": mc.get("total_pps"), "ecobee_pps": next((t["pps"] for t in mc.get("top", []) if t["who"] == "ecobee"), 0.0),
            "node_ping_max_ms": max([(x.get("avg") or 0) for x in nodes] or [0]),
            "max_loss_pct": max([v.get("loss", 0) for v in r["ping"].values()] or [0]),
            "dhcp_offers": r.get("dhcp_offers"),
            "wan_down": n.get("down"), "wan_up": n.get("up")}


def main():
    argv = sys.argv[1:]
    if "--json" in argv or (len(argv) == 1 and argv[0] == "run"):
        # Machine mode, used by Home Assistant over a forced-command SSH key. One run at a time.
        import fcntl
        os.makedirs(DATA, exist_ok=True)
        lock = open(DATA + "/run.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(json.dumps({"busy": True, "nflags": None}))
            return
        try:
            r, _ = collect()
            print(json.dumps(summary(r)))
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"error": str(e)[:200], "nflags": None}))
        return
    verbose = "--verbose" in argv
    if "--parse-only" in argv:
        i = argv.index("--parse-only")
        r, prev = collect(parse_only=(argv[i + 1], argv[i + 2]))
        verbose = True
    else:
        r, prev = collect()
    old = set(prev.get("flags", []))
    cur = {flag_key(x): x for x in r["flags"]}
    new = set(cur)
    changed = new != old
    if verbose or changed:
        head = "NETWORK HEALTH %s — %s" % (r["when"], ("%d flag(s)" % len(new)) if new else "all clear")
        lines = [head]
        for k in sorted(new - old):
            lines.append("  NEW: " + cur[k])
        for k in sorted(old - new):
            lines.append("  CLEARED: " + k)
        for k in sorted(new & old):
            lines.append("  still: " + cur[k])
        if verbose or new:
            lines += ["  " + x for x in render(r)]
        print("\n".join(lines))


if __name__ == "__main__":
    main()
