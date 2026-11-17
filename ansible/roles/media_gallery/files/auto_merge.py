#!/usr/bin/env python3
"""Materialize free/VIP folder pairs into the merges ledger — SERVER side.

A model is often ingested twice: a public feed and a paid one, so the library
holds two folders for the same person ("gemmajae"/"gemmajaevip",
"vip_emilyryder69"/"emilyryder69", "kyokocosplaysfree"/"kyokocosplay"). The
gallery shows those as one merged folder, and that grouping is STATE ABOUT THE
LIBRARY, so it belongs here rather than in the browser: a client with a stale
folder list would compute a different answer, and nothing would exist at all
while no page was open.

Runs as step 3 of refresh_gallery.sh (hourly, inside the job flock). It reads the
authoritative folder list and POSTs the resulting groups to the upload service,
which is the ONLY writer of /var/lib/media-gallery/folder_groups.json — this
script never edits that file, so it cannot fight the SPA's own writes.

Rules (conservative; the SPA keeps `isAutoGroup`/adoption to stay compatible):
  * a base needs >= 2 folders and at least one must carry a free/vip marker
    (free, vip, vipp, freepage, freeonly, viponly — leading or trailing,
    separator optional);
  * a plain folder within 2 characters that is a prefix of the stripped base
    also pairs ("chanxoxo-free"/"chanxoxos", "kyokocosplaysfree"/"kyokocosplay");
  * a folder already in a hand-made merge is never taken;
  * a dismissed pair (a tombstone with id `auto:<base>`) is never recreated;
  * an auto group whose members fall below two is dissolved, so no card can
    name a folder that is gone.

Idempotent: when the computed list matches what the server holds, nothing is
written. `--dry-run` prints the resulting auto groups without POSTing.

Env: TG_SERVE_DIR (folder list), TG_UPLOAD_URL (upload service base URL).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

SERVE_DIR = Path(os.environ.get("TG_SERVE_DIR", "/var/lib/media-gallery/serve/gallery"))
UPLOAD_URL = os.environ.get("TG_UPLOAD_URL", "http://172.16.0.46:8092").rstrip("/")
AUTO_PREFIX = "auto:"
MARKER_RE = re.compile(r"^(.*?)[-_.\s]*(freepage|freeonly|free|viponly|vipp|vip)$")
LEAD_RE = re.compile(r"^(freepage|freeonly|free|viponly|vipp|vip)[-_.\s]+(.+)$")


def auto_base(name):
    """(base, carried_marker) for a folder name."""
    s = str(name or "").strip().lower()
    hit = False
    m = MARKER_RE.match(s)
    if m and m.group(1) and len(m.group(1)) > 1:
        s, hit = m.group(1), True
    else:
        m = LEAD_RE.match(s)
        if m and m.group(2):
            s, hit = m.group(2), True
    return s.rstrip("-_ ."), hit


def is_auto(g):
    return isinstance(g, dict) and str(g.get("id", "")).startswith(AUTO_PREFIX)


def auto_name(base, members):
    """Prefer a plain member's name, then a folder literally named like the base."""
    for m in members:
        if not auto_base(m)[1]:
            return m
    for m in members:
        if m.lower() == base:
            return m
    return base


def pair_bases(folders):
    """{base: [folder, ...]} for every base that has a free/vip-marked member."""
    seen = list(dict.fromkeys(str(f) for f in folders if f))
    bases = {}
    for n in seen:
        b, hit = auto_base(n)
        if hit and b:
            bases.setdefault(b, []).append(n)
    low = {n.lower(): n for n in seen}
    for b, members in bases.items():
        p = low.get(b)
        if p and p not in members:
            members.append(p)          # the plain folder itself
    plain = {n.lower(): n for n in seen if not auto_base(n)[1]}
    for b in sorted(bases):
        if len(bases[b]) >= 2:
            continue
        best = ""
        for pl in plain:
            if pl == b or abs(len(pl) - len(b)) > 2:
                continue
            if not (pl.startswith(b) or b.startswith(pl)):
                continue
            if not best or abs(len(pl) - len(b)) < abs(len(best) - len(b)):
                best = pl
        if best:
            bases[b].append(plain.pop(best))
    return bases


def derive(groups, folders):
    """Return the merged ledger list. Pure: no I/O, easy to test."""
    groups = [g for g in (groups or []) if isinstance(g, dict) and g.get("id")]
    bases = pair_bases(folders)
    claimed = set()
    tomb = set()
    for g in groups:
        if g.get("del"):
            tomb.add(g["id"])
        elif not is_auto(g):
            claimed.update(str(n) for n in (g.get("folders") or []))
    out = []
    existing = {}
    for g in groups:
        if is_auto(g) and not g.get("del"):
            existing[g["id"]] = g
        else:
            out.append(g)
    now = int(time.time() * 1000)
    for b in sorted(bases):
        gid = AUTO_PREFIX + b
        live = existing.pop(gid, None)
        if gid in tomb:
            if live:                                   # a live group on a dismissed
                out.append({**live, "del": 1, "ts": now})   # pair: retire it
            continue
        members = [n for n in bases[b] if n not in claimed]
        members = sorted(dict.fromkeys(members))
        if len(members) < 2:
            if live:
                out.append({**live, "del": 1, "ts": now})
            continue
        name = auto_name(b, members)
        if live is None:
            out.append({"id": gid, "name": name, "folders": members, "ts": now, "auto": 1})
        elif sorted(str(x) for x in (live.get("folders") or [])) != members:
            out.append({**live, "folders": members, "ts": now, "auto": 1})
        else:
            out.append(live)
    for gid, live in existing.items():                 # base disappeared entirely
        out.append({**live, "del": 1, "ts": now})
    out.sort(key=lambda g: (int(g.get("ts") or 0), str(g.get("id"))))
    return out


def http_json(url, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--folders", default="", help="folder list JSON (default: serve dir)")
    ap.add_argument("--ledger", default="", help="ledger JSON instead of GET /merges")
    a = ap.parse_args()

    if a.folders:
        folders = json.loads(Path(a.folders).read_text())
    else:
        src = SERVE_DIR / "folders.json"
        if not src.exists():                      # tmpfs empty before the first
            print("auto_merge: %s not published yet — skipped" % src)   # refresh
            return 0
        folders = json.loads(src.read_text())
    if not isinstance(folders, list):
        print("auto_merge: folder list is not a list — skipped")
        return 1

    if a.ledger:
        ledger = json.loads(Path(a.ledger).read_text())
    else:
        ledger = http_json(UPLOAD_URL + "/merges?ts=" + str(int(time.time() * 1000)))
    groups = ledger.get("groups") or []
    new = derive(groups, folders)

    def sig(gs):
        return sorted((g.get("id"), int(g.get("ts") or 0), bool(g.get("del")),
                       tuple(sorted(g.get("folders") or [])))
                      for g in gs if isinstance(g, dict))

    live = [g for g in new if not g.get("del") and is_auto(g)]
    print("auto_merge: %d folders, %d derived merges, %d groups in ledger"
          % (len(folders), len(live), len(new)))
    for g in live:
        print("  %-24s <- %s" % (g.get("id"), " + ".join(g.get("folders") or [])))
    if sig(new) == sig(groups):
        print("auto_merge: no change")
        return 0
    if a.dry_run:
        print("auto_merge: --dry-run, nothing written")
        return 0
    body = {"groups": new}
    if isinstance(ledger.get("auto"), bool):
        body["auto"] = ledger["auto"]
    res = http_json(UPLOAD_URL + "/merges", body)
    print("auto_merge: saved %s" % json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
