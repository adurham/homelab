#!/usr/bin/env python3
"""switch_read_more.py -- one extra read-only visit to the GS108Ev4.

Fetches the pages the standard dump does not cover (per-port statistics, VLAN,
QoS, system) in a SINGLE session, then logs out. The switch allows only a few
concurrent sessions and wedges if the login endpoint is hammered, so this is
deliberately a one-shot: run it, read the files, do not loop it.

Reuses the login/logout flow in scripts/network/query_netgear.py.
"""
import os
import sys

sys.path.insert(0, "/Users/adam.durham/repos/homelab/scripts/network")
os.environ.setdefault("OP_BIOMETRIC_UNLOCK_ENABLED", "true")

import query_netgear as qn  # noqa: E402

PAGES = ["/dashboard.cgi", "/portStatistics.cgi", "/vlanConfig.cgi", "/vlanMembership.cgi",
         "/qos.cgi", "/system.cgi", "/management.cgi", "/switching.cgi"]

with qn.Switch() as sw:
    if not sw.login():
        print("login failed")
        raise SystemExit(1)
    for page in PAGES:
        try:
            html = sw.get(page)
        except Exception as e:  # noqa: BLE001
            print(f"{page}: {type(e).__name__}: {str(e)[:70]}")
            continue
        name = page.strip("/").replace(".cgi", "")
        path = f"/tmp/sw_{name}.html"
        with open(path, "w") as fh:
            fh.write(html)
        print(f"{page}: {len(html)} bytes -> {path}")
