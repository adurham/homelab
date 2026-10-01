#!/usr/bin/env python3
"""Shared ledger for tracking EVERY removal/dedup action and why.

WHY (user requirement, 2026-10-01): "we need to track what has been deleted/
deduped and why so we can make sure the scraper doesn't redownload them."

The gallery previously wrote only a flat stem list (`excluded.json`) that the
collectors consult before capturing. That proves a stem shouldn't be
re-captured, but says nothing about WHY it vanished — so a wrong automated
hide/delete could never be reviewed, and the reason for a big space reclaim
was unknowable after the fact.

This ledger is the single source of truth for removal HISTORY:

    {"entries": [
        {"stem": "...", "chat": "...", "action": "deleted"|"dedup_hidden"|
         "dedup_keep"|"spam_review"|"restored",
         "reason": "duplicate"|"user_delete"|"spam"|"manual",
         "detail": "<human-readable specifics>",
         "ts": "2026-10-01T12:34:56", "size": 12345, "by": "dedup_scan|trash|
         spam_scan|user"},
        ...]}

Dual-written to the local service dir AND mirrored to Drive
(`gcrypt:gallery/deletions.json`) so it survives a rebuild, exactly like
hidden.json / excluded.json.

CONTRACT: callers must ALSO add the stem to the exclusion ledger when the
removal should be permanent (see `record_removal`'s `exclude=True` default) —
the collectors gate on excluded.json, and a deleted-but-not-excluded stem
WILL be re-downloaded by the next scrape/reconcile sweep.

Kept deliberately dumb: append + prune + atomic replace, under fcntl so the
several services (trash/upload/dedup) that touch it can't race.
"""
import json
import os
import subprocess
import tempfile
import time
import fcntl
from pathlib import Path

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediagallery/.config/rclone/rclone.conf")
STATE = Path(os.environ.get("TG_STATE_DIR", "/var/lib/media-gallery"))
LEDGER = Path(os.environ.get("TG_DELETIONS_FILE", str(STATE / "deletions.json")))
REMOTE_LEDGER = REMOTE + "gallery/deletions.json"
EXCLUDE_FILE = Path(os.environ.get("TG_EXCLUDE_FILE", str(STATE / "excluded.json")))
EXCLUDE_REMOTE = REMOTE + "gallery/excluded.json"
# Lock lives beside the ledger (NOT a hardcoded /var/lock) so the module is
# testable and can't fail on a path the caller can't own. The other service
# locks in this app stay in /var/lock for historical reasons; this one is
# new, so it gets the better default.
LOCK = Path(os.environ.get("TG_DELETIONS_LOCK", str(STATE / "deletions.lock")))

# Cap the ledger so it can't grow without bound; oldest entries drop first.
# The user asked to be able to SEE what happened — 50k records is far more
# history than the UI needs and keeps the file a few MB.
MAX_ENTRIES = int(os.environ.get("TG_DELETIONS_MAX", "50000"))


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _rclone(*args):
    cmd = ["rclone"]
    if RCLONE_CONF:
        cmd += ["--config", RCLONE_CONF]
    return subprocess.run(cmd + list(args), capture_output=True, text=True)


def _load_locked():
    """Load the ledger. Caller must hold LOCK."""
    try:
        with open(LEDGER) as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return raw.get("entries") or []
        return raw or []
    except (OSError, ValueError):
        return []


def _save_locked(entries):
    """Atomic write + Drive mirror. Caller must hold LOCK."""
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    obj = {"entries": entries, "updated": _now()}
    fd, tmp = tempfile.mkstemp(dir=str(LEDGER.parent), suffix=".json")
    os.close(fd)
    Path(tmp).write_text(json.dumps(obj, separators=(",", ":")))
    os.replace(tmp, LEDGER)
    # Mirror to Drive (best effort — local is authoritative).
    try:
        _rclone("copyto", str(LEDGER), REMOTE_LEDGER)
    except OSError:
        pass


def _add_excluded(stems):
    """Add stems to the exclusion ledger (what the collectors gate on) and
    mirror it, so a removal can never be silently re-downloaded."""
    try:
        try:
            with open(EXCLUDE_FILE) as f:
                ex = set(json.load(f) or [])
        except (OSError, ValueError):
            ex = set()
        before = len(ex)
        ex |= {str(s) for s in stems}
        if len(ex) == before:
            return 0
        tmp = str(EXCLUDE_FILE) + ".tmp"
        Path(tmp).write_text(json.dumps(sorted(ex)))
        os.replace(tmp, EXCLUDE_FILE)
        try:
            _rclone("copyto", str(EXCLUDE_FILE), EXCLUDE_REMOTE)
        except OSError:
            pass
        return len(ex) - before
    except OSError:
        return 0


def record_removal(stem, chat="", action="deleted", reason="user_delete",
                   detail="", size=0, by="user", exclude=True, extra=None):
    """Record ONE removal/state-change and (by default) exclude it.

    Returns the record. Never raises — recording must never break a delete —
    but a failure is LOGGED (a silently-dead ledger would defeat the whole
    point of this module; see the app's pitfall about bare excepts).
    """
    rec = {
        "stem": str(stem),
        "chat": str(chat or ""),
        "action": str(action),
        "reason": str(reason),
        "detail": str(detail or ""),
        "ts": _now(),
        "size": int(size or 0),
        "by": str(by or "user"),
    }
    if extra:
        rec["extra"] = extra
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCK, "a+") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            entries = _load_locked()
            entries.append(rec)
            _save_locked(entries)
            if exclude:
                _add_excluded([stem])
    except Exception as e:  # noqa: BLE001 — must never break the caller
        print(f"[ledger] record_removal failed for {stem}: {type(e).__name__}: {e}",
              flush=True)
    return rec


def record_many(items, action="deleted", reason="user_delete", by="user",
                exclude=True, detail="", extra=None):
    """Record MANY removals in one locked pass (bulk deletes). `items` is an
    iterable of {stem, chat, size} dicts (or (stem, chat) tuples)."""
    out = []
    normalized = []
    for it in items:
        if isinstance(it, dict):
            normalized.append((str(it.get("stem")), str(it.get("chat") or ""),
                               int(it.get("size") or 0)))
        else:
            normalized.append((str(it[0]), str(it[1]) if len(it) > 1 else "", 0))
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCK, "a+") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            entries = _load_locked()
            ts = _now()
            for stem, chat, size in normalized:
                rec = {"stem": stem, "chat": chat, "action": str(action),
                       "reason": str(reason), "detail": str(detail or ""),
                       "ts": ts, "size": size, "by": str(by or "user")}
                if extra:
                    rec["extra"] = extra
                entries.append(rec)
                out.append(rec)
            _save_locked(entries)
            if exclude and normalized:
                _add_excluded([s for s, _, _ in normalized])
    except Exception as e:  # noqa: BLE001 — must never break the caller
        print(f"[ledger] record_many failed for {len(normalized)} stems: "
              f"{type(e).__name__}: {e}", flush=True)
    return out


def load_ledger(limit=None):
    """Read the ledger (newest last). For the UI / diagnostics."""
    try:
        with open(LOCK, "a+") as lf:
            fcntl.flock(lf, fcntl.LOCK_SH)
            entries = _load_locked()
    except OSError:
        return []
    return entries[-limit:] if limit else entries


def summary():
    """Counts by action + reason + reclaimed bytes (deleted & dedup_hidden)."""
    entries = load_ledger()
    by_action = {}
    by_reason = {}
    bytes_removed = 0
    for e in entries:
        a = e.get("action", "?")
        r = e.get("reason", "?")
        by_action[a] = by_action.get(a, 0) + 1
        by_reason[r] = by_reason.get(r, 0) + 1
        if a in ("deleted", "spam_deleted"):
            bytes_removed += int(e.get("size") or 0)
    return {"total": len(entries), "by_action": by_action,
            "by_reason": by_reason, "deleted_bytes": bytes_removed}
