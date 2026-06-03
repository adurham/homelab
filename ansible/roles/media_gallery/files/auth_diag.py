#!/usr/bin/env python3
"""
Observable two-phase login for the collector source client.

Phase 1 (--send):  connect, send_code_request, report WHERE upstream source sent the
                   code (app / sms / call / flashcall), persist the phone_code_hash.
Phase 2 (--code N): submit the code (and 2FA password if needed) to finish.

State (phone_code_hash) is stashed next to the session so phase 2 can resume.
Everything prints unbuffered to stdout so it's pollable over SSH.
"""
import os
import sys
import json
import asyncio

from telethon import TelegramClient as SourceClient
from telethon.errors import SessionPasswordNeededError

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-gallery/collector")
PHONE = os.environ["TG_PHONE"]
STATE = SESSION + ".loginstate.json"


def out(d):
    print(json.dumps(d), flush=True)


async def send():
    client = SourceClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if await client.is_user_authorized():
        out({"status": "already_authorized"})
        await client.disconnect()
        return
    sent = await client.send_code_request(PHONE)
    typ = type(sent.type).__name__
    nxt = type(sent.next_type).__name__ if sent.next_type else None
    with open(STATE, "w") as f:
        json.dump({"phone_code_hash": sent.phone_code_hash}, f)
    out({"status": "code_sent", "via": typ, "next_type": nxt})
    await client.disconnect()


async def submit(code, password=None):
    with open(STATE) as f:
        pch = json.load(f)["phone_code_hash"]
    client = SourceClient(SESSION, API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(PHONE, code=code, phone_code_hash=pch)
    except SessionPasswordNeededError:
        if not password:
            out({"status": "needs_2fa_password"})
            await client.disconnect()
            return
        await client.sign_in(password=password)
    me = await client.get_me()
    out({
        "status": "authorized",
        "user": getattr(me, "username", None) or getattr(me, "first_name", "?"),
        "id": getattr(me, "id", None),
    })
    await client.disconnect()
    try:
        os.remove(STATE)
    except OSError:
        pass


def main():
    if "--send" in sys.argv:
        asyncio.get_event_loop().run_until_complete(send())
    elif "--code" in sys.argv:
        i = sys.argv.index("--code")
        code = sys.argv[i + 1]
        pw = None
        if "--password" in sys.argv:
            pw = sys.argv[sys.argv.index("--password") + 1]
        elif "--password-stdin" in sys.argv:
            # Read 2FA password from stdin so it never appears in argv/ps.
            pw = sys.stdin.readline().rstrip("\n")
        asyncio.get_event_loop().run_until_complete(submit(code, pw))
    else:
        out({"status": "error", "msg": "need --send or --code N"})
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        out({"status": "error", "type": type(e).__name__, "msg": str(e)})
        sys.exit(1)
