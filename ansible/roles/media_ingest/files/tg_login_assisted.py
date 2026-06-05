#!/usr/bin/env python3
"""
Assisted (non-interactive-stdin) source re-login for the collector.

Sources the values from the environment / a file instead of stdin prompts, so an
operator (or an assistant driving it over SSH) can supply them without a TTY:

  TG_PHONE      phone number in international format, e.g. +13125550123
  TG_2FA        2FA password (optional; omit/empty if no 2FA)
  TG_CODE_FILE  path this script POLLS for the login code the source sends
                (default /tmp/tg_code). Write the code into that file when it
                arrives; the script picks it up and finishes.

Flow: submit phone -> the source sends a code to the logged-in device -> write the
code to TG_CODE_FILE -> session authorized -> written to TG_SESSION.
"""
import os
import sys
import time

from telethon import TelegramClient

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-ingest/collector")
PHONE = os.environ.get("TG_PHONE", "").strip()
TFA = os.environ.get("TG_2FA", "")
CODE_FILE = os.environ.get("TG_CODE_FILE", "/tmp/tg_code")
CODE_WAIT_SEC = int(os.environ.get("TG_CODE_WAIT_SEC", "300"))


def _phone():
    if not PHONE:
        print("ERROR: TG_PHONE not set", flush=True)
        sys.exit(2)
    print(f"PHONE_SUBMITTED {PHONE}", flush=True)
    return PHONE


def _code():
    # poll CODE_FILE until it has a non-empty value (the operator writes it)
    print(f"WAITING_FOR_CODE in {CODE_FILE}", flush=True)
    deadline = time.time() + CODE_WAIT_SEC
    while time.time() < deadline:
        try:
            with open(CODE_FILE) as f:
                v = f.read().strip()
            if v:
                print("CODE_RECEIVED", flush=True)
                return v
        except OSError:
            pass
        time.sleep(2)
    print("ERROR: timed out waiting for code", flush=True)
    sys.exit(3)


def _password():
    return TFA


def main():
    # start fresh: remove any stale code file
    try:
        os.remove(CODE_FILE)
    except OSError:
        pass
    client = TelegramClient(SESSION, API_ID, API_HASH)
    client.start(phone=_phone, code_callback=_code,
                 password=(_password if TFA else None))
    if client.loop.run_until_complete(client.is_user_authorized()):
        me = client.loop.run_until_complete(client.get_me())
        uname = getattr(me, "username", None) or getattr(me, "first_name", "?")
        print(f"AUTHORIZED {uname} id={me.id}", flush=True)
        client.disconnect()
        # clean up the code file (don't leave the code on disk)
        try:
            os.remove(CODE_FILE)
        except OSError:
            pass
        return 0
    print("FAILED not authorized", flush=True)
    client.disconnect()
    return 1


if __name__ == "__main__":
    sys.exit(main())
