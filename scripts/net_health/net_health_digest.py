#!/usr/bin/env python3
"""Daily digest of the hourly Wi-Fi/LAN health log (no LLM). Prints a compact summary of the last 24 h."""
import json
import os
import statistics as st
import time
from collections import Counter

LOG = os.path.expanduser("~/.hermes/cache/net-health/hourly.jsonl")
rows = []
if os.path.exists(LOG):
    for ln in open(LOG):
        try:
            rows.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            pass
cut = time.time() - 24 * 3600
day = [r for r in rows if r["ts"] >= cut]
if not day:
    print("NETWORK HEALTH DAILY: no hourly runs in the last 24 h (collector not running?)")
    raise SystemExit


def col(f):
    out = []
    for r in day:
        try:
            v = f(r)
        except Exception:  # noqa: BLE001
            v = None
        if v is not None:
            out.append(v)
    return out


def rng(vals, fmt="%.1f"):
    if not vals:
        return "n/a"
    return ("min " + fmt + " / median " + fmt + " / max " + fmt) % (min(vals), st.median(vals), max(vals))


flags = Counter(f for r in day for f in r.get("flags", []))
print("NETWORK HEALTH DAILY — %d hourly checks (%s to %s)" % (len(day), time.strftime("%a %H:%M", time.localtime(day[0]["ts"])), time.strftime("%a %H:%M", time.localtime(day[-1]["ts"]))))
print("flags raised (hours seen): " + ("; ".join("%s (%dx)" % (k, v) for k, v in flags.most_common(8)) if flags else "none"))
print("wired nodes ping avg ms : " + rng(col(lambda r: max(r["ping"][k]["avg"] for k in ("router .1", "Basement .63", "GameRoom .51", "MainBedroom .99")))))
print("worst packet loss %     : " + rng(col(lambda r: max(v["loss"] for v in r["ping"].values())), "%.0f"))
print("WAN ping avg ms         : " + rng(col(lambda r: r["ping"]["WAN 1.1.1.1"]["avg"])))
print("DNS query ms            : " + rng(col(lambda r: max(v for v in r["dns_ms"].values() if v is not None)), "%.0f"))
print("5GHz ch149 airtime %    : " + rng(col(lambda r: r["air"]["total_air_pct"])))
print("node multicast airtime %: " + rng(col(lambda r: r["air"]["nodes_mc_air_pct"])))
print("LAN multicast pps       : " + rng(col(lambda r: r["mc"]["total_pps"])))
print("ecobee broadcasts/s     : " + rng(col(lambda r: next((t["pps"] for t in r["mc"]["top"] if t["who"] == "ecobee"), 0.0))))
print("Wi-Fi throughput down   : " + rng(col(lambda r: r["wifi"]["down"]), "%.0f") + " Mbps   up: " + rng(col(lambda r: r["wifi"]["up"]), "%.0f") + " Mbps   tests: %d" % len(col(lambda r: r["wifi"]["down"])))
print("WAN (HA Ookla) down/up  : " + rng(col(lambda r: r["wan"]["down"]), "%.0f") + " / " + rng(col(lambda r: r["wan"]["up"]), "%.0f") + " Mbps")
print("MacBook ping p90 ms     : " + rng(col(lambda r: r["mac"]["avg_p90"])) + "   hours with data: %d" % len(col(lambda r: r["mac"].get("avg_p90"))))
bands = Counter()
for r in day:
    for k, v in (r.get("mac") or {}).get("bands", {}).items():
        bands[k] += v
print("MacBook band mix (samples): " + (", ".join("%s %d" % kv for kv in bands.most_common()) if bands else "none"))
top = Counter()
for r in day:
    for t in (r.get("air") or {}).get("top", [])[:5]:
        if "pt" not in t["who"] and "router" not in t["who"]:
            top[t["who"]] += 1
print("recurring top-5 airtime clients: " + ("; ".join("%s (%dh)" % kv for kv in top.most_common(5)) if top else "none"))
mcsrc = Counter()
for r in day:
    for t in (r.get("mc") or {}).get("top", [])[:3]:
        mcsrc[t["who"]] += 1
print("recurring top-3 broadcast sources: " + "; ".join("%s (%dh)" % kv for kv in mcsrc.most_common(5)))
newd = [d for r in day for d in r.get("new_devices", [])]
print("new devices seen: " + (", ".join(newd) if newd else "none"))
reb = [r for r in day if any("REBOOTED" in f for f in r.get("flags", []))]
print("router reboots: %d" % len(reb))
worst = sorted(day, key=lambda r: -(r.get("air", {}).get("total_air_pct") or 0))[:2]
print("busiest hours: " + "; ".join("%s %.0f%%" % (r["when"], r["air"]["total_air_pct"]) for r in worst if r.get("air", {}).get("total_air_pct") is not None))
