#!/usr/bin/env python3
"""
Upload service for the TG gallery — add your own pics + create folders.
Built to handle THOUSANDS of uploads: per-request batch staging + a single
rclone copy per batch (not per file), chunked streaming writes (no whole-file
in RAM), and a COALESCED background manifest rebuild (thousands of uploads
trigger a handful of rebuilds, not one each).

Endpoints (all POST, gated by Authentik at lb-01, firewalled to lb-01 only):
  /mkdir/<folder>                 create gcrypt:by-chat/<folder>/ (idempotent)
  /upload/<folder>   multipart    field "files" = 1..N files. Each gets stem
                                  "up_<ms>_<rand>" (never collides with source
                                  <chatid>_<msgid>), EXIF/mtime date recorded to
                                  the shared datemap, out=False (always kept).
  /status                         {pending_rebuild, last_rebuild, uploads_total}

Uploads land in gcrypt:by-chat/<folder>/ alongside source media, so they show
in the same root-level folders. The manifest builder never source-fetches
up_* stems (it regex-matches real source stems only).

Env: RCLONE_CONFIG, TG_RCLONE_REMOTE (gcrypt:), UPLOAD_PORT (8092),
     UPLOAD_BIND (172.16.0.46), TG_DATEMAP_CACHE, UPLOAD_MAX_MB (200),
     UPLOAD_STAGING (/var/lib/media-gallery/upload_staging),
     REBUILD_DEBOUNCE_SEC (20).
"""
import cgi
import datetime as dt
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from PIL import Image

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediagallery/.config/rclone/rclone.conf")
PORT = int(os.environ.get("UPLOAD_PORT", "8092"))
BIND = os.environ.get("UPLOAD_BIND", "172.16.0.46")
DATEMAP_CACHE = Path(os.environ.get("TG_DATEMAP_CACHE", "/var/lib/media-gallery/datemap.json"))
EXCLUDE_FILE = Path(os.environ.get("TG_EXCLUDE_FILE", "/var/lib/media-gallery/excluded.json"))
MAX_BYTES = int(os.environ.get("UPLOAD_MAX_MB", "200")) * 1024 * 1024
STAGING_ROOT = Path(os.environ.get("UPLOAD_STAGING", "/var/lib/media-gallery/upload_staging"))
DEBOUNCE = int(os.environ.get("REBUILD_DEBOUNCE_SEC", "20"))
# ─── Machine ingest auth: OAuth2 (Authentik) Bearer JWT ────────────────────
# The upstream source collector authenticates as a real Authentik OAuth2 app
# (client_credentials grant). It presents Authorization: Bearer <RS256 JWT>;
# we validate signature against Authentik's JWKS + issuer + audience + expiry.
# Browser uploads come through lb-01/Authentik (SSO) and need no token.
# INGEST_JWKS_URL / INGEST_ISSUER / INGEST_AUDIENCE configure validation.
INGEST_JWKS_URL = os.environ.get("INGEST_JWKS_URL", "").strip()
INGEST_ISSUER = os.environ.get("INGEST_ISSUER", "").strip()
INGEST_AUDIENCE = os.environ.get("INGEST_AUDIENCE", "").strip()
SRC = REMOTE + "by-chat"
CHUNK = 1024 * 1024  # 1 MiB streaming chunks

# JWKS client (cached; refreshes keys automatically on unknown kid)
_jwk_client = None


def _get_jwk_client():
    global _jwk_client
    if _jwk_client is None and INGEST_JWKS_URL:
        import jwt
        _jwk_client = jwt.PyJWKClient(INGEST_JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwk_client


def validate_bearer(auth_header: str) -> bool:
    """Validate an 'Authorization: Bearer <jwt>' header against Authentik's
    JWKS. Returns True only on a fully valid token (sig + iss + aud + exp)."""
    if not (INGEST_JWKS_URL and auth_header.startswith("Bearer ")):
        return False
    token = auth_header[len("Bearer "):].strip()
    try:
        import jwt
        client = _get_jwk_client()
        signing_key = client.get_signing_key_from_jwt(token)
        jwt.decode(
            token, signing_key.key, algorithms=["RS256"],
            audience=INGEST_AUDIENCE or None,
            issuer=INGEST_ISSUER or None,
            options={"require": ["exp", "iss"]},
        )
        return True
    except Exception:  # noqa: BLE001
        return False

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

STAGING_ROOT.mkdir(parents=True, exist_ok=True)
# ─── Async GDrive push queue ───────────────────────────────────────────────
# The upload request streams each file to PENDING/<folder>/<stem><ext> (a local,
# LAN-speed write) and returns 200 IMMEDIATELY. A background pusher thread does
# the slow rclone copy to Google Drive out-of-band, so the client's upload speed
# is decoupled from Google's. Before this, the rclone-to-GDrive ran INSIDE the
# request, so a client waited through the entire GDrive round-trip per batch
# (multi-GB videos timed out). Now the client only pays the local-disk write.
PENDING_ROOT = STAGING_ROOT / "pending"
PENDING_ROOT.mkdir(parents=True, exist_ok=True)
PUSH_INTERVAL = int(os.environ.get("PUSH_INTERVAL_SEC", "5"))
_dm_lock = threading.Lock()
_push_lock = threading.Lock()

# ─── Coalesced manifest rebuild ────────────────────────────────────────────
# Uploads set a dirty flag; a single background worker rebuilds at most once per
# DEBOUNCE window. Thousands of uploads => a few rebuilds, never a thundering
# herd of one-per-request.
_dirty = threading.Event()
_last_rebuild = [0.0]
_uploads_total = [0]
_pending_count = [0]


def _pusher_worker():
    """Background GDrive push: periodically rclone-move PENDING/<folder>/* to
    gcrypt:by-chat/<folder>/, then arm a manifest rebuild. Decouples the client
    upload (local write) from the slow GDrive transfer. rclone 'move' is
    copy-then-delete, so a crash mid-push just re-pushes next cycle (idempotent
    by stem). New files landing mid-push are caught on the following cycle."""
    while True:
        time.sleep(PUSH_INTERVAL)
        try:
            folders = [d for d in PENDING_ROOT.iterdir() if d.is_dir()]
        except OSError:
            continue
        pushed_any = False
        for fdir in folders:
            # only fully-renamed files (no .tmp); snapshot the list
            files = [f for f in fdir.iterdir()
                     if f.is_file() and not f.name.endswith(".tmp")]
            if not files:
                continue
            folder = fdir.name
            r = rclone("move", str(fdir), f"{SRC}/{folder}",
                       "--transfers", "8", "--checkers", "16",
                       "--retries", "5", "--low-level-retries", "10",
                       "--no-traverse", "--exclude", "*.tmp")
            if r.returncode == 0:
                pushed_any = True
                with _push_lock:
                    _pending_count[0] = max(0, _pending_count[0] - len(files))
            # on failure, files stay in PENDING and retry next cycle
        if pushed_any:
            _dirty.set()  # rebuild only after files are actually in GDrive


def _rebuild_worker():
    here = os.path.dirname(os.path.abspath(__file__))
    py = os.path.join(here, "venv", "bin", "python")
    if not os.path.exists(py):
        py = "python3"
    while True:
        _dirty.wait()
        time.sleep(DEBOUNCE)          # let a burst accumulate
        _dirty.clear()                # anything after this re-arms for next pass
        env = dict(os.environ)
        env.setdefault("RCLONE_CONFIG", RCLONE_CONF)
        env.setdefault("TG_RCLONE_REMOTE", REMOTE)
        try:
            subprocess.run([py, os.path.join(here, "build_manifest.py")],
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _last_rebuild[0] = time.time()
        except Exception:  # noqa: BLE001
            pass


def rclone(*args):
    return subprocess.run(["rclone", "--config", RCLONE_CONF, *args],
                          capture_output=True, text=True)


def sanitize_folder(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in (name or "")).strip()
    return keep.replace(" ", "-")


def safe_ext(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in (IMAGE_EXT | VIDEO_EXT) else ".bin"


def exif_date(path: Path):
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            for tag in (36867, 306):  # DateTimeOriginal, DateTime
                v = ex.get(tag)
                if v:
                    return dt.datetime.strptime(str(v), "%Y:%m:%d %H:%M:%S").isoformat()
    except Exception:  # noqa: BLE001
        pass
    return None


def update_datemap(entries: dict):
    with _dm_lock:
        try:
            m = json.loads(DATEMAP_CACHE.read_text())
        except (OSError, ValueError):
            m = {}
        m.update(entries)
        tmp = str(DATEMAP_CACHE) + ".tmp"
        Path(tmp).write_text(json.dumps(m))
        os.replace(tmp, DATEMAP_CACHE)


def new_stem() -> str:
    import secrets
    return f"up_{int(time.time()*1000)}_{secrets.token_hex(4)}"


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

    def _key_ok(self) -> bool:
        """True if the request carries a valid Authentik-issued Bearer JWT
        (the collector's OAuth2 client_credentials token). Browser requests won't
        have it (and don't need it — gated by Authentik SSO at lb-01)."""
        return validate_bearer(self.headers.get("Authorization", ""))

    def do_GET(self):
        p = unquote(self.path)
        # /ingest/* GETs (collector reads, e.g. /excluded) require a valid Bearer
        # JWT — the exclusion ledger is sensitive (message IDs). Browser GETs
        # don't hit this service (rclone serves them, gated by Authentik).
        if p.startswith("/ingest/"):
            if not self._key_ok():
                return self._json(401, {"error": "unauthorized"})
            p = p[len("/ingest"):]
        if p == "/status":
            return self._json(200, {
                "pending_rebuild": _dirty.is_set(),
                "last_rebuild": _last_rebuild[0],
                "uploads_total": _uploads_total[0],
                "pending_gdrive_push": _pending_count[0],
            })
        if p == "/excluded":
            # The collector fetches this to skip trashed/purged items before
            # spending upstream source bandwidth re-capturing them.
            try:
                ex = json.loads(EXCLUDE_FILE.read_text())
            except (OSError, ValueError):
                ex = []
            return self._json(200, {"excluded": ex, "count": len(ex)})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        p = unquote(self.path)
        # /ingest/* is the collector path (routed by lb-01 WITHOUT Authentik SSO;
        # this service validates the Bearer JWT itself). Strip the prefix so
        # /ingest/upload/X == /upload/X. The metadata override still requires a
        # valid token via _key_ok(), so the prefix alone grants nothing.
        if p.startswith("/ingest/"):
            # collector-only path: require a valid Bearer JWT for ALL operations
            # (not just metadata override). Browser uploads use /upload directly
            # behind Authentik SSO; /ingest is exclusively the keyed collector.
            if not self._key_ok():
                return self._json(401, {"error": "unauthorized"})
            p = p[len("/ingest"):]
        if p.startswith("/mkdir/"):
            return self._mkdir(p[len("/mkdir/"):])
        if p.startswith("/upload/"):
            return self._upload(p[len("/upload/"):])
        if p.startswith("/rename/"):
            return self._rename(p[len("/rename/"):])
        if p.startswith("/move/"):
            return self._move(p[len("/move/"):])
        self._json(404, {"error": "not found"})

    def _mkdir(self, raw):
        folder = sanitize_folder(raw)
        if not folder:
            return self._json(400, {"error": "bad folder name"})
        r = rclone("mkdir", f"{SRC}/{folder}")
        self._json(200 if r.returncode == 0 else 500,
                   {"created": folder} if r.returncode == 0 else {"error": r.stderr[:200]})

    def _rename(self, raw):
        """POST /rename/<old>/<new> — rename a gallery folder. Moves the original
        media AND its thumbnail cache, so posters survive the rename. The manifest
        rebuild then re-keys every item's `chat`/`file`/`thumb` to the new name
        (the manifest is derived from the folder listing, so a rebuild is enough).
        Idempotent-ish: refuses if <new> already exists (would merge, surprising)."""
        parts = [s for s in raw.split("/") if s]
        if len(parts) != 2:
            return self._json(400, {"error": "want /rename/<old>/<new>"})
        old = sanitize_folder(parts[0])
        new = sanitize_folder(parts[1])
        if not old or not new:
            return self._json(400, {"error": "bad folder name"})
        if old == new:
            return self._json(200, {"renamed": old, "to": new, "noop": True})
        # refuse if destination already exists (avoid silent merge)
        chk = rclone("lsf", f"{SRC}/{new}/")
        if chk.returncode == 0 and chk.stdout.strip():
            return self._json(409, {"error": f"folder '{new}' already exists"})
        # move the originals
        r = rclone("move", f"{SRC}/{old}", f"{SRC}/{new}",
                   "--transfers", "8", "--checkers", "16",
                   "--retries", "5", "--low-level-retries", "10")
        if r.returncode != 0:
            return self._json(500, {"error": "rename failed", "detail": r.stderr[:200]})
        # move the thumbnail cache too (best effort — posters regenerate if missing)
        rclone("move", f"{REMOTE}thumbs/{old}", f"{REMOTE}thumbs/{new}",
               "--retries", "3", "--low-level-retries", "5")
        # clean up the now-empty source dirs
        rclone("rmdir", f"{SRC}/{old}")
        rclone("rmdir", f"{REMOTE}thumbs/{old}")
        _dirty.set()  # rebuild manifest -> items re-keyed to <new>
        self._json(200, {"renamed": old, "to": new})

    def _move(self, raw):
        """POST /move/<srcfolder>/<stem>/<destfolder> — move ONE item (its
        original + thumbnail) between folders. Used by the UI to drag a photo
        into the right person's folder. The stem keeps its identity; only the
        containing folder changes."""
        parts = [s for s in raw.split("/") if s]
        if len(parts) != 3:
            return self._json(400, {"error": "want /move/<srcfolder>/<stem>/<destfolder>"})
        srcf = sanitize_folder(parts[0])
        stem = parts[1]
        destf = sanitize_folder(parts[2])
        if not srcf or not destf or not stem:
            return self._json(400, {"error": "bad folder or stem"})
        if srcf == destf:
            return self._json(200, {"moved": stem, "to": destf, "noop": True})
        # find the original's leaf (stem + real extension) in the source folder
        ls = rclone("lsf", f"{SRC}/{srcf}/")
        if ls.returncode != 0:
            return self._json(404, {"error": f"source folder '{srcf}' not found"})
        leaf = None
        for line in ls.stdout.splitlines():
            name = line.strip()
            if name and os.path.splitext(name)[0] == stem:
                leaf = name
                break
        if not leaf:
            return self._json(404, {"error": f"item '{stem}' not in '{srcf}'"})
        ext = os.path.splitext(leaf)[1]
        # ensure dest exists
        rclone("mkdir", f"{SRC}/{destf}")
        # move the original
        r = rclone("moveto", f"{SRC}/{srcf}/{leaf}", f"{SRC}/{destf}/{leaf}",
                   "--retries", "5", "--low-level-retries", "10")
        if r.returncode != 0:
            return self._json(500, {"error": "move failed", "detail": r.stderr[:200]})
        # move the thumbnail too (best effort — regenerates if missing)
        rclone("moveto", f"{REMOTE}thumbs/{srcf}/{stem}.jpg",
               f"{REMOTE}thumbs/{destf}/{stem}.jpg",
               "--retries", "3", "--low-level-retries", "5")
        _dirty.set()  # rebuild manifest -> item re-keyed to <destf>
        self._json(200, {"moved": stem, "from": srcf, "to": destf,
                         "file": f"by-chat/{destf}/{leaf}"})

    def _upload(self, raw):
        folder = sanitize_folder(raw)
        if not folder:
            return self._json(400, {"error": "bad folder name"})
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._json(400, {"error": "expected multipart/form-data"})

        # cgi.FieldStorage streams large parts to spooled temp files itself; we
        # then move each into a per-request staging dir under their final name.
        fs = cgi.FieldStorage(
            fp=self.rfile, headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype},
        )
        items = fs["files"] if "files" in fs else []
        if not isinstance(items, list):
            items = [items]

        # Optional metadata (collector push). Browser uploads omit these.
        # stem_override: preserve source <chatid>_<msgid> identity (enables
        #   dedup + incremental manifest date-fetch).
        # date_override / out_override: keep real message date + received flag.
        # These require the ingest key (a browser session must NOT be able to
        # forge a source stem / out flag).
        keyed = self._key_ok()

        def field(name):
            try:
                v = fs.getfirst(name)
                return v if v else None
            except Exception:  # noqa: BLE001
                return None

        stem_override = field("stem") if keyed else None
        date_override = field("date") if keyed else None
        out_override = (field("out") == "1") if keyed else False
        src_tag = "source" if keyed else "upload"

        # Stream each file straight into PENDING/<folder>/ (local disk, LAN
        # speed) and return immediately. The _pusher_worker copies to GDrive
        # out-of-band. We write to <stem><ext>.tmp then atomically rename, so the
        # pusher never grabs a half-written file.
        pdir = PENDING_ROOT / folder
        pdir.mkdir(parents=True, exist_ok=True)
        stored, errors, datemap_add = [], [], {}
        for item in items:
            if not getattr(item, "filename", None):
                continue
            ext = safe_ext(item.filename)
            # honor a provided stem (single-file collector push); else generate
            stem = stem_override if (stem_override and len(items) == 1) else new_stem()
            tmp = pdir / f"{stem}{ext}.tmp"
            dest = pdir / f"{stem}{ext}"
            try:
                # chunked stream copy — never load whole file in RAM
                with open(tmp, "wb") as out:
                    shutil.copyfileobj(item.file, out, CHUNK)
                sz = tmp.stat().st_size
                if sz == 0:
                    errors.append(f"{item.filename}: empty"); tmp.unlink(); continue
                if sz > MAX_BYTES:
                    errors.append(f"{item.filename}: too large"); tmp.unlink(); continue
                date = date_override or exif_date(tmp) or \
                    dt.datetime.fromtimestamp(tmp.stat().st_mtime).isoformat()
                os.replace(tmp, dest)  # atomic; now visible to the pusher
                datemap_add[stem] = {"date": date, "out": out_override, "src": src_tag}
                stored.append({"stem": stem, "file": f"by-chat/{folder}/{stem}{ext}",
                               "orig": item.filename})
            except Exception as e:  # noqa: BLE001
                errors.append(f"{getattr(item,'filename','?')}: {type(e).__name__}")
                try:
                    tmp.unlink()
                except OSError:
                    pass

        # Record dates now so the manifest is correct once the pusher lands the
        # files in GDrive. The pusher arms the rebuild after the actual push.
        if stored:
            update_datemap(datemap_add)
            _uploads_total[0] += len(stored)
            with _push_lock:
                _pending_count[0] += len(stored)
        # 'queued' = accepted to local staging, GDrive push is async.
        self._json(200, {"folder": folder, "stored": len(stored),
                         "queued": len(stored), "items": stored,
                         "errors": errors, "async": True})


def _drain_pending_on_start():
    """On startup, re-arm any files left in PENDING from a previous run/crash so
    the pusher flushes them (and clean up orphaned .tmp partials)."""
    try:
        for fdir in PENDING_ROOT.iterdir():
            if not fdir.is_dir():
                continue
            for f in fdir.iterdir():
                if f.name.endswith(".tmp"):
                    try:
                        f.unlink()
                    except OSError:
                        pass
                elif f.is_file():
                    with _push_lock:
                        _pending_count[0] += 1
    except OSError:
        pass


def main():
    _drain_pending_on_start()
    threading.Thread(target=_rebuild_worker, daemon=True).start()
    threading.Thread(target=_pusher_worker, daemon=True).start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"upload service on {BIND}:{PORT} (debounce {DEBOUNCE}s, async GDrive push)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
