#!/usr/bin/env python3
"""
One-time interactive source login for the media-ingest collector.

Re-authorizes the source session file the collector uses (TG_SESSION). Run this
when the session gets revoked/expired (collector logs "SESSION NOT AUTHORIZED").

Usage (on the media-ingest CT, as the mediaingest user, with collector.env loaded):
    set -a; . /opt/media-ingest/collector.env; set +a
    /opt/media-ingest/venv/bin/python /opt/media-ingest/tg_login.py

It will prompt for the phone number, the login code the source sends, and (if set)
your 2FA password. On success it writes an authorized session to TG_SESSION and
exits; then start the collector service.
"""
import os
import sys

from telethon import TelegramClient

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-ingest/collector")


def main():
    print(f"Session file: {SESSION}.session")
    client = TelegramClient(SESSION, API_ID, API_HASH)
    # .start() runs the full interactive flow: phone -> code -> (2FA password)
    client.start()
    if client.loop.run_until_complete(client.is_user_authorized()):
        me = client.loop.run_until_complete(client.get_me())
        uname = getattr(me, "username", None) or getattr(me, "first_name", "?")
        print(f"\nOK — authorized as {uname} (id={me.id}). Session written.")
        print("Now start the collector:  systemctl start media-ingest-collector")
        client.disconnect()
        return 0
    print("\nFAILED — still not authorized.", file=sys.stderr)
    client.disconnect()
    return 1


if __name__ == "__main__":
    sys.exit(main())
