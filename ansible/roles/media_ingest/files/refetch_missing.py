#!/usr/bin/env python3
"""Re-fetch specific items by message id and push them to the gallery.

The live collector has no "retry this one item" entry point: an item whose
capture stalled or failed is either parked as ciphertext (sweep drains it) or —
if the fetch never returned — simply absent, with nothing to retry. This script
closes that gap for a named list of message ids.

Identity-free by design: the chat id, gallery folder and message ids all come
from the environment, never from this file (public repo rule).

Run it as the service user with the unit's own env, and point TG_REFETCH_SESSION
at a COPY of the collector session (the collector may hold the original):

  sudo -u mediaingest env $(grep -v '^#' /opt/media-ingest/collector.env \
      | grep = | xargs -d '\n') \
    TG_REFETCH_SESSION=/var/lib/media-ingest/refetch.session \
    RF_CHAT=<chat-id> RF_FOLDER=<folder> RF_IDS=<id>,<id> \
    /opt/media-ingest/venv/bin/python /opt/media-ingest/refetch_missing.py

Copy the session while the collector is stopped (cp collector.session
refetch.session, chmod 600, same owner), start the collector again, then run —
and delete the copy afterwards. Output is one line per id: PUSHED / SKIP /
FAIL, so it can be read without grepping a log.
"""
import asyncio
import os
import sys

sys.path.insert(0, "/opt/media-ingest")
from telethon import TelegramClient  # noqa: E402

import store_client  # noqa: E402

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_REFETCH_SESSION"]
STAGING = os.environ.get("TG_STAGING", "/var/lib/media-ingest/staging")
CHAT = int(os.environ.get("RF_CHAT", "0"))
FOLDER = os.environ.get("RF_FOLDER", "")
IDS = [int(x) for x in os.environ.get("RF_IDS", "").split(",") if x.strip()]


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("NOT AUTHORIZED")
        return 1
    ent = await client.get_entity(CHAT)
    for mid in IDS:
        stem = str(CHAT) + "_" + str(mid)
        got = await client.get_messages(ent, ids=mid)
        msg = got[0] if isinstance(got, list) else got
        if not msg or not msg.media:
            print("SKIP " + stem + ": no media on message")
            continue
        tmp = os.path.join(STAGING, "rf_" + stem)
        path = await msg.download_media(file=tmp)
        if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
            print("FAIL " + stem + ": empty download")
            continue
        size = os.path.getsize(path)
        date_iso = msg.date.isoformat() if msg.date else ""
        try:
            store_client.push_media(FOLDER, path, stem, date_iso, False)
            print("PUSHED " + stem + " (" + str(size) + " bytes) -> " + FOLDER)
        except Exception as e:  # noqa: BLE001
            print("FAIL " + stem + ": " + type(e).__name__ + ": " + str(e))
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        await asyncio.sleep(0.5)
    await client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
