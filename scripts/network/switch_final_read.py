#!/usr/bin/env python3
"""switch_final_read.py -- one last read-only visit to the GS108Ev4.

Fetches, in a single session: the per-port counters again (to see whether the
earlier all-zero render was a fluke), the port status page, the cable-tester
results page (results only -- the test itself is not triggered here, since a
cable test can bounce a live link), the broadcast/storm-control page, IGMP
multicast state, and the settings page (for system info/uptime).

Nothing is written; every request is a GET; the session logs out at the end.
"""
import os
import sys

sys.path.insert(0, "/Users/adam.durham/repos/homelab/scripts/network")
os.environ.setdefault("OP_BIOMETRIC_UNLOCK_ENABLED", "true")

import query_netgear as qn  # noqa: E402

OUT = "/tmp/swfinal"
os.makedirs(OUT, exist_ok=True)

PAGES = ["/portStatistics.cgi", "/port_status.cgi", "/cableTester.cgi",
         "/broadCastFilter.cgi", "/multicast.cgi", "/settings.cgi",
         "/green_ethernet.cgi", "/switchDiscovery.cgi"]

with qn.Switch() as sw:
    if not sw.login():
        print("LOGIN FAILED")
        raise SystemExit(1)
    print("login ok")
    for page in PAGES:
        try:
            html = sw.get(page)
        except Exception as e:  # noqa: BLE001
            print(f"{page:24} {type(e).__name__}: {str(e)[:60]}")
            continue
        name = page.strip("/").replace(".cgi", "") + ".html"
        with open(f"{OUT}/{name}", "w") as fh:
            fh.write(html)
        print(f"{page:24} {len(html):7} bytes -> {OUT}/{name}")
