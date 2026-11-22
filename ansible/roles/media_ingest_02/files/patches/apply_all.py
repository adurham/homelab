#!/usr/bin/env python3
"""Apply the ofscraper local patches (idempotent wrapper).

OnlyFans' current frontend rejects replayed sessions, so the scraper's API calls
have to run inside the logged-in browser via a CDP shim. These patches add:
  * x-of-rev to the auth headers
  * x-bc / x-hash from the lifted browser values (CDN fallback)
  * shim routing for async (_aio_funct) and sync (_httpx_funct) requests
Each step is a separate script that first checks whether its change is already
present, so re-running this is safe.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PY = "/opt/media-ingest-02/venv/bin/python"
STEPS = [
    "patch_cdn.py",          # CDN token helpers + x-of-rev
    "patch_bc_pref.py",      # prefer the lifted device key over a fresh CDN one
    "patch_shim.py",         # async shim response + routing
    "patch_shim2.py",        # url/method on the shim response
    "patch_shim3.py",        # raise_for_status
    "patch_shim_sync.py",    # sync shim response + routing
]

for step in STEPS:
    r = subprocess.run([sys.executable, str(HERE / step)], capture_output=True, text=True)
    ok = r.returncode == 0
    print(("ok   " if ok else "FAIL ") + step + " :: " + (r.stdout or r.stderr).strip()[:160])
    if not ok:
        sys.exit(1)
print("ofscraper patches complete")
