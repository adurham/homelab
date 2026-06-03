#!/usr/bin/env python3
"""
One-time interactive login for the upstream source collector source client.

Creates the authorized .session file that collector.py then reuses headlessly.
Run this ONCE, interactively, on the LXC (it prompts for the login code that
upstream source sends to the existing app, and for the 2FA cloud password if set):

    sudo -u mediaingest TG_API_ID=... TG_API_HASH=... TG_SESSION=/var/lib/media-gallery/collector \
        /opt/media-gallery/venv/bin/python /opt/media-gallery/login.py

After it prints "Authorized as ...", the session is saved and the systemd
service can start. The session file is sensitive (it's a full login) — it
stays mode 0600 owned by the service user.
"""
import os
import sys

from telethon import TelegramClient as SourceClient

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-gallery/collector")
PHONE = os.environ.get("TG_PHONE")  # optional; source prompts if absent


def main() -> None:
    with SourceClient(SESSION, API_ID, API_HASH) as client:
        if PHONE:
            client.start(phone=PHONE)
        else:
            client.start()
        me = client.loop.run_until_complete(client.get_me())
        uname = getattr(me, "username", None) or getattr(me, "first_name", "?")
        print(f"Authorized as {uname} (id={getattr(me, 'id', '?')}).")
        print(f"Session saved to {SESSION}.session")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"Login failed: {e}", file=sys.stderr)
        sys.exit(1)
