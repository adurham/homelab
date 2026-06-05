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
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediagallery/.config/rclone/rclone.conf")
PORT = int(os.environ.get("TRASH_PORT", "8091"))
BIND = os.environ.get("TRASH_BIND", "172.16.0.46")
THUMB_CACHE = Path(os.environ.get("THUMB_LOCAL_CACHE", "/var/lib/media-gallery/thumbcache"))
EXCLUDE_FILE = Path(os.environ.get("TG_EXCLUDE_FILE", "/var/lib/media-gallery/excluded.json"))
# Persistent queue of {chat,stem} the user has marked for deletion. The HTTP
# request only appends here + to the exclusion ledger (instant); a background
# reaper thread does the actual rclone deletes. Survives restarts.
QUEUE_FILE = Path(os.environ.get("TG_DELETE_QUEUE", "/var/lib/media-gallery/pending_delete.json"))
SRC = REMOTE + "by-chat"
THUMBS = REMOTE + "thumbs"
EXCLUDE_REMOTE = REMOTE + "gallery/excluded.json"

_lock = threading.Lock()
_qlock = threading.Lock()
# live counters for /trashqueue (reset on restart; queued is recomputed from file)
_reaper_state = {"reaped": 0, "failed": 0}


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
    # mirror to Drive (encrypted) for backup in a BACKGROUND thread — a slow
    # Drive (e.g. a big video download in flight) must not block the HTTP
    # response. The local ledger is the source of truth; the mirror is backup.
    threading.Thread(
        target=lambda: rclone("copyto", str(EXCLUDE_FILE), EXCLUDE_REMOTE),
        daemon=True,
    ).start()


# ── pending-delete queue (instant mark + background reaper) ──────────────────
def load_queue() -> list:
    try:
        return json.loads(QUEUE_FILE.read_text())
    except (OSError, ValueError):
        return []


def save_queue(items: list) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(QUEUE_FILE) + ".tmp"
    Path(tmp).write_text(json.dumps(items))
    os.replace(tmp, QUEUE_FILE)


def enqueue_deletes(chat: str, stems: list) -> int:
    """Append {chat,stem} entries to the persistent queue. Instant — no rclone."""
    with _qlock:
        q = load_queue()
        have = {(e.get("chat"), e.get("stem")) for e in q}
        added = 0
        for s in stems:
            if (chat, s) not in have:
                q.append({"chat": chat, "stem": s})
                added += 1
        save_queue(q)
    return added


def _reap_one(entry) -> bool:
    """Do the actual rclone delete for a single queued entry. Returns True on
    success (or if the file was already gone)."""
    chat, stem = entry.get("chat"), entry.get("stem")
    ok = True
    leaf = find_original_leaf(chat, stem)
    if leaf:
        r = rclone("deletefile", f"{SRC}/{chat}/{leaf}",
                   "--retries", "3", "--low-level-retries", "5")
        ok = (r.returncode == 0)
    # thumbnail (best effort — never blocks success)
    rclone("deletefile", f"{THUMBS}/{chat}/{stem}.jpg",
           "--retries", "2", "--low-level-retries", "3")
    try:
        (THUMB_CACHE / chat / f"{stem}.jpg").unlink()
    except OSError:
        pass
    return ok


def reaper_loop():
    """Background worker: drains the pending-delete queue. The item is already
    hidden from the gallery (it's in the exclusion ledger), so this just does the
    slow Drive deletes without anyone waiting on them."""
    import time
    while True:
        try:
            with _qlock:
                q = load_queue()
            if not q:
                time.sleep(3)
                continue
            entry = q[0]
            ok = _reap_one(entry)
            # pop the head (re-read in case new items were appended meanwhile)
            with _qlock:
                cur = load_queue()
                if cur and cur[0].get("stem") == entry.get("stem") and cur[0].get("chat") == entry.get("chat"):
                    cur.pop(0)
                    save_queue(cur)
            if ok:
                _reaper_state["reaped"] += 1
            else:
                _reaper_state["failed"] += 1
                # leave a failed item out of the queue (already popped) but count it;
                # it stays excluded so it won't reappear. Avoids head-of-line stall.
        except Exception:  # noqa: BLE001
            import time as _t
            _t.sleep(5)


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
            [py, os.path.join(here, "build_manifest.py")],
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

    def do_GET(self):
        p = unquote(self.path)
        if p.startswith("/trashqueue"):
            with _qlock:
                q = load_queue()
            return self._json(200, {
                "queued": len(q),
                "reaped": _reaper_state["reaped"],
                "failed": _reaper_state["failed"],
            })
        self._json(404, {"error": "not found"})

    def do_POST(self):
        p = unquote(self.path)
        if p.startswith("/trashmark"):
            return self._trashmark()
        if p.startswith("/trashbatch"):
            return self._trashbatch()
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

    def _trashmark(self):
        """POST /trashmark  body: {"chat": "...", "stems": [...]}
        INSTANT soft-delete: add the stems to the exclusion ledger (so they
        vanish from the gallery immediately and never re-download) and to the
        persistent pending-delete queue. Returns at once — the background reaper
        does the actual Drive file deletion. This is what makes bulk deletes feel
        instant while the user keeps browsing."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or "{}")
        except (ValueError, OSError):
            return self._json(400, {"error": "bad json body"})
        chat = body.get("chat", "")
        stems = body.get("stems") or []
        if ".." in chat or "/" in chat or not isinstance(stems, list) or not stems:
            return self._json(400, {"error": "want {chat, stems[]}"})
        stems = [s for s in stems if ".." not in s and "/" not in s]
        if not stems:
            return self._json(400, {"error": "no valid stems"})
        # 1) exclusion ledger — makes them disappear from the manifest now
        with _lock:
            ex = load_excluded()
            for s in stems:
                ex.add(s)
            save_excluded(ex)
        # 2) queue the real deletes for the background reaper
        added = enqueue_deletes(chat, stems)
        # 3) kick a manifest rebuild so a fresh page load is already correct
        _trigger_manifest_rebuild()
        with _qlock:
            depth = len(load_queue())
        return self._json(200, {"marked": len(stems), "queued_added": added,
                                "queue_depth": depth})

    def _trashbatch(self):
        """POST /trashbatch  body: {"chat": "...", "stems": [...]}
        Delete many items from one folder in a SINGLE pair of rclone processes
        (originals + thumbs via --include filters) instead of N x 2 sequential
        deletefile calls, then append all stems to the exclusion ledger once."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or "{}")
        except (ValueError, OSError):
            return self._json(400, {"error": "bad json body"})
        chat = body.get("chat", "")
        stems = body.get("stems") or []
        if ".." in chat or "/" in chat or not isinstance(stems, list) or not stems:
            return self._json(400, {"error": "want {chat, stems[]}"})
        stems = [s for s in stems if ".." not in s and "/" not in s]
        if not stems:
            return self._json(400, {"error": "no valid stems"})
        with _lock:
            # resolve leaves present in the folder
            ls = rclone("lsf", f"{SRC}/{chat}/")
            by_stem = {}
            for line in ls.stdout.splitlines():
                leaf = line.strip()
                if leaf:
                    by_stem[os.path.splitext(leaf)[0]] = leaf
            leaves = [by_stem[s] for s in stems if s in by_stem]
            deleted = 0
            if leaves:
                inc = []
                for leaf in leaves:
                    inc += ["--include", leaf]
                r = rclone("delete", f"{SRC}/{chat}", *inc,
                           "--transfers", "16", "--checkers", "32")
                if r.returncode == 0:
                    deleted = len(leaves)
            # thumbnails (best effort)
            tinc = []
            for s in stems:
                tinc += ["--include", f"{s}.jpg"]
            rclone("delete", f"{THUMBS}/{chat}", *tinc,
                   "--transfers", "16", "--checkers", "32")
            for s in stems:
                try:
                    (THUMB_CACHE / chat / f"{s}.jpg").unlink()
                except OSError:
                    pass
            # add to exclusion ledger once
            ex = load_excluded()
            for s in stems:
                ex.add(s)
            save_excluded(ex)
            _trigger_manifest_rebuild()
            return self._json(200, {"deleted": deleted, "requested": len(stems),
                                    "excluded_total": len(ex)})


def main():
    # background reaper drains the pending-delete queue (does the slow rclone
    # deletes) so the HTTP path stays instant.
    t = threading.Thread(target=reaper_loop, daemon=True)
    t.start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"trash service on {BIND}:{PORT} (reaper running)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
