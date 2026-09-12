#!/usr/bin/env python3
"""
Ingest-time duplicate detection for the media gallery.

WHY ingest-time: dedup_scan.py is the hourly BATCH duplicate detector. It
maintains the persistent stem->hash cache at DEDUP_HASH_CACHE and emits
dedup.json, which drives the SPA's "Duplicates" review view. But that is
fundamentally scheduled work: it only runs on refresh_gallery.sh's hourly
cycle, so a newly-arrived photo can sit for up to an hour before the scan
knows about it — and the batch scan also only REPORTS candidate groups for a
human to review; it never hides anything on its own.

The user's bar for this app is that duplicates are gone AT THE MOMENT a photo
arrives — "as seamless as browsing images in folders on a computer". A normal
desktop folder simply doesn't contain the duplicate, with no separate review
step and no staleness window. So this module reuses dedup_scan's incremental
hash cache and queries it ON-DEMAND from the upload path (upload_service.py is
the single ingest point for both browser uploads and the Telegram collector):
for each newly-arrived NON-VIDEO item, compute its dHash and ask "does
anything already indexed collide within HAMMING bits?" If yes, immediately hide
the loser from normal browsing via the hidden.json ledger (mirrored best-effort
to gcrypt:gallery/hidden.json by the same convention as trash_service.py's
save_excluded).

Compatibility with the batch scan: ingest-time hashing operates on the
ORIGINAL upload (upload_service stages each file into PENDING_ROOT), whereas
the hourly scan hashes 400px THUMBNAILS into the same cache. This is
compatible — empirically verified live: a dHash computed on an original image
and its thumbnail differ by 0-1 bits across 34 tested pairs, far inside
HAMMING=6 — so an ingest-time hash of the original is directly comparable to,
and merges cleanly into, the scan's thumbnail-based cache. Videos are excluded
here exactly as in the scan (INCLUDE_VIDEO=0).

Concurrency / data files (shared convention with the other workers):
  - HASH CACHE guarded by fcntl CACHE_LOCK (/var/lock/media-gallery-dedup-cache.lock)
  - hidden.json guarded by fcntl HIDDEN_LOCK (/var/lock/media-gallery-hidden.lock)
  - NEVER run anything as root: a root-owned lock file silently breaks the real
    mediagallery service (known incident — dedup_scan.py's own comment).

Env: TG_RCLONE_REMOTE (default gcrypt:), TG_HIDDEN_FILE, TG_DATEMAP_CACHE,
     RCLONE_CONFIG, and (through dedup_scan's defaults) DEDUP_HASH_CACHE.

All functions are importable without side effects — module import only parses
env vars (safe to import from the service without doing any work).
"""
import fcntl
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from dedup_scan import (  # noqa: F401  (re-exported for convenience of callers)
    HAMMING,
    dhash,
    load_hash_cache,
    popcount,
    save_hash_cache,
)

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "")
HIDDEN_FILE = Path(os.environ.get("TG_HIDDEN_FILE", "/var/lib/media-gallery/hidden.json"))
HIDDEN_REMOTE = REMOTE + "gallery/hidden.json"
HIDDEN_LOCK = Path("/var/lock/media-gallery-hidden.lock")
CACHE_LOCK = Path("/var/lock/media-gallery-dedup-cache.lock")
DATEMAP_CACHE = Path(os.environ.get("TG_DATEMAP_CACHE", "/var/lib/media-gallery/datemap.json"))


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# Same shape as dedup_scan.py's rclone() — honors RCLONE_CONFIG when set.
def rclone(*args):
    cmd = ["rclone"]
    if RCLONE_CONF:
        cmd += ["--config", RCLONE_CONF]
    return subprocess.run(cmd + list(args), capture_output=True, text=True)


def load_hidden(path=None):
    """hidden.json -> {"hidden": set, "keep": set}. Missing/corrupt -> empty sets.

    Format ("hidden" = stems hidden from normal browsing; "keep" = stems the user
    explicitly unhid, surviving the hourly scan's reconciliation):
        {"hidden": [stem, ...], "keep": [stem, ...]}
    Invariant: hidden ∩ keep = ∅ (mutations below preserve it).

    `path` overrides HIDDEN_FILE for testability; omitted => production file.
    """
    target = Path(path) if path is not None else HIDDEN_FILE
    raw = None
    try:
        raw = json.loads(target.read_text())
    except (OSError, ValueError, TypeError):
        raw = None
    if not isinstance(raw, dict):
        return {"hidden": set(), "keep": set()}
    hidden = raw.get("hidden")
    keep = raw.get("keep")
    if not isinstance(hidden, list):
        hidden = []
    if not isinstance(keep, list):
        keep = []
    return {"hidden": set(hidden), "keep": set(keep)}


def save_hidden(h, path=None):
    """Atomic write (tmp + os.replace) to hidden.json, then a best-effort mirror
    of the local file to HIDDEN_REMOTE via rclone in a daemon thread.

    The CALLER must hold HIDDEN_LOCK (this is the shared convention; the lock is
    not re-acquired here so it stays non-reentrant-safe for the endpoints that
    already hold it). Passing a custom `path` (test override) writes locally
    WITHOUT mirroring to Drive — no network/rclone side effects in tests.
    """
    target = Path(path) if path is not None else HIDDEN_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(target) + ".tmp"
    data = json.dumps(
        {"hidden": sorted(h["hidden"]), "keep": sorted(h["keep"])},
        separators=(",", ":"),
    )
    Path(tmp).write_text(data)
    os.replace(tmp, target)
    if path is None:  # production: slow Drive mirror must not block the response
        threading.Thread(
            target=lambda: rclone("copyto", str(HIDDEN_FILE), HIDDEN_REMOTE),
            daemon=True,
        ).start()


def find_newest_match(hash_val, cache, dates):
    """Return the cached stem whose hash is within HAMMING bits of hash_val,
    preferring the NEWEST by iso date among candidates. Linear scan of the cache
    (fine at ingest-time volume; the batch path uses LSH banding instead).

    dates: dict stem -> iso date string; a missing date is treated as "". Ties
    (equal dates) resolve to the first candidate in cache iteration order.
    Returns None when nothing is within HAMMING bits.
    """
    best = None
    best_date = ""
    for s, ch in cache.items():
        if popcount(hash_val ^ ch) > HAMMING:
            continue
        d = dates.get(s, "")
        if best is None or d > best_date:
            best, best_date = s, d
    return best


def decide_hide(new_stem, new_date, matched_stem, matched_date, keep_set):
    """PURE decision for one ingest-time duplicate pair. Returns:
      'hide_matched' — the NEW item is strictly newer than the existing matched
                       item, so hide the older one instead. (Never chosen if the
                       matched stem was explicitly user-KEPT.)
      'hide_new'     — otherwise: the new item is the duplicate to hide. This also
                       covers an explicitly user-KEPT matched stem (keep wins).
    `keep_set` = stems the user has unhid/kept; it is consulted but not mutated
    here (mutation happens in the caller so this stays a pure function).
    """
    if matched_stem in keep_set:
        return "hide_new"
    if new_date > matched_date:
        return "hide_matched"
    return "hide_new"


def _load_datemap_dates():
    """Parse DATEMAP_CACHE ({stem: {"date": <iso>, ...}}) into {stem: iso_date}.
    Missing/corrupt -> {}; a stem without a usable date maps to ''."""
    try:
        m = json.loads(DATEMAP_CACHE.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    out = {}
    for s, v in m.items():
        d = v.get("date") if isinstance(v, dict) else None
        out[s] = d if isinstance(d, str) else ""
    return out


def check_ingest_batch(items, new_dates):
    """items: list of (stem, path, is_video) tuples — the just-staged uploads.
    new_dates: {stem: iso_date} for the new stems (upload_service calls this AFTER
    update_datemap, so the shared datemap already contains the new stems too).

    For each NON-VIDEO item: compute its dHash (failure => log + skip, never
    raise). Then, holding fcntl CACHE_LOCK: load the shared hash cache and look for
    a within-HAMMING match. The datemap is loaded LAZILY — only after a hash
    match is found — and merged with new_dates. On a match, holding fcntl
    HIDDEN_LOCK — load the hidden ledger and decide which member to hide:
      - matched stem is in `keep`                      -> hide the NEW stem
      - matched stem == the new stem (idempotent re-ingest of an item already
                                                  indexed) -> SKIP: refresh the hash,
        never hide (a re-ingest must never hide itself)
      - new stem's date > matched                       -> hide the MATCHED stem (newer wins)
      - otherwise                                       -> hide the NEW stem
    Every new stem's hash is added to the cache regardless, and the cache saved.
    Every decision is logged.
    """
    hashed = []
    for stem, path, is_video in items:
        if is_video:
            continue
        try:
            hv = dhash(path)
        except Exception as e:  # noqa: BLE001 — never raise; skip the item
            log(f"ingest dedup: dhash failed for {stem}: {type(e).__name__}: {e}")
            continue
        hashed.append((stem, hv))
    if not hashed:
        return

    CACHE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        clf = open(CACHE_LOCK, "w")
    except PermissionError as e:
        log(f"ingest dedup: cannot open cache lock {CACHE_LOCK}: {e}")
        return
    with clf:
        fcntl.flock(clf, fcntl.LOCK_EX)
        cache = load_hash_cache()
        dates = None  # lazy: datemap only parsed once a hash match is found
        for stem, hv in hashed:
            # Hash-only candidate gate (cheap linear scan) so we don't parse the
            # ~22MB datemap for items that have no collision at all.
            if not any(popcount(hv ^ ch) <= HAMMING for ch in cache.values()):
                cache.setdefault(stem, hv)
                continue
            if dates is None:
                dates = _load_datemap_dates()
                dates.update(new_dates)
            matched = find_newest_match(hv, cache, dates)
            if matched is None:
                cache.setdefault(stem, hv)
                continue
            # Self-match guard: find_newest_match can return the stem's OWN hash
            # at distance 0 when the stem is already indexed (e.g. the Telegram
            # collector idempotently re-pushes media with the same stem_override,
            # so the SAME stem is staged and re-hashed). Without this guard the
            # item would be hidden by its own re-ingest — a visible item silently
            # hiding itself. Refresh the hash and skip the hide decision entirely.
            if matched == stem:
                log(f"ingest dedup: {stem} re-ingested (self-match) — no hide decision")
                cache.setdefault(stem, hv)
                continue
            # Match found: hide someone. hold the hidden ledger lock.
            HIDDEN_LOCK.parent.mkdir(parents=True, exist_ok=True)
            with open(HIDDEN_LOCK, "w") as hlf:
                fcntl.flock(hlf, fcntl.LOCK_EX)
                h = load_hidden()
                action = decide_hide(
                    stem, new_dates.get(stem, ""), matched,
                    dates.get(matched, ""), h["keep"])
                if action == "hide_matched":
                    h["hidden"].add(matched)
                    h["keep"].discard(matched)
                else:
                    h["hidden"].add(stem)
                    h["keep"].discard(stem)
                save_hidden(h)
                dist = popcount(hv ^ cache[matched])
                hidden_stem = matched if action == "hide_matched" else stem
                log(f"ingest dedup: {stem} is a duplicate of {matched} "
                    f"(hamming {dist}) — hidden {hidden_stem}")
            cache.setdefault(stem, hv)
        save_hash_cache(cache)
