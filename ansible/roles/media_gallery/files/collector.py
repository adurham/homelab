#!/usr/bin/env python3
"""
upstream source ephemeral / ephemeral media collector (source client, the source protocol).

Mechanism: a ephemeral media blob lives on upstream source's servers only between
delivery and the moment a client sends the view receipt
(messages.readMessageContents). This source client listens in real time and, the
instant an ephemeral message arrives, downloads the bytes via getFile WITHOUT
ever sending a read receipt. Result: an invisible, non-destructive capture —
the copy on the user's phone stays intact and unopened.

Capture chain (degrades gracefully):
  1. silent full-resolution download  (primary; non-destructive)
  2. largest available thumbnail      (fallback if full-res returns empty)
  3. Discord alert "capture failed"   (last resort, so nothing slips silently)

Secret-chat (E2E) ephemeral media is NOT reachable by source and is
deliberately out of scope.

Config is read from environment (see collector.env / systemd EnvironmentFile).
Captured files land in SAVE_DIR; a separate sync timer encrypts+ships them to
Google Drive via rclone crypt and prunes the local cache.
"""

import asyncio
import datetime as dt
import logging
import os
import sys
import urllib.request
from pathlib import Path

from telethon import TelegramClient as SourceClient, events
from telethon.tl.types import (
    MessageMediaPhoto,
    MessageMediaDocument,
)

# ─── Config from environment ──────────────────────────────────────────────
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-gallery/collector")
SAVE_DIR = Path(os.environ.get("TG_SAVE_DIR", "/var/lib/media-gallery/captures"))
LOG_FILE = os.environ.get("TG_LOG_FILE", "/var/log/media-gallery/collector.log")
DISCORD_WEBHOOK = os.environ.get("TG_DISCORD_WEBHOOK", "").strip()

SAVE_DIR.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

# ─── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("collector")
# source is chatty at INFO; keep it at WARNING so our lines stand out.
logging.getLogger("telethon").setLevel(logging.WARNING)


def discord_alert(text: str) -> None:
    """Fire-and-forget Discord webhook ping. Never raises into the event loop."""
    if not DISCORD_WEBHOOK:
        return
    try:
        import json

        data = json.dumps({"content": text}).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:  # noqa: BLE001 - alert path must never crash capture
        log.warning("discord alert failed: %s", e)


def ttl_of(media) -> int | None:
    """Return ttl_seconds if this media is ephemeral/ephemeral, else None."""
    if isinstance(media, (MessageMediaPhoto, MessageMediaDocument)):
        ttl = getattr(media, "ttl_seconds", None)
        if ttl:
            return ttl
    return None


async def sender_tag(event) -> str:
    """Human-ish identifier for the sender, for filenames + alerts."""
    try:
        s = await event.get_sender()
        if s is None:
            return "unknown"
        uname = getattr(s, "username", None)
        if uname:
            return uname
        first = getattr(s, "first_name", "") or ""
        last = getattr(s, "last_name", "") or ""
        name = (first + last).strip().replace(" ", "")
        return name or f"id{getattr(s, 'id', 'unknown')}"
    except Exception:  # noqa: BLE001
        return "unknown"


async def handle(event) -> None:
    msg = event.message
    media = getattr(msg, "media", None)
    if media is None:
        return
    ttl = ttl_of(media)
    if not ttl:
        return  # not ephemeral; ignore

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = await sender_tag(event)
    stem = SAVE_DIR / f"{ts}_{tag}_ttl{ttl}"
    log.info("EPHEMERAL detected: from=%s ttl=%ss msg_id=%s", tag, ttl, msg.id)

    # 1) silent full-resolution download (no read receipt is ever sent)
    try:
        path = await msg.download_media(file=str(stem))
        if path and os.path.getsize(path) > 0:
            log.info("CAPTURED full-res -> %s (%d bytes)", path, os.path.getsize(path))
            discord_alert(f"\U0001f4f8 Captured ephemeral from {tag} -> {os.path.basename(path)}")
            return
        log.warning("full-res download returned empty for msg_id=%s", msg.id)
    except Exception as e:  # noqa: BLE001
        log.warning("full-res download failed msg_id=%s: %s", msg.id, e)

    # 2) thumbnail fallback (largest available)
    try:
        path = await msg.download_media(file=str(stem) + "_thumb", thumb=-1)
        if path and os.path.getsize(path) > 0:
            log.info("CAPTURED thumbnail -> %s (%d bytes)", path, os.path.getsize(path))
            discord_alert(f"\u26a0\ufe0f Only thumbnail captured for ephemeral from {tag}")
            return
    except Exception as e:  # noqa: BLE001
        log.warning("thumbnail download failed msg_id=%s: %s", msg.id, e)

    # 3) total miss
    log.error("CAPTURE FAILED for ephemeral from %s msg_id=%s", tag, msg.id)
    discord_alert(f"\u274c FAILED to capture ephemeral from {tag} (msg {msg.id})")


async def main() -> None:
    client = SourceClient(SESSION, API_ID, API_HASH)
    # incoming=True: only messages received, not ones we send.
    client.add_event_handler(handle, events.NewMessage(incoming=True))
    # Catch ephemeral that arrive as edits (rare, but cheap to cover).
    client.add_event_handler(handle, events.MessageEdited(incoming=True))

    await client.connect()
    if not await client.is_user_authorized():
        log.error(
            "SESSION NOT AUTHORIZED. Run the one-time login (login.py) to create "
            "%s.session before starting the service.",
            SESSION,
        )
        sys.exit(2)

    me = await client.get_me()
    log.info(
        "Collector online as %s (id=%s). Listening for ephemeral media...",
        getattr(me, "username", None) or getattr(me, "first_name", "?"),
        getattr(me, "id", "?"),
    )
    discord_alert("\U0001f7e2 media-gallery online and listening")
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
