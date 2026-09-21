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
    flight. `.len` is a LIVE property (bytes remaining), mirroring
    requests_toolbelt's own FileWrapper.len — MultipartEncoder's write loop
    (Part.write_to) polls total_len(body) on every iteration expecting it to
    shrink toward zero as bytes are consumed; a static `.len` that never
    changes makes that loop spin forever (caught in local testing before
    deploy: a 100-byte test file hung indefinitely). The one-time-total used
    for the overall Content-Length calculation is captured separately and
    correctly by MultipartEncoder itself (Part.__init__ snapshots
    total_len(body) once, at construction, before any reads happen) — this
    property only needs to satisfy the write loop's PROGRESS check, not
    restate the original total.

    Preventing a live file from growing past its snapshotted size also
    protects against desyncing the promised Content-Length vs. actual bytes
    sent, e.g. if the caller's stability-gate race (see scraper_wrapper.py's
    _walk_and_push .part-suffix exclusion, added alongside this fix for the
    same underlying scenario) ever let a still-being-written file through.
    """

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
    requests' files= kwarg. Root-caused 2026-09-21: requests' own multipart
    path (RequestEncodingMixin._encode_files) does fdata = fp.read() — reads
    the ENTIRE file into one bytes blob — then urllib3's
    encode_multipart_formdata() copies it AGAIN into a joined BytesIO before
    the request is sent. For a multi-GB video that's ~2x the file size in
    transient process heap on top of the file already resident in the (tmpfs)
    staging dir. Confirmed via the Proxmox host's own kernel OOM report for
    this exact failure (`journalctl -k`, not just the guest's systemd log):
    the killed task was this wrapper's own "python" PID with
    anon-rss ~15.7-16GB / shmem-rss:0 (i.e. process HEAP, not the tmpfs file)
    at the moment a ~9.3GB video was being pushed, and the cgroup's own
    memory.stat showed shmem (~8.4GB, the tmpfs file) + anon (~16GB, this
    double-buffered copy) together exactly exhausting the 24GB memory.max —
    both contributors, stacking. MultipartEncoder computes Content-Length via
    fstat and streams .read() in bounded chunks, so process RSS stays flat
    regardless of file size. allow_redirects=False because a streamed body
    can't be replayed on a redirect (requests would silently send an empty
    body on 307/308 or drop to GET on 301/302) — a redirect here means
    GALLERY_BASE or the ingest path is misconfigured and should fail loudly,
    not silently corrupt an upload.
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
