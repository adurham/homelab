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
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediaingest/.config/rclone/rclone.conf")
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
_dm_lock = threading.Lock()

# ─── Coalesced manifest rebuild ────────────────────────────────────────────
# Uploads set a dirty flag; a single background worker rebuilds at most once per
# DEBOUNCE window. Thousands of uploads => a few rebuilds, never a thundering
# herd of one-per-request.
_dirty = threading.Event()
_last_rebuild = [0.0]
_uploads_total = [0]


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
        self._json(404, {"error": "not found"})

    def _mkdir(self, raw):
        folder = sanitize_folder(raw)
        if not folder:
            return self._json(400, {"error": "bad folder name"})
        r = rclone("mkdir", f"{SRC}/{folder}")
        self._json(200 if r.returncode == 0 else 500,
                   {"created": folder} if r.returncode == 0 else {"error": r.stderr[:200]})

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

        stage = Path(STAGING_ROOT) / new_stem()
        stage.mkdir(parents=True, exist_ok=True)
        stored, errors, datemap_add = [], [], {}
        try:
            for item in items:
                if not getattr(item, "filename", None):
                    continue
                ext = safe_ext(item.filename)
                # honor a provided stem (single-file collector push); else generate
                stem = stem_override if (stem_override and len(items) == 1) else new_stem()
                dest = stage / f"{stem}{ext}"
                try:
                    # chunked stream copy — never load whole file in RAM
                    with open(dest, "wb") as out:
                        shutil.copyfileobj(item.file, out, CHUNK)
                    sz = dest.stat().st_size
                    if sz == 0:
                        errors.append(f"{item.filename}: empty"); dest.unlink(); continue
                    if sz > MAX_BYTES:
                        errors.append(f"{item.filename}: too large"); dest.unlink(); continue
                    date = date_override or exif_date(dest) or \
                        dt.datetime.fromtimestamp(dest.stat().st_mtime).isoformat()
                    datemap_add[stem] = {"date": date, "out": out_override, "src": src_tag}
                    stored.append({"stem": stem, "file": f"by-chat/{folder}/{stem}{ext}",
                                   "orig": item.filename})
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{getattr(item,'filename','?')}: {type(e).__name__}")

            # ONE rclone copy for the whole batch (fast for many files)
            if stored:
                r = rclone("copy", str(stage), f"{SRC}/{folder}",
                           "--transfers", "8", "--checkers", "16",
                           "--retries", "5", "--low-level-retries", "10")
                if r.returncode != 0:
                    return self._json(500, {"error": "batch upload failed",
                                            "detail": r.stderr[:300]})
                update_datemap(datemap_add)
                _uploads_total[0] += len(stored)
                _dirty.set()  # coalesced rebuild
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        self._json(200, {"folder": folder, "stored": len(stored),
                         "items": stored, "errors": errors})


def main():
    threading.Thread(target=_rebuild_worker, daemon=True).start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"upload service on {BIND}:{PORT} (debounce {DEBOUNCE}s)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
