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


class _SizeBoundedReader:
    """File-like wrapper that snapshots a file's size at construction and will
    never read past that many bytes, even if the underlying file keeps
    growing while a (potentially many-minutes-long, multi-GB) upload is in
    flight. `.len` is a LIVE property (bytes remaining) -- MultipartEncoder's
    write loop polls it every iteration expecting it to shrink toward zero; a
    static `.len` hangs the loop forever (caught in local testing before
    deploy). Same fix as media_ingest_02's store_client.py -- see that copy's
    push_media docstring for the full incident writeup (2026-09-21 OOM
    root-cause) and this class's docstring for why `.len` must be live."""

    def __init__(self, fh, size):
        self._fh = fh
        self._remaining = size

    @property
    def len(self):
        return self._remaining

    def read(self, n=-1):
        if self._remaining <= 0:
            return b""
        if n is None or n < 0:
            n = self._remaining
        n = min(n, self._remaining)
        data = self._fh.read(n)
        self._remaining -= len(data)
        return data


def push_media(folder: str, path: str, stem: str, date_iso: str, is_out: bool) -> dict:
    """Upload one media file with source metadata to the gallery.

    STREAMS the body (requests_toolbelt.MultipartEncoder) instead of using
    requests' files= kwarg, which double-buffers the entire file in process
    heap (fp.read() in requests, then a second copy in urllib3's joined
    BytesIO) — confirmed via a live OOM on media-ingest-02's identical copy
    of this function pushing a ~9.3GB video (2026-09-21; see that role's
    store_client.py for the full incident writeup). This CT currently runs
    with only 1GB of memory and smaller typical capture sizes, so the bug was
    latent here, but the code path is identical — fixed proactively rather
    than waiting for this box to hit the same wall.
    """
    from requests_toolbelt.multipart.encoder import MultipartEncoder

    fname = os.path.basename(path)
    size = os.stat(path).st_size
    with open(path, "rb") as fh:
        reader = _SizeBoundedReader(fh, size)
        m = MultipartEncoder(fields={
            "stem": stem,
            "date": date_iso or "",
            "out": "1" if is_out else "0",
            "files": (fname, reader, "application/octet-stream"),
        })
        r = requests.post(f"{GALLERY_BASE}/ingest/upload/{folder}",
                          headers={**_auth_headers(), "Content-Type": m.content_type},
                          data=m, timeout=TIMEOUT, allow_redirects=False)
    if 300 <= r.status_code < 400:
        raise RuntimeError(
            f"push_media got redirect {r.status_code} for {stem} -- streamed "
            f"body can't be replayed; check GALLERY_BASE/ingest path for a "
            f"trailing-slash mismatch rather than retrying"
        )
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


def set_chat_ids(folder: str, chat_ids: list) -> dict:
    """Map source chat-ids to a folder in folder_meta (the single source of
    truth). Used to seed the static map into folder_meta on first run."""
    r = requests.post(f"{GALLERY_BASE}/ingest/setchatids",
                      headers={**_auth_headers(), "Content-Type": "application/json"},
                      json={"folder": folder, "chat_ids": [str(c) for c in chat_ids]},
                      timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    # self-test: token + excluded fetch
    print("token ok, len:", len(_get_token()))
    ex = get_excluded()
    print("excluded count:", len(ex))
