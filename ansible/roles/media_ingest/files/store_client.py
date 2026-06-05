#!/usr/bin/env python3
"""
Gallery client — the collector's link to the gallery platform.

Auth: OAuth2 client_credentials against Authentik. We hold client_id +
client_secret, fetch a short-lived Bearer JWT from Authentik's token endpoint,
cache it until ~60s before expiry, and present it on every ingest call. No
crypt key, no GDrive token here — the gallery owns all of that.

API (all via lb-01 at GALLERY_BASE, path /ingest/*, JWT-validated by the gallery):
  push_media(folder, path, stem, date_iso, is_out) -> dict
      multipart upload of one media file with source metadata (stem preserves
      <chatid>_<msgid> identity; date + out flag carried through).
  mkdir(folder) -> dict
  get_excluded() -> set[str]   stems the user trashed/purged; skip re-capturing.

Env: AUTHENTIK_TOKEN_URL, COLLECTOR_CLIENT_ID, COLLECTOR_CLIENT_SECRET, GALLERY_BASE.
"""
import os
import threading
import time

import requests

TOKEN_URL = os.environ["AUTHENTIK_TOKEN_URL"]
CLIENT_ID = os.environ["COLLECTOR_CLIENT_ID"]
CLIENT_SECRET = os.environ["COLLECTOR_CLIENT_SECRET"]
GALLERY_BASE = os.environ.get("GALLERY_BASE", "https://gallery.chi.lab.amd-e.com").rstrip("/")
SCOPE = os.environ.get("COLLECTOR_SCOPE", "openid")
TIMEOUT = int(os.environ.get("GALLERY_HTTP_TIMEOUT", "120"))

_tok_lock = threading.Lock()
_token = {"value": None, "exp": 0.0}


def _get_token() -> str:
    with _tok_lock:
        now = time.time()
        if _token["value"] and now < _token["exp"] - 60:
            return _token["value"]
        r = requests.post(TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": SCOPE,
        }, timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
        _token["value"] = d["access_token"]
        _token["exp"] = now + int(d.get("expires_in", 3600))
        return _token["value"]


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}


def mkdir(folder: str) -> dict:
    r = requests.post(f"{GALLERY_BASE}/ingest/mkdir/{folder}",
                      headers=_auth_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def push_media(folder: str, path: str, stem: str, date_iso: str, is_out: bool) -> dict:
    """Upload one media file with source metadata to the gallery."""
    fname = os.path.basename(path)
    with open(path, "rb") as fh:
        files = {"files": (fname, fh)}
        data = {"stem": stem, "date": date_iso or "", "out": "1" if is_out else "0"}
        r = requests.post(f"{GALLERY_BASE}/ingest/upload/{folder}",
                          headers=_auth_headers(), files=files, data=data,
                          timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_excluded() -> set:
    r = requests.get(f"{GALLERY_BASE}/ingest/excluded",
                     headers=_auth_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return set(r.json().get("excluded", []))


def get_folder_meta() -> dict:
    """Fetch {folder: {cover, chat_ids}} so the collector can route chat-ids to
    user-mapped folders (rename-safe)."""
    r = requests.get(f"{GALLERY_BASE}/ingest/foldermeta",
                     headers=_auth_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    # self-test: token + excluded fetch
    print("token ok, len:", len(_get_token()))
    ex = get_excluded()
    print("excluded count:", len(ex))
