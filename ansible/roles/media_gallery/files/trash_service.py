#!/usr/bin/env python3
"""
Trash service for the TG gallery — write-capable, deletes media and remembers
it so it never comes back.

POST /trash/<chat>/<stem>
  1. delete the original  gcrypt:by-chat/<chat>/<stem>.<ext>
  2. delete the thumbnail gcrypt:thumbs/<chat>/<stem>.jpg + local tmpfs copy
  3. append <stem> to the EXCLUSION LEDGER so backfill / manifest / collector
     skip it forever (no re-download)

The ledger lives at /var/lib/media-gallery/excluded.json (persistent local —
NOT tmpfs, must survive reboot) and is mirrored to gcrypt:gallery/excluded.json
(encrypted, for backup). All readers (build_manifest, backfill, collector) load
the local copy.

Auth: none here — gated by Authentik forward-auth at lb-01 (POST /trash/),
bound to the private IP so nginx can reach it.

Env: RCLONE_CONFIG, TG_RCLONE_REMOTE (default gcrypt:), TRASH_PORT (8091),
     TRASH_BIND (172.16.0.51), THUMB_LOCAL_CACHE, TG_EXCLUDE_FILE.
"""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediaingest/.config/rclone/rclone.conf")
PORT = int(os.environ.get("TRASH_PORT", "8091"))
BIND = os.environ.get("TRASH_BIND", "172.16.0.51")
THUMB_CACHE = Path(os.environ.get("THUMB_LOCAL_CACHE", "/var/lib/media-gallery/thumbcache"))
EXCLUDE_FILE = Path(os.environ.get("TG_EXCLUDE_FILE", "/var/lib/media-gallery/excluded.json"))
SRC = REMOTE + "by-chat"
THUMBS = REMOTE + "thumbs"
EXCLUDE_REMOTE = REMOTE + "gallery/excluded.json"

_lock = threading.Lock()


def rclone(*args):
    return subprocess.run(["rclone", "--config", RCLONE_CONF, *args],
                          capture_output=True, text=True)


def load_excluded() -> set:
    try:
        return set(json.loads(EXCLUDE_FILE.read_text()))
    except (OSError, ValueError):
        return set()


def save_excluded(s: set) -> None:
    EXCLUDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(EXCLUDE_FILE) + ".tmp"
    Path(tmp).write_text(json.dumps(sorted(s)))
    os.replace(tmp, EXCLUDE_FILE)
    # mirror to Drive (encrypted) for backup; best-effort
    rclone("copyto", str(EXCLUDE_FILE), EXCLUDE_REMOTE)


def find_original_leaf(chat, stem):
    r = rclone("lsf", f"{SRC}/{chat}/")
    for line in r.stdout.splitlines():
        leaf = line.strip()
        if leaf.startswith(stem + "."):
            return leaf
    return None


def trash_item(chat, stem) -> dict:
    with _lock:
        result = {"stem": stem, "chat": chat, "deleted": [], "errors": []}
        leaf = find_original_leaf(chat, stem)
        if leaf:
            r = rclone("deletefile", f"{SRC}/{chat}/{leaf}")
            (result["deleted"] if r.returncode == 0 else result["errors"]).append(f"original:{leaf}")
        # thumb on Drive
        r = rclone("deletefile", f"{THUMBS}/{chat}/{stem}.jpg")
        if r.returncode == 0:
            result["deleted"].append("thumb")
        # local tmpfs thumb
        try:
            (THUMB_CACHE / chat / f"{stem}.jpg").unlink()
        except OSError:
            pass
        # Only touch the ledger if we actually deleted the original — avoids a
        # bad/typo request polluting the exclusion list (which would
        # permanently block a stem that was never really ours to trash).
        if any(d.startswith("original:") for d in result["deleted"]):
            ex = load_excluded()
            ex.add(stem)
            save_excluded(ex)
            result["excluded_total"] = len(ex)
            _trigger_manifest_rebuild()
        else:
            result["excluded_total"] = len(load_excluded())
            result["note"] = "original not found; not added to ledger"
        return result


def _trigger_manifest_rebuild():
    """Rebuild the manifest (fast, cached date map) in the background so the
    on-disk manifest stays consistent after a delete. The SPA already drops the
    tile client-side; this keeps a fresh page-load correct without waiting for
    the hourly refresh. Fire-and-forget; never blocks the HTTP response."""
    here = os.path.dirname(os.path.abspath(__file__))
    py = os.path.join(here, "venv", "bin", "python")
    if not os.path.exists(py):
        py = "python3"
    env = dict(os.environ)
    env.setdefault("RCLONE_CONFIG", RCLONE_CONF)
    env.setdefault("TG_RCLONE_REMOTE", REMOTE)
    try:
        subprocess.Popen(
            [py, os.path.join(here, "build_manifest.py"), "--fast"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        p = unquote(self.path)
        if not p.startswith("/trash/"):
            self._json(404, {"error": "not found"})
            return
        rest = p[len("/trash/"):]
        if "/" not in rest:
            self._json(400, {"error": "bad path, want /trash/<chat>/<stem>"})
            return
        chat, stem = rest.split("/", 1)
        if ".." in chat or ".." in stem or "/" in stem:
            self._json(400, {"error": "bad chars"})
            return
        try:
            self._json(200, trash_item(chat, stem))
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"trash service on {BIND}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
