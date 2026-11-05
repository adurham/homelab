#!/usr/bin/env python3
"""Mirror the chi.lab.amd-e.com BIND zone into AdGuard Home DNS rewrites.

WHY THIS EXISTS
---------------
AdGuard Home on the HA box (192.168.86.2) is the resolver every LAN client's
DHCP option 6 names, and Tailscale split-DNS forwards chi.lab.amd-e.com to it
too. It does NOT have a per-domain upstream into the private SDN any more: the
HA host has no route to 172.16.0.0/24, so `[/chi.lab.amd-e.com/]172.16.0.10`
hung for the full upstream timeout and stalled every lab lookup (2026-11-05).

The supported mechanism is therefore one DNS rewrite per lab hostname. That
means the zone exists in TWO places (dns-01's BIND zone and AdGuard's rewrite
table) and they drift silently: on 2026-11-05 the upstream was removed and only
`printbot` + `dns` were re-added as rewrites, so gallery.chi.lab.amd-e.com and
33 other lab names answered NXDOMAIN for every LAN and tailnet client. Safari
showed "can't find the server" while the service behind lb-01 was healthy.

Run this after any dns_server role deploy, and from cron --check if you want
drift to be visible early.

USAGE
-----
  adguard_zone_mirror.py                 # reconcile (adds missing / fixes changed)
  adguard_zone_mirror.py --check         # report drift, exit 1 if any
  adguard_zone_mirror.py --dry-run       # print what would change

ENV
---
  AGH_API      default http://100.77.245.39:45158  (tailnet forwarder into the
               host-networked Advanced SSH app; see home-lan-dhcp-and-dns-control)
  DNS_PRIMARY  default 172.16.0.10 (dns-01, the authoritative zone holder)
  ZONE         default chi.lab.amd-e.com

This script never deletes a rewrite and never touches /control/dns_config
(which rebinds the listeners on the P0 resolver). It only calls
/control/rewrite/{list,add,delete} and /control/cache_clear.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

AGH_API = os.environ.get("AGH_API", "http://100.77.245.39:45158").rstrip("/")
DNS_PRIMARY = os.environ.get("DNS_PRIMARY", "172.16.0.10")
ZONE = os.environ.get("ZONE", "chi.lab.amd-e.com")

# Names whose AdGuard answer is deliberately NOT the BIND answer.
OVERRIDES = {
    # dns.chi.lab is the DoT/DoH endpoint served by AdGuard itself, so it must
    # point at the HA box, not at dns-01.
    "dns." + ZONE: "192.168.86.2",
}

# Non-zone rewrites that live in the same table and must never be reported as
# drift (Apple MDM blocks).
IGNORE_SUFFIXES = ("apple.com",)


def _api(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        AGH_API + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode().strip()
    return json.loads(raw) if raw else None


def zone_records() -> dict[str, str]:
    """A records from dns-01 via AXFR. name -> address."""
    out = subprocess.run(
        ["dig", "@" + DNS_PRIMARY, ZONE, "AXFR", "+time=5", "+tries=1"],
        capture_output=True, text=True, timeout=30,
    ).stdout
    records: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        fields = re.split(r"\s+", line)
        if len(fields) < 5 or fields[3] != "A":
            continue
        name = fields[0].rstrip(".").lower()
        if name.endswith("." + ZONE) or name == ZONE:
            records[name] = fields[4]
    if not records:
        raise SystemExit(f"AXFR from {DNS_PRIMARY} for {ZONE} returned no A records")
    return records


def current_rewrites() -> dict[str, str]:
    rows = _api("GET", "/control/rewrite/list") or []
    return {r["domain"].lower(): r["answer"] for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report drift, exit 1")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args()

    desired = dict(zone_records())
    desired.update(OVERRIDES)
    have = current_rewrites()

    missing = {d: ip for d, ip in desired.items() if d not in have}
    changed = {d: (have[d], ip) for d, ip in desired.items()
               if d in have and have[d] != ip}

    print(f"zone={ZONE} dns={DNS_PRIMARY} agh={AGH_API}")
    print(f"desired={len(desired)} present={len(have)} "
          f"missing={len(missing)} changed={len(changed)}")
    for d, ip in sorted(missing.items()):
        print(f"  MISSING {d} -> {ip}")
    for d, (old, new) in sorted(changed.items()):
        print(f"  CHANGED {d}: {old} -> {new}")

    orphans = sorted(set(have) - set(desired))
    orphans = [o for o in orphans if not o.endswith(IGNORE_SUFFIXES)]
    if orphans:
        print(f"  (note) {len(orphans)} rewrite(s) not in the zone, left alone:")
        for o in orphans:
            print(f"    {o} -> {have[o]}")

    if args.check:
        return 1 if (missing or changed) else 0
    if args.dry_run or not (missing or changed):
        return 0

    for d, ip in missing.items():
        _api("POST", "/control/rewrite/add", {"domain": d, "answer": ip})
    for d, (old, new) in changed.items():
        _api("POST", "/control/rewrite/delete", {"domain": d, "answer": old})
        _api("POST", "/control/rewrite/add", {"domain": d, "answer": new})
    # NXDOMAIN/old answers stay in the resolver cache until it is cleared.
    _api("POST", "/control/cache_clear", {})

    after = current_rewrites()
    bad = [d for d, ip in desired.items() if after.get(d) != ip]
    print(f"reconciled: {len(missing)} added, {len(changed)} fixed, "
          f"verified {len(desired) - len(bad)}/{len(desired)}")
    if bad:
        print("STILL WRONG: " + ", ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
