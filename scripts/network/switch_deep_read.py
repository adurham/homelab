#!/usr/bin/env python3
"""switch_deep_read.py -- ONE login on the GS108Ev4 that answers everything left:
the shell page, the app JS (to find the real counter endpoint), the per-port
counters themselves, storm control, and system/uptime.

The switch holds very few HTTP sessions and wedges if the login endpoint is
hammered, so everything happens inside one Switch() session that logs out at the
end. Nothing is written to the switch; all requests are GETs.
"""
import os
import re
import sys

sys.path.insert(0, "/Users/adam.durham/repos/homelab/scripts/network")
os.environ.setdefault("OP_BIOMETRIC_UNLOCK_ENABLED", "true")

import query_netgear as qn  # noqa: E402

OUT = "/tmp/swdeep"
os.makedirs(OUT, exist_ok=True)

def save(name, text):
    with open(f"{OUT}/{name}", "w") as fh:
        fh.write(text)
    return len(text)

PAGES = ["/index.cgi", "/dashboard.cgi", "/portStatistics.cgi", "/stromControl.cgi",
         "/system.cgi", "/mgmt.cgi", "/admin.cgi", "/info.cgi", "/deviceInfo.cgi"]

with qn.Switch() as sw:
    if not sw.login():
        print("LOGIN FAILED")
        raise SystemExit(1)
    print("login ok")
    scripts = set()
    for page in PAGES:
        try:
            html = sw.get(page)
        except Exception as e:  # noqa: BLE001
            print(f"{page:24} {type(e).__name__}: {str(e)[:60]}")
            continue
        n = save(page.strip('/').replace('.cgi', '') + ".html", html)
        print(f"{page:24} {n:7} bytes")
        for src in re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', html):
            scripts.add(src)

    print("\nJS referenced by those pages:", sorted(scripts))
    for src in sorted(scripts):
        path = src if src.startswith("/") else "/" + src
        try:
            js = sw.get(path)
        except Exception as e:  # noqa: BLE001
            print(f"  {path:28} {type(e).__name__}: {str(e)[:50]}")
            continue
        save("js_" + path.strip("/").replace("/", "_"), js)
        hits = sorted(set(re.findall(r'["\']([/A-Za-z0-9_\-]+\.cgi[^"\']*)["\']', js)))
        print(f"  {path:28} {len(js):7} bytes  endpoints: {hits[:10]}")
        for kw in ("portStatistics", "showCounter", "getCounter", "counter"):
            if kw.lower() in js.lower():
                idx = js.lower().find(kw.lower())
                print(f"      ~ {kw}: ...{js[max(0, idx-90):idx+110]}...".replace("\n", " ")[:220])
