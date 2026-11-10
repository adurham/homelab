#!/usr/bin/env python3
"""Last-good frame server for the Frigate cameras (frigate-01).

Why: when a Nest/session stalls, Frigate serves its placeholder JPEG
("No frames have been received"), and every HA camera tile that still_image_url
points at Frigate shows that error card. This keeps the newest *real* frame per
camera on disk and serves it, so a stalled camera shows its last good picture
instead of an error tile.

Endpoint: http://<host>:8099/<camera>.jpg  (Cache-Control: no-store)

Placeholder detection is by content hash AND by byte size - Frigate's
placeholder is a fixed 51,868-byte JPEG, so a hash match is exact and a
size floor catches a future placeholder rewrite.
"""
import hashlib
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FRIGATE = os.environ.get("FRIGATE_URL", "http://127.0.0.1:5000")
OUT_DIR = os.environ.get("LASTGOOD_DIR", "/opt/frigate/lastgood")
PORT = int(os.environ.get("LASTGOOD_PORT", "8099"))
REFRESH = int(os.environ.get("LASTGOOD_REFRESH", "15"))
CAMS = os.environ.get(
    "LASTGOOD_CAMS",
    "cat_room foyer basement driveway backyard front_porch",
).split()
PLACEHOLDER_MD5 = "c7b3c8f612faa361ff1a6441b9c4f1fc"
MIN_BYTES = 20000  # a real 1080p frame is 80-300 kB; the placeholder is 51.8 kB


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def fetch(url, timeout=12):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def store(cam, data):
    tmp = os.path.join(OUT_DIR, f".{cam}.jpg.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, os.path.join(OUT_DIR, f"{cam}.jpg"))


def refresh_loop():
    os.makedirs(OUT_DIR, exist_ok=True)
    stats = {c: {"saved": 0, "skipped": 0} for c in CAMS}
    while True:
        for cam in CAMS:
            try:
                data = fetch(f"{FRIGATE}/api/{cam}/latest.jpg")
            except Exception as exc:  # noqa: BLE001
                log(f"{cam}: fetch failed: {exc}")
                continue
            digest = hashlib.md5(data).hexdigest()
            if digest == PLACEHOLDER_MD5 or len(data) < MIN_BYTES:
                stats[cam]["skipped"] += 1
                continue
            try:
                store(cam, data)
                stats[cam]["saved"] += 1
            except Exception as exc:  # noqa: BLE001
                log(f"{cam}: write failed: {exc}")
        log("refresh " + json.dumps({c: s for c, s in stats.items()}, separators=(",", ":")))
        time.sleep(REFRESH)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        name = self.path.lstrip("/").split("?")[0]
        if name.endswith(".jpg"):
            name = name[:-4]
        path = os.path.join(OUT_DIR, f"{name}.jpg")
        if name not in CAMS or not os.path.exists(path):
            self.send_error(404, "no last-good frame yet")
            return
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - base class signature
        pass


if __name__ == "__main__":
    threading.Thread(target=refresh_loop, daemon=True).start()
    log(f"serving last-good frames on :{PORT} for {CAMS}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
