#!/usr/bin/env python3
"""switch_counter_deltas.py -- one session, two counter samples 60 s apart.

Per-port byte deltas over a minute cannot be confused by the 32-bit wrap that
makes whole-uptime volumes ambiguous, so this is how the port map gets verified
against each node's own nic0 byte counters over the same window.

Read-only: two GETs and a sleep, then logout.
"""
import os
import sys
import time

sys.path.insert(0, "/Users/adam.durham/repos/homelab/scripts/network")
os.environ.setdefault("OP_BIOMETRIC_UNLOCK_ENABLED", "true")

import query_netgear as qn  # noqa: E402

OUT = "/tmp/swdelta"
os.makedirs(OUT, exist_ok=True)

with qn.Switch() as sw:
    if not sw.login():
        print("LOGIN FAILED")
        raise SystemExit(1)
    print("login ok")
    a = sw.get("/portStatistics.cgi")
    t_a = time.time()
    open(f"{OUT}/sample_a.html", "w").write(a)
    print(f"sample A at {time.strftime('%H:%M:%S', time.localtime(t_a))} ({len(a)} bytes)")
    time.sleep(60)
    b = sw.get("/portStatistics.cgi")
    t_b = time.time()
    open(f"{OUT}/sample_b.html", "w").write(b)
    print(f"sample B at {time.strftime('%H:%M:%S', time.localtime(t_b))} ({len(b)} bytes)")
    # record the epoch window for the metric comparison
    with open(f"{OUT}/window.txt", "w") as fh:
        fh.write(f"{t_a}\n{t_b}\n")
    print(f"window: {t_b - t_a:.1f} s")
