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
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

SERVE_DIR = Path(os.environ.get("TG_SERVE_DIR", "/var/lib/media-gallery/serve/gallery"))
PROFILES_FILE = Path(os.environ.get("TG_PROFILES_FILE", "/var/lib/media-gallery/source_profiles.json"))
UPLOAD_URL = os.environ.get("TG_UPLOAD_URL", "http://172.16.0.46:8092").rstrip("/")
AUTO_PREFIX = "auto:"
ID_PREFIX = "id:"          # id-based groups are keyed "auto:id:<hash>"
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


def load_profiles(path=None):
    """{folder: {source_id, name, avatar, mentions, price}} written by the scraper lane."""
    p = Path(path) if path else PROFILES_FILE
    try:
        d = json.loads(p.read_text())
        prof = d.get("profiles", d) if isinstance(d, dict) else {}
        return prof if isinstance(prof, dict) else {}
    except (OSError, ValueError):
        return {}


def identity_bases(folders, profiles):
    """Pairs proven by the ACCOUNT PROFILE rather than the folder name.

    Two feeds of one creator are two accounts, so no name rule can join them
    ("sexyoverdrive" / "sexytestdrive"). What does: the bio of one naming the
    other (explicit cross-reference), or the same normalised display name on a
    free account and a paid one (price 0 vs > 0).

    Returns {group_key: [folder, ...]} with group_key like "id:<hash>", stable for
    a given membership so a tombstone keeps working.
    """
    have = [f for f in folders if f in profiles and isinstance(profiles[f], dict)]
    if len(have) < 2:
        return {}
    by_handle = {f.lower(): f for f in have}
    links = []
    for f in have:
        pf = profiles[f]
        for m in pf.get("mentions") or []:
            other = by_handle.get(str(m).lower())
            if other and other != f:
                links.append((f, other))
    for i, a in enumerate(have):
        for b in have[i + 1:]:
            pa, pb = profiles[a], profiles[b]
            if not pa.get("name") or pa.get("name") != pb.get("name"):
                continue
            if pa.get("source_id") == pb.get("source_id"):
                continue
            try:
                fa, fb = float(pa.get("price") or 0), float(pb.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if (fa == 0) != (fb == 0):          # one free, one paid
                links.append((a, b))
    if not links:
        return {}
    # union-find so three-way links collapse into one group
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for a, b in links:
        union(a, b)
    comp = {}
    for f in list(parent):
        comp.setdefault(find(f), []).append(f)
    out = {}
    for members in comp.values():
        if len(members) < 2:
            continue
        key = ID_PREFIX + hashlib.sha1("|".join(sorted(members)).encode()).hexdigest()[:10]
        out[key] = sorted(members)
    return out


def explain(folders, profiles):
    """Why these folders were paired — short labels for the review list.

    Empty list means "no identity signal" (a name-based pair, or nothing).
    """
    reasons = []
    low = {f.lower(): f for f in folders}
    for f in folders:
        pf = profiles.get(f) or {}
        for m in pf.get("mentions") or []:
            if str(m).lower() in low and str(m).lower() != f.lower():
                if "bio names the other feed" not in reasons:
                    reasons.append("bio names the other feed")
    names = {(profiles.get(f) or {}).get("name") for f in folders} - {None, ""}
    if len(folders) > 1 and len(names) == 1:
        reasons.append("same display name")
    prices = []
    for f in folders:
        try:
            prices.append(float((profiles.get(f) or {}).get("price") or 0))
        except (TypeError, ValueError):
            prices.append(0.0)
    if prices and any(p == 0 for p in prices) and any(p > 0 for p in prices):
        reasons.append("free + paid")
    return reasons


def derive(groups, folders, profiles=None):
    """Return the merged ledger list. Pure: no I/O, easy to test."""
    groups = [g for g in (groups or []) if isinstance(g, dict) and g.get("id")]
    bases = pair_bases(folders)
    ident = identity_bases(folders, profiles or {})
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
    assigned = set()

    def settle(gid, key, candidates):
        """Materialise one derived group (name-based or identity-based)."""
        live = existing.pop(gid, None)
        if gid in tomb:
            if live:                                   # a live group on a dismissed
                out.append({**live, "del": 1, "ts": now})   # pair: retire it
            return
        members = sorted(dict.fromkeys(n for n in candidates if n not in claimed))
        if len(members) < 2:
            if live:
                out.append({**live, "del": 1, "ts": now})
            return
        assigned.update(members)
        name = auto_name(key, members)
        if live is None:
            out.append({"id": gid, "name": name, "folders": members, "ts": now, "auto": 1})
        elif sorted(str(x) for x in (live.get("folders") or [])) != members:
            out.append({**live, "folders": members, "ts": now, "auto": 1})
        else:
            out.append(live)

    # 1) name-based pairs first: their ids are stable and human-recognisable
    for b in sorted(bases):
        settle(AUTO_PREFIX + b, b, bases[b])
    # 2) identity pairs: only folders no name rule already grouped
    for key in sorted(ident):
        settle(AUTO_PREFIX + key, key, [n for n in ident[key] if n not in assigned])

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
    ap.add_argument("--profiles", default="", help="source_profiles.json (default: state dir)")
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

    profiles = load_profiles(a.profiles or None)
    print("auto_merge: %d source profiles available" % len(profiles))
    if a.ledger:
        ledger = json.loads(Path(a.ledger).read_text())
    else:
        ledger = http_json(UPLOAD_URL + "/merges?ts=" + str(int(time.time() * 1000)))
    groups = ledger.get("groups") or []
    new = derive(groups, folders, profiles)

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
