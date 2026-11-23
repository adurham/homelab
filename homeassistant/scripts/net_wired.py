#!/usr/bin/env python3
"""Wired-network health probes, run INSIDE Home Assistant Core (python3 + host network on .2).

Owner's rule: every physically-cabled measurement runs on the HA box; the workstation is only
allowed to measure Wi-Fi. This script measures, from the HA host's own LAN interface:

  * ICMP loss / latency to the four mesh nodes, the AT&T gateway, both LAN resolvers and the WAN
  * DNS query time against both AdGuard resolvers (raw UDP, no dig needed)
  * the Nest router's own status API (uptime = reboot detector, mesh channel, WAN state)
  * one real DHCP DISCOVER, counting offers (0 = dead pair, 2+ = rogue server)
  * a wired Ethernet multicast/broadcast census (top sources, ARP share)

Prints one JSON object. No third-party modules: it must run on the HA Core image as-is.
Usage: net_wired.py [--json]     (any argv; the command_line sensor just runs it)
"""
import json
import os
import random
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.request

PING_TARGETS = {
    "router .1": "192.168.86.1", "Basement .63": "192.168.86.63", "GameRoom .51": "192.168.86.51",
    "MainBedroom .99": "192.168.86.99", "AT&T gw": "192.168.1.254", "WAN 1.1.1.1": "1.1.1.1",
    "DNS .4": "192.168.86.4", "DNS .5": "192.168.86.5",
}
MCAST_SECONDS = 45


def _default_iface():
    try:
        out = subprocess.run(["ip", "-o", "-4", "route", "show", "default"], capture_output=True, text=True, timeout=5).stdout
        return out.split()[4] if out.split() else None
    except Exception:  # noqa: BLE001
        return None


def sh(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except Exception as e:  # noqa: BLE001
        return "ERR %s" % e


# ---------------------------------------------------------------- ICMP
def ping_stats(host, count=20):
    """busybox and iputils both print min/avg/max (iputils adds stddev)."""
    out = sh(["ping", "-c", str(count), "-i", "0.2", "-W", "1", host], timeout=40)
    m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", out)
    if not m:
        return {"loss": 100.0, "avg": None, "max": None, "error": out.strip().splitlines()[-1][:60] if out.strip() else "ping failed"}
    tx, rx = int(m.group(1)), int(m.group(2))
    loss = 100.0 * (tx - rx) / max(tx, 1)
    r = re.search(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)(?:/[\d.]+)?\s*ms", out)
    return {"loss": round(loss, 1), "avg": float(r.group(2)) if r else None, "max": float(r.group(3)) if r else None}


# ---------------------------------------------------------------- DNS
def _dns_query(name, server, timeout=3):
    """One A query over UDP; returns milliseconds or None. Raw so no dig/nslookup is required."""
    tid = random.randint(0, 0xFFFF)
    q = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    for label in name.split("."):
        q += bytes([len(label)]) + label.encode()
    q += b"\x00" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    t0 = time.time()
    try:
        s.sendto(q, (server, 53))
        while True:
            data, _ = s.recvfrom(1024)
            if len(data) >= 12 and struct.unpack(">H", data[:2])[0] == tid:
                return int(round((time.time() - t0) * 1000))
    except Exception:  # noqa: BLE001
        return None
    finally:
        s.close()


def dns_ms(server):
    # a name the resolver has never seen: an authoritative answer cannot come from cache
    return _dns_query("nh%d.example.com" % int(time.time() * 1000 % 100000), server)


# ---------------------------------------------------------------- router
def router_status():
    try:
        d = json.load(urllib.request.urlopen("http://192.168.86.1/api/v1/status", timeout=5))
        return {"uptime": d.get("system", {}).get("uptime"), "mesh_channel": d.get("meshInfo", {}).get("mesh-channel"),
                "wan_online": d.get("wan", {}).get("online")}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:60]}


# ---------------------------------------------------------------- DHCP
def dhcp_discover(seconds=8):
    """A real DISCOVER from :68, counting OFFERs. Needs root (port 68) but no client state is kept."""
    xid = random.randint(1, 0xFFFFFFFF)
    mac = [0x02, 0x00, 0x00, 0xDE, 0xAD, random.randint(1, 0xFE)]   # locally administered, throwaway
    pkt = struct.pack("!BBBBIHH", 1, 1, 6, 0, xid, 0, 0x8000) + b"\x00" * 16
    pkt += bytes(mac) + b"\x00" * 10 + b"\x00" * 64 + b"\x00" * 128
    pkt += b"\x63\x82\x53\x63"                                       # magic cookie
    pkt += bytes([53, 1, 1])                                         # DHCPDISCOVER
    pkt += bytes([55, 4, 1, 3, 6, 15])                               # param request list
    pkt += bytes([12, 6]) + b"hermes" + bytes([255])
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    offers, servers = 0, set()
    try:
        s.bind(("0.0.0.0", 68))
    except Exception as e:  # noqa: BLE001
        return {"offers": None, "error": "bind :68 failed: %s" % str(e)[:50]}
    try:
        s.sendto(pkt, ("255.255.255.255", 67))
        deadline = time.time() + seconds
        while time.time() < deadline:
            s.settimeout(max(0.2, deadline - time.time()))
            try:
                data, _ = s.recvfrom(2048)
            except socket.timeout:
                break
            if len(data) < 240 or struct.unpack("!I", data[4:8])[0] != xid:
                continue
            opts, i = data[240:], 0
            msg_type = None
            while i < len(opts):
                if opts[i] == 255:
                    break
                if opts[i] == 0:
                    i += 1
                    continue
                code, ln = opts[i], opts[i + 1]
                val = opts[i + 2:i + 2 + ln]
                if code == 53 and ln >= 1:
                    msg_type = val[0]
                if code == 54 and ln >= 4:          # server identifier
                    servers.add(".".join(str(b) for b in val[:4]))
                i += 2 + ln
            if msg_type == 2:
                offers += 1
    finally:
        s.close()
    return {"offers": offers, "servers": sorted(servers)}


# ---------------------------------------------------------------- multicast census
def mcast_census(iface, seconds=MCAST_SECONDS):
    """Ethernet multicast/broadcast seen on the wired NIC, counted per source, no privileges beyond NET_RAW."""
    try:
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(3))
        s.bind((iface, 0))
        s.settimeout(1.0)
    except Exception as e:  # noqa: BLE001
        return {"error": "raw socket failed: %s" % str(e)[:60]}
    src = {}
    frames = arp = 0
    t_end = time.time() + seconds
    try:
        while time.time() < t_end:
            try:
                frame, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            if len(frame) < 14:
                continue
            if not (frame[0] & 1):
                continue
            frames += 1
            sa = ":".join("%02x" % b for b in frame[6:12])
            src[sa] = src.get(sa, 0) + 1
            if frame[12:14] == b"\x08\x06":
                arp += 1
    finally:
        s.close()
    span = max(seconds, 1)
    top = sorted(src.items(), key=lambda kv: -kv[1])[:5]
    return {"span_s": seconds, "total_pps": round(frames / span, 1), "arp_share": int(100 * arp / frames) if frames else 0,
            "top": [{"mac": m, "pps": round(c / span, 1)} for m, c in top]}


# ---------------------------------------------------------------- main
def collect():
    iface = os.environ.get("NET_WIRED_IFACE") or _default_iface()
    r = {"ts": int(time.time()), "iface": iface}
    r["ping"] = {k: ping_stats(v) for k, v in PING_TARGETS.items()}
    r["dns_ms"] = {"DNS .4": dns_ms("192.168.86.4"), "DNS .5": dns_ms("192.168.86.5")}
    r["router"] = router_status()
    r["dhcp"] = dhcp_discover()
    r["mc"] = mcast_census(iface) if iface else {"error": "no default-route interface"}
    return r


if __name__ == "__main__":
    out = collect()
    print(json.dumps(out))
