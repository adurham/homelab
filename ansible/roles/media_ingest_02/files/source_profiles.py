#!/usr/bin/env python3
"""Export the source profile of every model ofscraper has cached, for the gallery.

WHY: free and paid feeds of the same person are two accounts, so folder NAMES
cannot pair them ("sexyoverdrive" vs "sexytestdrive"). ofscraper fetches each
profile on every run — display name, bio, avatar — and throws it away. This
writes that down and POSTs it to the gallery, where the pairing rule can use
identity instead of guessing from names.

Source: ofscraper's own response cache (requests-cache in
<profile>/cache_sql/cache.db). No new API calls, no new credentials, no writes
to the scraper's state.

Runs as step 2 of the scraper sweep and on a timer. Idempotent.
"""
import hashlib
import json
import os
import pickle  # our own scraper's cache file on this host — not untrusted input
import re
import sqlite3
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("TG_SCRAPER_STATE", "/var/lib/media-ingest-02"))
DB = Path(os.environ.get("TG_OFSC_CACHE", str(STATE / "main_profile/cache_sql/cache.db")))
OUT = Path(os.environ.get("TG_SOURCE_PROFILES", str(STATE / "source_profiles.json")))
HANDLE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,29}")


def load_value(blob):
    if isinstance(blob, (bytes, bytearray)):
        try:
            return pickle.loads(bytes(blob))
        except Exception:  # noqa: BLE001
            return None
    return blob


def find_profile(obj, depth=0):
    """A user dict carries id + username + (avatar or name)."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if obj.get("id") and obj.get("username") and ("avatar" in obj or "name" in obj):
            return obj
        for v in obj.values():
            r = find_profile(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, (list, tuple)):
        for v in obj[:50]:
            r = find_profile(v, depth + 1)
            if r:
                return r
    return None


def norm_name(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def sha(s):
    return hashlib.sha256(str(s or "").encode()).hexdigest()[:16]


def main():
    if not DB.exists():
        print("profiles: no scraper cache at %s — nothing to export" % DB)
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = list(con.execute("select key, value from Cache"))
    profiles = {}
    for key, val in rows:
        obj = load_value(val)
        prof = find_profile(obj)
        if not prof:
            continue
        user = str(prof.get("username") or "").strip().lower()
        if not user or user in profiles:
            continue
        about = str(prof.get("about") or "")
        profiles[user] = {
            "source_id": sha(prof.get("id")),        # hashed: the gallery never needs the raw id
            "name": norm_name(prof.get("name")),
            "avatar": sha(prof.get("avatar")),
            "mentions": sorted({m for m in HANDLE_RE.findall(about.lower())
                                if m != user and len(m) > 3}),
            "price": prof.get("subscribePrice"),
            "exported": int(time.time()),
        }
    if not profiles:
        print("profiles: cache had no profile responses — nothing to export")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(OUT) + ".tmp"
    Path(tmp).write_text(json.dumps({"profiles": profiles}, separators=(",", ":"), sort_keys=True))
    os.replace(tmp, OUT)
    print("profiles: wrote %d to %s" % (len(profiles), OUT))

    # Ship it to the gallery (same bearer path the media push uses).
    try:
        sys.path.insert(0, "/opt/media-ingest-02")
        import requests
        import store_client

        r = requests.post(store_client.GALLERY_BASE + "/ingest/profiles",
                          json={"profiles": profiles},
                          headers=store_client._auth_headers(), timeout=60)
        print("profiles: POST /ingest/profiles -> %s %s" % (r.status_code, r.text[:120]))
        if r.status_code >= 300:
            return 1
    except Exception as e:  # noqa: BLE001 — a push failure must not break the sweep
        print("profiles: push failed: %s: %s" % (type(e).__name__, e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
