#!/usr/bin/env python3
"""switch_cable_test.py -- run the GS108Ev4's own cable diagnostics on ports 1-4.

Ports 1 and 2 are the verified ports of the two nodes that stall (pve01, pve02);
ports 3 and 4 are the candidate ports for pve03. The switch's diagnostics judge
each cable pair, which is the evidence needed before anyone moves a cable.

Contract (recovered from the firmware's own JS):
    POST /cableTester.cgi   hash=<page hash>&port0=checked&port1=checked&...
    -> body "SUCCESS" (or "CHECK HASH FAILED"); results appear ~11 s later as a
       plain GET of the same URL.

Also samples the per-port counters either side of the test, so the same run
yields port->node deltas AND cable quality. One session, one logout.
"""
import os
import re
import sys
import time

sys.path.insert(0, "/Users/adam.durham/repos/homelab/scripts/network")
os.environ.setdefault("OP_BIOMETRIC_UNLOCK_ENABLED", "true")

import query_netgear as qn  # noqa: E402

OUT = "/tmp/swcable"
os.makedirs(OUT, exist_ok=True)
PORTS = [0, 1, 2, 3]  # zero-based: ports 1,2,3,4 on the front panel

with qn.Switch() as sw:
    # ONE attempt, no retry loop: the switch's session table is the thing this
    # investigation already strained, and a retry burst against it risks wedging
    # the management CGI for real (documented pitfall). If this attempt reports
    # full slots, the correct move is to back off and report, not to loop.
    if not sw.login(attempts=1, wait=0):
        print("LOGIN FAILED")
        raise SystemExit(1)
    print("login ok")

    a = sw.get("/portStatistics.cgi")
    t_a = time.time()
    open(f"{OUT}/counters_before.html", "w").write(a)
    print(f"counters A at {time.strftime('%H:%M:%S')}")

    page = sw.get("/cableTester.cgi")
    m = re.search(r"name=['\"]hash['\"][^>]*value=['\"]?([0-9a-fA-F]+)", page)
    if not m:
        m = re.search(r"id=['\"]hash['\"][^>]*value=['\"]?([0-9a-fA-F]+)", page)
    if not m:
        print("no hash field on the cable tester page; head:", page[:300])
        raise SystemExit(1)
    data = {"hash": m.group(1)}
    for p in PORTS:
        data[f"port{p}"] = "checked"
    print("triggering cable test for ports:", [p + 1 for p in PORTS])
    resp = sw.get("/cableTester.cgi", data=data)
    print("POST response:", resp.strip()[:120])

    time.sleep(12)
    results = sw.get("/cableTester.cgi")
    open(f"{OUT}/results.html", "w").write(results)
    print(f"results: {len(results)} bytes -> {OUT}/results.html")

    b = sw.get("/portStatistics.cgi")
    t_b = time.time()
    open(f"{OUT}/counters_after.html", "w").write(b)
    with open(f"{OUT}/window.txt", "w") as fh:
        fh.write(f"{t_a}\n{t_b}\n")
    print(f"counters B at {time.strftime('%H:%M:%S')} (delta window {t_b - t_a:.1f} s)")

    try:
        qn.show_sysinfo(sw)
    except Exception as e:  # noqa: BLE001
        print("sysinfo failed:", str(e)[:80])
