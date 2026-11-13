#!/usr/bin/env python3
"""
upstream source media collector (collector edition) — captures incoming media in
real time and PUSHES it to the gallery platform via the authenticated ingest
API. No rclone, no crypt key, no GDrive here: this box only holds the upstream source
session and the gallery OAuth2 client creds.

Scope of capture (what counts as "all images FROM the user, not FROM me"):
  * INCOMING only (msg.out == False) — never our own sent media.
  * PRIVATE 1:1 chats only (event.is_private) — not groups/channels, so big
    group/channel media floods don't pollute the gallery. Broaden here if you
    ever want group capture.
  * Photos, videos, and image/video documents. Stickers / voice / other docs
    are skipped. Ephemeral (ttl_seconds / ephemeral) media is INCLUDED
    automatically and handled non-destructively (silent download, no read
    receipt — preserves the phone copy).
  * Stems already in the gallery exclusion ledger (trashed/purged) are skipped
    so they never re-import.

On a capturable incoming message sent TO us:
  1. silent download to a tmpfs staging dir (no read receipt fired)
  2. resolve the destination folder = the chat's gallery folder name
  3. push to the gallery with stem=<chatid>_<msgid>, the real message date,
     out=False (received). The gallery encrypts + stores + thumbnails + dedups
     by stem (idempotent re-push on edits).
  4. delete the local staging file.

Folder naming mirrors the gallery's CHAT_NAMES map so captures land in the same
folders as the historical archive.
"""
import asyncio
import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from telethon import TelegramClient as SourceClient, events, utils as tl_utils
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store_client  # noqa: E402
import ingest_metrics  # noqa: E402

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-ingest/collector")
STAGING = Path(os.environ.get("TG_STAGING", "/var/lib/media-ingest/staging"))
LOG_FILE = os.environ.get("TG_LOG_FILE", "/var/log/media-ingest/collector.log")
# Where a download is parked when the gallery push fails. STAGING is a tmpfs, so
# anything left there dies with a reboot, and TTL/self-destruct media is purged
# server-side once consumed -- a failed push used to be permanent data loss
# (hit live 2026-11-10: the file was downloaded, the push 400'd during a gallery
# auth outage, and the old unconditional cleanup deleted the only copy).
FAILED = Path(os.environ.get("TG_FAILED_DIR", "/var/lib/media-ingest/failed"))
# Parked downloads are encrypted to a PUBLIC key: plaintext media must never
# touch persistent storage (that is why staging is a tmpfs), and the matching
# private key is deliberately NOT on this host -- it lives in the password
# manager, so a compromise of this box yields ciphertext only. Nothing here can
# decrypt, which is the point; recovery is done off-box.
PARK_RECIPIENT = os.environ.get("STAGING_PARK_RECIPIENT", "park@media-ingest.local")
# After a failed push the plaintext is kept in staging (RAM) beside its
# encrypted disk copy only while staging is under this fraction; see
# reconcile.KEEP_PLAIN_BELOW, which must stay in step.
KEEP_PLAIN_BELOW = float(os.environ.get("TG_KEEP_PLAIN_BELOW", "0.5"))


def _encrypt_file(src: Path, dst: Path) -> None:
    """Encrypt src to dst for PARK_RECIPIENT (gpg public-key, no local secret)."""
    # Write beside the target and rename: a gpg that dies half-way must never
    # replace an earlier good ciphertext of the same item with a truncated one.
    part = dst.with_name(dst.name + ".part")
    try:
        subprocess.run(
            ["gpg", "--batch", "--yes", "--quiet", "--trust-model", "always",
             "--recipient", PARK_RECIPIENT, "--output", str(part), "--encrypt", str(src)],
            check=True,
        )
        os.replace(part, dst)
    finally:
        if part.exists():
            part.unlink()

# Active-pull backstop interval (seconds). Telegram deprioritizes update fan-out
# to idle-looking secondary sessions (a userbot that only pings looks dormant),
# so the passive push path can lag MINUTES — fatal for self-destruct/TTL media,
# which is purged server-side the instant it's consumed and is NOT recoverable by
# the history-based reconcile sweep. We force a getState+getDifference every
# POLL_INTERVAL seconds to pull any pending updates and replay them through the
# live handlers, bounding worst-case live-path latency to ~POLL_INTERVAL. The
# regular active API calls also keep the session looking "live," which improves
# native push promptness on its own. catch_up is a cheap no-op when nothing is
# pending. Set TG_POLL_INTERVAL=0 to disable (revert to pure passive push).
POLL_INTERVAL = float(os.environ.get("TG_POLL_INTERVAL", "15"))

# chat-id -> gallery folder, optional STATIC SEED. The gallery's folder_meta.json
# is the SINGLE SOURCE OF TRUTH for chat-id -> folder routing; manage all
# mappings in the gallery UI. This dict is intentionally EMPTY in the public repo
# (it used to hold real chat-ids + people's names — a privacy leak in a public
# tree). Leave it empty: unmapped chats fall back to the sanitized chat title and
# are then routed/renamed from the gallery. Populate locally only if you need a
# bootstrap before folder_meta exists, but never commit real identities here.
CHAT_NAMES = {}


def _seed_static_chat_ids():
    """One-time on startup: push CHAT_NAMES entries into folder_meta for any
    chat-id not already mapped there. Makes folder_meta the single source of
    truth without losing the historical static mappings."""
    try:
        import store_client
        meta = store_client.get_folder_meta() or {}
        mapped = set()
        for entry in meta.values():
            for cid in (entry.get("chat_ids") or []):
                mapped.add(str(cid))
        # group unmapped static entries by their target folder
        to_add = {}
        for cid, folder in CHAT_NAMES.items():
            if str(cid) not in mapped:
                to_add.setdefault(folder, []).append(str(cid))
        for folder, cids in to_add.items():
            existing = (meta.get(folder, {}).get("chat_ids") or [])
            store_client.set_chat_ids(folder, sorted(set(existing) | set(cids)))
            log.info("seeded folder_meta: %s -> %s", folder, cids)
        if to_add:
            log.info("folder_meta seed complete (%d folder(s))", len(to_add))
    except Exception as e:  # noqa: BLE001
        log.warning("folder_meta seed skipped: %s", e)

# Cached chat-id -> folder map fetched from the gallery's folder_meta.json.
_dyn_map = {}
# Cached durable-merge redirect map (folder_meta.json "redirects" key) — see
# resolve_folder above. Refreshed on the same TTL as the chat map.
_dyn_redirects = {}
_dyn_map_ts = 0.0
_DYN_TTL = 60.0  # refresh at most once a minute


def _refresh_dynamic_map():
    """Pull folder_meta from the gallery and build chat_id -> folder. Best-effort;
    on any failure we keep the last good map (or empty -> static fallback)."""
    global _dyn_map, _dyn_redirects, _dyn_map_ts
    import time as _t
    if _t.time() - _dyn_map_ts < _DYN_TTL:
        return
    _dyn_map_ts = _t.time()
    try:
        import store_client
        meta = store_client.get_folder_meta()  # {folder: {chat_ids:[...], cover}}
        m = {}
        for folder, entry in (meta or {}).items():
            for cid in (entry.get("chat_ids") or []):
                m[str(cid)] = folder
        _dyn_map = m
        _dyn_redirects = dict((meta or {}).get("redirects") or {})
    except Exception as e:  # noqa: BLE001
        log.debug("folder_meta refresh failed: %s", e)

STAGING.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("collector-collector")
logging.getLogger("telethon").setLevel(logging.WARNING)


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


def folder_for(chat_id, name):
    # 1) durable merge redirect on the chat-id wins (authoritative; reflects a
    #    folder merge even before chat_ids is re-keyed, and even when a stale
    #    chat_ids map would otherwise route wrong)
    _refresh_dynamic_map()
    cid = str(chat_id)
    r = resolve_redirect(_dyn_redirects, "chat:%s" % cid)
    if r is not None:
        return r
    # 2) dynamic UI map (rename-safe, user-controlled)
    if cid in _dyn_map:
        return _dyn_map[cid]
    # 3) name redirect on what we WOULD sanitize to (catches folder merges that
    #    rename the display name when no chat_ids mapping exists)
    r = resolve_redirect(_dyn_redirects, "name:%s" % sanitize(name))
    if r is not None:
        return r
    # 4) static fallback map
    if cid in CHAT_NAMES:
        return CHAT_NAMES[cid]
    # 5) sanitized chat title (or 'unknown')
    return sanitize(name)


def ttl_of(media):
    if isinstance(media, (MessageMediaPhoto, MessageMediaDocument)):
        return getattr(media, "ttl_seconds", None)
    return None


def media_kind(msg):
    """Classify a message's media for capture. Returns 'photo' / 'video' /
    'media-doc' for capturable media, or None to skip. Captures photos, videos
    (incl. gifs / round video notes) and image|video documents; skips stickers,
    voice/audio, and non-media documents. Ephemeral media is included (its
    underlying type is still a photo/document)."""
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


# Gallery exclusion ledger (trashed/purged stems). Refreshed periodically so the
# collector never re-imports something the user deleted in the gallery.
_excluded = set()
_excluded_ts = 0.0
_EXCL_TTL = 120.0  # refresh at most every 2 minutes


def _refresh_excluded():
    global _excluded, _excluded_ts
    import time as _t
    if _t.time() - _excluded_ts < _EXCL_TTL and _excluded_ts:
        return
    _excluded_ts = _t.time()
    try:
        _excluded = store_client.get_excluded()
    except Exception as e:  # noqa: BLE001
        log.debug("excluded refresh failed: %s", e)


# In-process set of stems already pushed this run, so NewMessage + MessageEdited
# (or repeated caption edits) don't re-download/re-push the same item.
_seen = set()


def _park_failed(stem: str, folder: str, date_iso: str, keep_plain: bool = False) -> bool:
    """Keep a downloaded-but-unpushed file instead of deleting it.

    STAGING is a tmpfs and the old cleanup ran in a `finally`, so a failed push
    destroyed the only copy while the source had already purged TTL media. Move
    the bytes to the durable FAILED dir plus a .json sidecar (folder + date) so
    a retry can push them correctly. Best-effort: never mask the original error.

    keep_plain=True writes the encrypted copy but leaves the staged plaintext
    in place: used to park ephemeral media BEFORE the push is attempted, so no
    later failure (push, park, a full staging dir) can be the only thing
    standing between that item and permanent loss.
    """
    done = 0
    try:
        FAILED.mkdir(parents=True, exist_ok=True)
        files = [p for p in ingest_metrics.stem_files(STAGING, stem)
                 if p.suffix != ".json" and p.stat().st_size > 0]
        if not files:
            return False
        for p in files:
            dst = FAILED / (p.name + ".gpg")
            _encrypt_file(p, dst)
            done += 1
            if not keep_plain:
                p.unlink()  # plaintext never lands on persistent storage
        (FAILED / (stem + ".json")).write_text(
            json.dumps({"stem": stem, "folder": folder, "date": date_iso,
                        "encrypted": True}),
            encoding="utf-8",
        )
        log.warning(
            "PARKED %s (%d file(s), encrypted) in %s — %s",
            stem, len(files), FAILED,
            "held until the push is confirmed" if keep_plain else "push failed, kept for retry",
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("could not park %s: %s: %s", stem, type(e).__name__, e)
        _bump("media_ingest_park_failures_total")
        if done:
            _write_sidecar(stem, folder, date_iso)
        return done > 0


def _unpark(stem: str) -> None:
    """Drop a parked copy once the gallery has confirmed the push. Media first,
    sidecar last: a sidecar without media is harmless, the reverse is not."""
    try:
        for p in ingest_metrics.stem_files(FAILED, stem):
            if p.suffix != ".json":
                p.unlink()
        side = FAILED / (stem + ".json")
        if side.exists():
            side.unlink()
    except OSError as e:
        log.warning("could not clear parked copy of %s: %s", stem, e)


def _open_staged(path):
    return open(path, "wb")


async def _capture_to_park(client, msg, stem: str, folder, date_iso: str, tee=None):
    """Stream the media from the source straight into gpg -> FAILED.

    Nothing here depends on STAGING, and nothing is held in memory beyond one
    chunk, which is why a full or broken staging dir can no longer lose an
    item. Returns (plaintext byte count, staged path or None); raises if no
    bytes arrived or gpg failed.

    tee=<staging path stem>: ALSO write each chunk to a staging file, so one
    fetch from the source yields both the durable ciphertext and the plaintext
    to push. Used for ephemeral media, which must never need a second fetch.
    A staging failure (full, read-only) only drops the tee; the ciphertext
    capture carries on.
    """
    FAILED.mkdir(parents=True, exist_ok=True)
    ext = tl_utils.get_extension(msg.media) or ""
    dst = FAILED / (stem + ext + ".gpg")
    part = FAILED / (stem + ext + ".gpg.part")
    staged = out = None
    if tee is not None:
        staged = tee.with_name(tee.name + ext)
        try:
            out = _open_staged(staged)
        except OSError as e:
            log.error("staging unusable for %s (%s: %s) — capturing ciphertext only",
                      stem, type(e).__name__, e)
            staged = out = None

    def drop_tee():
        nonlocal staged, out
        try:
            if out is not None:
                out.close()
        except OSError:
            pass
        try:
            if staged is not None and staged.exists():
                staged.unlink()
        except OSError:
            pass
        staged = out = None

    proc = await asyncio.create_subprocess_exec(
        "gpg", "--batch", "--yes", "--quiet", "--trust-model", "always",
        "--recipient", PARK_RECIPIENT, "--output", str(part), "--encrypt",
        stdin=asyncio.subprocess.PIPE,
    )
    n = 0
    try:
        async for chunk in client.iter_download(msg.media):
            proc.stdin.write(chunk)
            await proc.stdin.drain()
            if out is not None:
                try:
                    out.write(chunk)
                except OSError as e:
                    log.error("staging write failed for %s (%s: %s) — capturing "
                              "ciphertext only", stem, type(e).__name__, e)
                    drop_tee()
            n += len(chunk)
        proc.stdin.close()
        rc = await proc.wait()
        if out is not None:
            try:
                out.close()
                out = None
            except OSError as e:
                log.error("staging flush failed for %s (%s)", stem, e)
                drop_tee()
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        if part.exists():
            part.unlink()
        drop_tee()
        raise
    if rc != 0 or n == 0:
        if part.exists():
            part.unlink()
        drop_tee()
        raise RuntimeError(f"direct capture got {n} bytes, gpg rc={rc}")
    os.replace(part, dst)
    _write_sidecar(stem, folder, date_iso)
    log.warning("PARKED %s (%d bytes, encrypted%s) in %s",
                stem, n, "" if staged else ", captured without staging", FAILED)
    return n, staged


# Counters for the textfile collector. Process-lifetime; the alert rules look
# at increases, so a restart resetting them to zero is harmless.
_metrics = {
    "media_ingest_capture_failures_total": 0,   # a live capture did not reach the gallery
    "media_ingest_capture_lost_total": 0,       # ...and no copy of the bytes was kept at all
    "media_ingest_park_failures_total": 0,      # gpg park attempt failed
    "media_ingest_captures_total": 0,           # live captures pushed
    "media_ingest_slow_captures_total": 0,      # reached us > SLOW_CAPTURE_S after it was sent
}


def _write_metrics() -> None:
    used, size = ingest_metrics.staging_usage(STAGING)
    ingest_metrics.write("media_ingest_collector", {
        **_metrics,
        "media_ingest_collector_heartbeat_timestamp_seconds": ingest_metrics.now(),
        "media_ingest_staging_used_bytes": used,
        "media_ingest_staging_size_bytes": size,
        "media_ingest_parked_items": ingest_metrics.parked_count(FAILED),
    })


def _bump(name: str) -> None:
    _metrics[name] += 1
    _write_metrics()


def _drop_empty_staged(stem: str) -> None:
    """Remove zero-byte leftovers of a download that never wrote a byte. They
    carry no data, and left in place they make the next attempt pick a
    'stem (N)' name and pile up."""
    for p in ingest_metrics.stem_files(STAGING, stem):
        try:
            if p.is_file() and p.stat().st_size == 0:
                p.unlink()
        except OSError:
            pass


_inflight = set()   # stems being captured right now (NewMessage + MessageEdited race)
SLOW_CAPTURE_S = float(os.environ.get("TG_SLOW_CAPTURE_SECONDS", "60"))


def _write_sidecar(stem: str, folder, date_iso: str) -> None:
    """(Re)write a parked item's sidecar. folder may be None while the gallery
    has not been asked yet; the sweep then routes by the chat id in the stem."""
    try:
        FAILED.mkdir(parents=True, exist_ok=True)
        (FAILED / (stem + ".json")).write_text(
            json.dumps({"stem": stem, "folder": folder, "date": date_iso,
                        "encrypted": True}),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("could not write sidecar for %s: %s", stem, e)


async def handle(event):
    msg = event.message
    if getattr(msg, "out", False):
        return  # only media sent TO us, never our own
    if not getattr(event, "is_private", False):
        return  # private 1:1 chats only — skip group/channel floods
    kind = media_kind(msg)
    if not kind:
        return
    cid = event.chat_id
    stem = f"{cid}_{msg.id}"
    if stem in _seen or stem in _inflight:
        return
    # Cached ledger only. NOTHING that talks to the gallery may run before the
    # bytes are safe: those calls are synchronous and wait out the gateway
    # timeout when the gallery is down, which delayed each capture by minutes
    # -- long enough for disappearing media to be gone.
    if stem in _excluded:
        log.info("skip excluded stem=%s", stem)
        return
    _inflight.add(stem)
    # The sweep is a separate process working on the same files. Whoever holds
    # the item's lock owns it; the sweep parks on failure exactly as we do.
    lock = ingest_metrics.StemLock(STAGING, stem)
    if not lock.acquire():
        _inflight.discard(stem)
        log.info("stem=%s is being handled by the sweep — leaving it there", stem)
        return
    try:
        await _capture(event, msg, cid, stem, kind)
    finally:
        lock.release()
        _inflight.discard(stem)


async def _capture(event, msg, cid, stem, kind):
    date_iso = msg.date.isoformat() if msg.date else ""
    eph = " ephemeral" if ttl_of(getattr(msg, "media", None)) else ""
    # Delivery lag = how long Telegram took to hand us this update after the
    # message's own timestamp. This is the metric we're hunting: passive push can
    # be minutes; the active-pull loop should cap it near POLL_INTERVAL.
    lag_s = None
    if msg.date:
        now = dt.datetime.now(dt.timezone.utc)
        md = msg.date if msg.date.tzinfo else msg.date.replace(tzinfo=dt.timezone.utc)
        lag_s = (now - md).total_seconds()
    lag_str = f" lag={lag_s:.1f}s" if lag_s is not None else ""
    log.info("MEDIA%s from chat=%s stem=%s kind=%s%s", eph, cid, stem, kind, lag_str)
    if lag_s is not None and lag_s > SLOW_CAPTURE_S:
        _bump("media_ingest_slow_captures_total")

    tmp = STAGING / stem
    pushed = False
    held = False   # an encrypted copy exists in FAILED
    folder = None
    try:
        # 1) Bytes first.
        path = None
        direct = False
        if eph:
            # Ephemeral media is fetched exactly ONCE. That single stream is
            # written to the encrypted disk copy and to staging at the same
            # time, so no failure of staging, of the push or of the gallery
            # can leave it needing a second fetch the source may refuse.
            _n, staged = await _capture_to_park(event.client, msg, stem, None,
                                                date_iso, tee=tmp)
            held = True
            path = str(staged) if staged else None
            direct = path is None
        else:
            # Staging is a small tmpfs; if it is full, missing or read-only
            # the download fails or yields nothing. That used to be the end
            # of the item. Now it falls through to a capture that does not
            # use staging at all.
            try:
                path = await msg.download_media(file=str(tmp))
            except OSError as e:
                log.error("staging download failed %s: %s: %s — capturing without staging",
                          stem, type(e).__name__, e)
            if not path or os.path.getsize(path) == 0:
                path = None
                _drop_empty_staged(stem)
                await _capture_to_park(event.client, msg, stem, None, date_iso)
                held = direct = True

        # 2) Only now ask the gallery where it goes -- off the event loop, so a
        #    slow or dead gallery cannot stall the next capture either.
        chat = await event.get_chat()
        name = getattr(chat, "title", None) or getattr(chat, "first_name", None)
        folder = await asyncio.to_thread(folder_for, cid, name)
        await asyncio.to_thread(_refresh_excluded)
        if held:
            _write_sidecar(stem, folder, date_iso)
        if stem in _excluded:
            log.info("skip excluded stem=%s (dropped after capture)", stem)
            _unpark(stem)
            pushed = True   # earns the staging cleanup below
            return
        if direct:
            # The bytes are safe but only as ciphertext this host cannot read,
            # so this item needs the off-box key to finish. Count it as a
            # failed live capture so it alerts.
            _bump("media_ingest_capture_failures_total")
            return

        # 3) Push, also off the event loop (an upload can take minutes).
        await asyncio.to_thread(store_client.push_media, folder, path, stem, date_iso, False)
        _seen.add(stem)
        pushed = True
        log.info("PUSHED %s to gallery folder %s", stem, folder)
        _bump("media_ingest_captures_total")
        if held:
            _unpark(stem)
    except Exception as e:  # noqa: BLE001
        log.error("capture/push failed %s: %s: %s", stem, type(e).__name__, e)
        _bump("media_ingest_capture_failures_total")
        # Encrypt whatever is staged. The plaintext stays in the RAM-only
        # staging dir while there is room, so the next sweep can push it by
        # itself once the gallery answers; past that it is removed and the
        # ciphertext is the sole copy.
        used, size = ingest_metrics.staging_usage(STAGING)
        room = bool(size) and (used / size) < KEEP_PLAIN_BELOW
        if held:
            # The ciphertext already exists and is not rewritten. Only decide
            # whether the plaintext may stay in RAM for the sweep to push.
            _write_sidecar(stem, folder, date_iso)
            if not room:
                for p in ingest_metrics.stem_files(STAGING, stem):
                    try:
                        p.unlink()
                    except OSError:
                        pass
        elif not _park_failed(stem, folder, date_iso, keep_plain=room):
            # Nothing staged and nothing parked: try once more to pull the
            # bytes straight into the park before giving up on the item.
            try:
                await _capture_to_park(event.client, msg, stem, folder, date_iso)
            except Exception as e2:  # noqa: BLE001
                log.error("LOST %s%s: no copy could be captured (%s: %s)",
                          stem, eph, type(e2).__name__, e2)
                _bump("media_ingest_capture_lost_total")
    finally:
        # Only a successful push earns deletion; a failed one was just parked.
        if pushed:
            for p in ingest_metrics.stem_files(STAGING, stem):
                try:
                    p.unlink()
                except OSError:
                    pass
        else:
            _drop_empty_staged(stem)


async def main():
    # catch_up=True makes the source client request the missed-update difference on
    # (re)connect, so messages delivered while the daemon was down/reconnecting
    # are replayed through the NewMessage handler instead of being lost. This is
    # the live-path defense against restart/disconnect gaps; the periodic
    # reconcile sweep (reconcile.py) is the belt-and-suspenders backstop.
    client = SourceClient(SESSION, API_ID, API_HASH, catch_up=True)
    client.add_event_handler(handle, events.NewMessage(incoming=True))
    client.add_event_handler(handle, events.MessageEdited(incoming=True))
    await client.connect()
    if not await client.is_user_authorized():
        log.error("SESSION NOT AUTHORIZED — run login on this box first.")
        sys.exit(2)
    me = await client.get_me()
    log.info("Collector collector online as %s (id=%s). Listening...",
             getattr(me, "username", None) or getattr(me, "first_name", "?"), me.id)
    # sanity: confirm gallery auth works at startup
    try:
        global _excluded, _excluded_ts
        ex = store_client.get_excluded()
        # prime the cached ledger: handle() consults it without a network call
        _excluded = ex
        _excluded_ts = ingest_metrics.now()
        log.info("gallery auth OK; %d excluded stems", len(ex))
    except Exception as e:  # noqa: BLE001
        log.error("gallery auth FAILED at startup: %s", e)
    # one-time: seed the static chat-id map into folder_meta (single source of truth)
    _seed_static_chat_ids()
    # replay any updates missed while we were offline, then stream live
    try:
        await client.catch_up()
        log.info("catch_up complete — replayed any offline updates")
    except Exception as e:  # noqa: BLE001
        log.warning("catch_up failed (live stream still active): %s", e)

    # Active-pull backstop: Telegram's passive push to an idle secondary session
    # can lag minutes, which loses self-destruct/TTL media (purged server-side on
    # consume, unrecoverable by the history-based reconcile). Force a
    # getState+getDifference every POLL_INTERVAL seconds so pending updates are
    # pulled and replayed through the live handlers within ~POLL_INTERVAL,
    # independent of how badly Telegram deprioritizes native push.
    async def _poll_loop():
        if POLL_INTERVAL <= 0:
            log.info("active-pull poll DISABLED (TG_POLL_INTERVAL<=0)")
            return
        log.info("active-pull poll loop online (every %.0fs)", POLL_INTERVAL)
        last_beat = 0.0
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                await client.catch_up()
            except Exception as e:  # noqa: BLE001
                log.debug("poll catch_up failed (will retry): %s", e)
            # Heartbeat + gauges once a minute, so a hung collector or a
            # filling staging dir is visible without waiting for a capture.
            if ingest_metrics.now() - last_beat >= 60:
                last_beat = ingest_metrics.now()
                _write_metrics()

    poll_task = asyncio.ensure_future(_poll_loop())
    try:
        await client.run_until_disconnected()
    finally:
        poll_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
