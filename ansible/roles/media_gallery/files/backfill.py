#!/usr/bin/env python3
"""
One-shot bulk backfill: pull all photos/videos from every chat and ship them
to Google Drive (encrypted), reusing the collector's session + rclone crypt.

This is SEPARATE from the live daemon (collector.py). It walks history; the
daemon watches the future.

Modes:
  --count            Enumerate only. Per-dialog photo/video totals + grand
                     total. Cheap (server-side counts, downloads nothing).
                     Use this first to size the job.
  --run              Actually download. STREAMING + RESUMABLE + THROTTLED:
                       * downloads into SAVE_DIR/backfill in batches
                       * after each batch: rclone move -> crypt remote, prune
                         local (so the 8GB disk never fills)
                       * checkpoints last-processed message id per dialog in
                         a JSON state file, so an interrupted run resumes
                         instead of restarting
                       * respects source FloodWait automatically; --sleep
                         adds a gentle inter-download pause

Env (shares the daemon's config):
  TG_API_ID, TG_API_HASH, TG_SESSION   - same session as the live collector
  TG_SAVE_DIR                          - base dir; backfill uses <dir>/backfill
  TG_RCLONE_REMOTE                     - e.g. gcrypt: (crypt remote)
  RCLONE_CONFIG                        - path to rclone.conf
  TG_BACKFILL_STATE                    - checkpoint json (default alongside session)

Flags:
  --batch N      files per upload flush (default 40)
  --sleep S      seconds to sleep between downloads (default 0.5)
  --dialogs ...  optional: restrict to dialog name substrings (space-sep)
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from telethon import TelegramClient as SourceClient
from telethon.tl.types import InputMessagesFilterPhotoVideo

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-gallery/collector")
SAVE_BASE = Path(os.environ.get("TG_SAVE_DIR", "/var/lib/media-gallery/captures"))
BACKFILL_DIR = SAVE_BASE / "backfill"
REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediaingest/.config/rclone/rclone.conf")
STATE_FILE = os.environ.get("TG_BACKFILL_STATE", SESSION + ".backfill.json")
EXCLUDE_FILE = os.environ.get("TG_EXCLUDE_FILE", "/var/lib/media-gallery/excluded.json")


def _load_excluded() -> set:
    try:
        with open(EXCLUDE_FILE) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


# Stems the user trashed — never re-download them on backfill re-runs.
EXCLUDED = _load_excluded()


def log(*a):
    print(*a, flush=True)


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def sanitize(name: str) -> str:
    """Filesystem-safe folder name from a chat title."""
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in (name or "")).strip()
    keep = keep.replace(" ", "-")
    return keep or "unknown"


def flush_to_remote() -> None:
    """rclone move the backfill dir to the crypt remote, preserving the
    per-chat subfolder structure, pruning local. Files are downloaded into
    BACKFILL_DIR/<ChatName>/ so the destination ends up organized as
    gcrypt:by-chat/<ChatName>/."""
    if not any(BACKFILL_DIR.iterdir()):
        return
    cmd = [
        "rclone", "--config", RCLONE_CONF, "move", str(BACKFILL_DIR), REMOTE + "by-chat",
        "--transfers", "8", "--checkers", "16",
        # Dedicated OAuth client_id = private quota bucket (1B queries/day),
        # so the old --tpslimit 8 (sized for the shared-client 403s) is gone.
        "--retries", "10", "--low-level-retries", "20",
        "--delete-empty-src-dirs",
        "--log-level", "NOTICE",
    ]
    subprocess.run(cmd, check=True)


async def do_count(client, name_filters):
    dialogs = await client.get_dialogs()
    grand = 0
    rows = []
    for d in dialogs:
        if name_filters and not any(nf.lower() in (d.name or "").lower() for nf in name_filters):
            continue
        try:
            res = await client.get_messages(d.entity, limit=0, filter=InputMessagesFilterPhotoVideo)
            total = res.total
        except Exception as e:  # noqa: BLE001
            log(f"  (skip {d.name!r}: {type(e).__name__})")
            continue
        if total:
            rows.append((total, d.name or str(d.id)))
            grand += total
    rows.sort(reverse=True)
    log("\n=== photo/video counts per chat (non-zero) ===")
    for total, name in rows:
        log(f"  {total:6d}  {name}")
    log(f"\nGRAND TOTAL photos+videos across {len(rows)} chats: {grand}")
    log("(run with --run to download; it's streaming, resumable, throttled)")


async def do_run(client, name_filters, batch, sleep_s):
    BACKFILL_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    dialogs = await client.get_dialogs()
    pending = 0
    grabbed = 0
    for d in dialogs:
        if name_filters and not any(nf.lower() in (d.name or "").lower() for nf in name_filters):
            continue
        key = str(d.id)
        last_done = state.get(key, 0)
        max_seen = last_done
        chat_folder = BACKFILL_DIR / sanitize(d.name)
        chat_folder.mkdir(parents=True, exist_ok=True)
        log(f"\n--- {d.name!r} -> {chat_folder.name}/ (resuming after msg_id {last_done}) ---")
        try:
            async for msg in client.iter_messages(
                d.entity, filter=InputMessagesFilterPhotoVideo,
                min_id=last_done, reverse=True,  # oldest->newest so checkpoint is monotonic
            ):
                if not msg.media:
                    continue
                # only media sent TO us, and not something the user trashed
                if getattr(msg, "out", False):
                    max_seen = max(max_seen, msg.id)
                    continue
                if f"{d.id}_{msg.id}" in EXCLUDED:
                    max_seen = max(max_seen, msg.id)
                    continue
                stem = chat_folder / f"{d.id}_{msg.id}"
                try:
                    path = await msg.download_media(file=str(stem))
                    if path:
                        grabbed += 1
                        pending += 1
                except Exception as e:  # noqa: BLE001
                    log(f"   dl fail msg {msg.id}: {type(e).__name__}: {e}")
                max_seen = max(max_seen, msg.id)
                if sleep_s:
                    await asyncio.sleep(sleep_s)
                if pending >= batch:
                    flush_to_remote()
                    state[key] = max_seen
                    save_state(state)
                    log(f"   flushed batch; checkpoint {d.name!r}@{max_seen} (total grabbed {grabbed})")
                    pending = 0
        except Exception as e:  # noqa: BLE001
            log(f"   chat error {d.name!r}: {type(e).__name__}: {e}")
        # end of dialog: flush remainder + checkpoint
        flush_to_remote()
        state[key] = max_seen
        save_state(state)
        pending = 0
    log(f"\nBACKFILL COMPLETE. total files grabbed this run: {grabbed}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--dialogs", nargs="*", default=[])
    args = ap.parse_args()

    client = SourceClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log("SESSION NOT AUTHORIZED — run login first.")
        sys.exit(2)

    if args.count:
        await do_count(client, args.dialogs)
    elif args.run:
        await do_run(client, args.dialogs, args.batch, args.sleep)
    else:
        log("specify --count or --run")
        sys.exit(2)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
