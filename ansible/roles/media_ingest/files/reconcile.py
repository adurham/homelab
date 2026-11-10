#!/usr/bin/env python3
"""
Reconcile sweep (collector edition) — periodic backstop that re-scans recent
private-chat history and pushes any incoming media the live collector missed
(restart/disconnect gaps, a message that arrived before a deploy, etc.).

This is the belt-and-suspenders companion to the live collector's catch_up:
catch_up handles the reconnect difference; this sweep guarantees eventual
consistency by independently walking the last N messages of each private 1:1
chat on a timer and pushing anything not already in the gallery.

Design (matches collector.py semantics exactly):
  * INCOMING only (msg.out == False) — never our own sent media.
  * PRIVATE 1:1 chats only.
  * photos, videos (incl. gifs / round notes), image|video documents; skip
    stickers / voice / non-media docs. Ephemeral included.
  * route chat-id -> folder via the gallery's folder_meta (rename-safe), exactly
    like the live collector — NOT the empty static map. Falls back to the
    sanitized chat title only if folder_meta has no mapping.
  * skip stems in the gallery exclusion ledger (trashed/purged).
  * idempotent: the gallery dedups by stem, so re-pushing an existing item is a
    no-op. A per-run in-memory _seen guards against album/duplicate work.

Bounded work: scans at most LOOKBACK messages per dialog (default 40), so each
run is cheap and the timer can fire often. The gallery's stem-dedup means we
never need a perfect checkpoint — overlap is free.

Env: TG_API_ID, TG_API_HASH, TG_SESSION (+ store_client env). Flags:
  --lookback N   messages per dialog to scan (default 40)
  --dialogs S..  restrict to dialog-name substrings
  --dry-run      report what WOULD be pushed, download/push nothing
"""
import argparse
import asyncio
import glob
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from telethon import TelegramClient as SourceClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store_client  # noqa: E402

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
# The live collector holds collector.session's SQLite open. Two processes on one
# .session file cause lock contention, so the sweep runs on a SEPARATE session
# file that is a fresh copy of the collector's auth (the source allows multiple
# concurrent connections on one authorization). We copy it at startup.
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-ingest/collector")
RECONCILE_SESSION = os.environ.get("TG_RECONCILE_SESSION", "/var/lib/media-ingest/reconcile")
STAGING = Path(os.environ.get("TG_STAGING", "/var/lib/media-ingest/staging"))
LOG_FILE = os.environ.get("TG_RECONCILE_LOG", "/var/log/media-ingest/reconcile.log")
# Downloads the live collector could not push (see collector._park_failed). This
# sweep drains them first, so an outage no longer strands media on disk.
FAILED = Path(os.environ.get("TG_FAILED_DIR", "/var/lib/media-ingest/failed"))
# Last known exclusion (trash) ledger. Without it a token failure used to abort
# the whole sweep — and did for ~20h on 2026-11-10 while the gallery auth was
# broken, silently losing every ephemeral item in the window.
EXCL_CACHE = Path(os.environ.get("TG_EXCLUDED_CACHE", "/var/lib/media-ingest/excluded_cache.json"))

STAGING.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("reconcile")
logging.getLogger("telethon").setLevel(logging.WARNING)


def _load_excluded_cache():
    try:
        return set(json.loads(EXCL_CACHE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return None


def _park(stem, folder, date_iso):
    """Keep a reconcile download whose push failed (mirror of collector._park_failed).

    The sweep's own cleanup used to delete the file even on failure, so an outage
    could lose media the same way the live collector did. Park it next to the
    collector's parked items; the next sweep's push_parked() drains it.
    """
    try:
        FAILED.mkdir(parents=True, exist_ok=True)
        files = [p for p in STAGING.glob(stem + "*") if p.suffix != ".json"]
        if not files:
            return
        for p in files:
            shutil.move(str(p), str(FAILED / p.name))
        (FAILED / (stem + ".json")).write_text(
            json.dumps({"stem": stem, "folder": folder, "date": date_iso}),
            encoding="utf-8",
        )
        log.warning("PARKED %s (%d file(s)) in %s — push failed, kept for retry",
                    stem, len(files), FAILED)
    except Exception as e:  # noqa: BLE001
        log.warning("could not park %s: %s: %s", stem, type(e).__name__, e)


def push_parked(dry_run=False, limit=50):
    """Drain downloads the live collector could not push.

    collector._park_failed moves a failed download out of the tmpfs staging dir
    into FAILED with a .json sidecar (folder + date). Push those first on every
    sweep, so a gallery outage strands media for minutes instead of forever.
    """
    if not FAILED.is_dir():
        return 0, 0
    pushed = failed = 0
    for sidecar in sorted(FAILED.glob("*.json"))[:limit]:
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.warning("parked sidecar unreadable %s: %s", sidecar.name, e)
            continue
        stem = meta.get("stem") or sidecar.stem
        folder = meta.get("folder")
        files = [p for p in FAILED.glob(stem + "*") if p.suffix != ".json"]
        if not folder or not files:
            continue
        if dry_run:
            log.info("WOULD push parked %s (%s) -> %s", stem, files[0].name, folder)
            continue
        try:
            store_client.push_media(folder, str(files[0]), stem, meta.get("date", ""),
                                    is_out=False)
            for p in files:
                p.unlink()
            sidecar.unlink()
            log.info("PUSHED parked %s -> %s", stem, folder)
            pushed += 1
        except Exception as e:  # noqa: BLE001
            log.error("parked push failed %s: %s: %s", stem, type(e).__name__, e)
            failed += 1
    return pushed, failed


def sanitize(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in (name or "")).strip()
    return keep.replace(" ", "-") or "unknown"


# ─── Durable-merge redirect resolution (SEMANTIC COPY of
#     roles/media_gallery/files/folder_redirect.py — the canonical module; it
#     cannot be imported here because this host is a different box with its own
#     non-overlapping module tree). Keep these byte-for-byte in sync with the
#     canonical source; roles/media_gallery/tests/test_merge_redirect.py asserts
#     the copies produce identical output.
def resolve_redirect(redirects, key, max_hops=10):
    seen = set()
    cur = key
    for _ in range(max_hops):
        if cur not in redirects:
            return None
        if cur in seen:
            return cur
        seen.add(cur)
        cur = redirects[cur]
        if cur not in redirects:
            return cur
    return None


def resolve_folder(redirects, folder, chat_id=None):
    if chat_id is not None:
        r = resolve_redirect(redirects, "chat:%s" % chat_id)
        if r is not None:
            return r
    r = resolve_redirect(redirects, "name:%s" % folder)
    if r is not None:
        return r
    r = resolve_redirect(redirects, "user:%s" % folder)
    if r is not None:
        return r
    return folder


def media_kind(msg):
    """Identical classification to collector.py: photo/video/media-doc or None."""
    if getattr(msg, "sticker", None):
        return None
    if getattr(msg, "photo", None):
        return "photo"
    if getattr(msg, "video", None) or getattr(msg, "video_note", None) or getattr(msg, "gif", None):
        return "video"
    doc = getattr(msg, "document", None)
    if doc is not None:
        mt = getattr(doc, "mime_type", "") or ""
        if mt.startswith("image/") or mt.startswith("video/"):
            return "media-doc"
    return None


def build_folder_map():
    """chat_id -> folder from the gallery's folder_meta (rename-safe routing),
    with durable-merge redirects folded in (a chat redirect wins over the
    chat_ids map — the authoritative post-merge routing)."""
    try:
        meta = store_client.get_folder_meta() or {}
    except Exception as e:  # noqa: BLE001
        log.warning("folder_meta fetch failed (%s); using sanitized titles only", e)
        return {}, {}
    m = {}
    for folder, entry in meta.items():
        for cid in (entry.get("chat_ids") or []):
            m[str(cid)] = folder
    redirects = dict(meta.get("redirects") or {})
    # chat redirects fold into the map so per-dialog routing stays one lookup
    for k, v in redirects.items():
        if k.startswith("chat:") and v:
            m[k[len("chat:"):]] = v
    return m, redirects


def _ensure_session_copy():
    """Copy the collector's authorized session to the reconcile session path so
    the sweep doesn't contend on the live SQLite. Refresh each run so a re-auth
    of the collector propagates. No-op if the source session is missing."""
    import shutil
    src = SESSION + ".session"
    dst = RECONCILE_SESSION + ".session"
    if not os.path.exists(src):
        log.error("collector session %s missing — cannot run sweep", src)
        sys.exit(2)
    try:
        shutil.copy2(src, dst)
        # drop any stale journal/wal for the copy
        for ext in ("-journal", "-wal", "-shm"):
            p = dst + ext
            if os.path.exists(p):
                os.remove(p)
    except OSError as e:
        log.error("could not stage reconcile session: %s", e)
        sys.exit(2)


async def run(lookback, dialog_filters, dry_run):
    _ensure_session_copy()
    client = SourceClient(RECONCILE_SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log.error("SESSION NOT AUTHORIZED — collector login required.")
        sys.exit(2)
    dynmap, redirects = build_folder_map()
    try:
        excluded = store_client.get_excluded()
        try:
            EXCL_CACHE.write_text(json.dumps(sorted(excluded)), encoding="utf-8")
        except OSError as e:
            log.debug("could not refresh exclusion cache: %s", e)
    except Exception as e:  # noqa: BLE001
        cached = _load_excluded_cache()
        if cached is None:
            log.error("excluded fetch failed: %s — no cache to fall back on, aborting "
                      "to avoid re-adding trash", e)
            await client.disconnect()
            sys.exit(3)
        excluded = cached
        log.warning("excluded fetch failed (%s) — using cached ledger (%d stems); "
                    "anything trashed since that cache may be re-pushed", e, len(excluded))
    log.info("reconcile start: lookback=%d folder_meta=%d excluded=%d dry_run=%s",
             lookback, len(dynmap), len(excluded), dry_run)

    # ─── Phase 0: drain downloads the collector could not push ─────────────
    parked_pushed, parked_failed = push_parked(dry_run=dry_run)
    if parked_pushed or parked_failed:
        log.info("parked drain: pushed=%d failed=%d", parked_pushed, parked_failed)

    # ─── Phase 1: enumerate candidates (metadata only, no downloads) ───────
    # Collect every incoming media stem in the recent history window FIRST,
    # then ask the gallery which of them it already accounts for. Without
    # this pre-check the sweep re-downloaded and re-pushed the same recent
    # items on every 20-minute run, forever — the gallery's stem-dedup made
    # that a silent no-op at the destination, but every pass still paid a
    # full source download + upload for media it had held for months.
    candidates = []  # (stem, kind, folder, date_iso, entity)
    seen = set()
    async for d in client.iter_dialogs():
        if not d.is_user:  # private 1:1 only
            continue
        if dialog_filters and not any(s.lower() in (d.name or "").lower() for s in dialog_filters):
            continue
        cid = str(d.id)
        # chat redirect (already folded into dynmap) > chat_ids > name redirect
        # on what we'd sanitize to > sanitized title
        folder = dynmap.get(cid) or resolve_redirect(redirects, "name:%s" % sanitize(d.name)) or sanitize(d.name)
        async for msg in client.iter_messages(d.entity, limit=lookback):
            if getattr(msg, "out", False):
                continue
            kind = media_kind(msg)
            if not kind:
                continue
            stem = f"{d.id}_{msg.id}"
            if stem in seen:
                continue
            seen.add(stem)
            date_iso = msg.date.isoformat() if msg.date else ""
            candidates.append((stem, kind, folder, date_iso, msg))

    # Ask the gallery which candidate stems it already accounts for (ingested
    # previously, or deliberately deleted). Fail OPEN on any error — the old
    # behavior (push everything), which the gallery's dedup absorbs — but
    # structure the log line distinctly so a broken /have is alertable
    # rather than silently restoring the full re-push burn.
    have = set()
    have_ok = True
    if not dry_run and candidates:
        try:
            have = store_client.have_stems([c[0] for c in candidates])
        except Exception as e:  # noqa: BLE001
            have_ok = False
            log.error("HAVE CHECK FAILED (%s: %s) — falling back to full push "
                      "this sweep; gallery dedup absorbs it but the sweep is "
                      "unoptimized until this recovers", type(e).__name__, e)

    # ─── Phase 2: download + push only what's actually missing ────────────
    scanned = pushed = skipped = failed = 0
    for stem, kind, folder, date_iso, msg in candidates:
        scanned += 1
        if stem in excluded:
            skipped += 1
            continue
        if have_ok and stem in have:
            skipped += 1
            continue
        if dry_run:
            log.info("WOULD push %s (%s) date=%s -> %s", stem, kind, date_iso, folder)
            pushed += 1
            continue
        tmp = STAGING / stem
        ok = False
        try:
            path = await msg.download_media(file=str(tmp))
            if not path or os.path.getsize(path) == 0:
                log.warning("empty download %s", stem)
                continue
            store_client.push_media(folder, path, stem, date_iso, is_out=False)
            pushed += 1
            ok = True
            log.info("PUSHED %s (%s) -> %s", stem, kind, folder)
        except Exception as e:  # noqa: BLE001
            failed += 1
            log.error("push failed %s: %s: %s", stem, type(e).__name__, e)
            _park(stem, folder, date_iso)
        finally:
            if ok:
                for p in [str(tmp)] + glob.glob(str(tmp) + "*"):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
    log.info("reconcile done: scanned=%d pushed=%d skipped=%d failed=%d",
             scanned, pushed, skipped, failed)
    await client.disconnect()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=int(os.environ.get("TG_RECONCILE_LOOKBACK", "40")))
    ap.add_argument("--dialogs", nargs="*", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    asyncio.run(run(a.lookback, a.dialogs, a.dry_run))


if __name__ == "__main__":
    main()
