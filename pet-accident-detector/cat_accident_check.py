#!/usr/bin/env python3
"""
Cat-room pet-accident detector  (v2 — rich iOS alerts with preview + reason + box)

Pulls the latest frame for each monitored camera from go2rtc, sends it to the
local Qwen2.5-VL VLM server (Mac Studio node 1), parses an ACCIDENT yes/no
verdict + reasoning. On a confident "yes" it:

  1. Asks the VLM for a bounding box of the suspected area (grounding).
  2. Draws a red box + label on the frame (annotated.jpg).
  3. scp's the annotated frame to Home Assistant's /config/www so it is
     reachable at /local/accident_<cam>.jpg (works on-LAN AND remotely via
     Nabu Casa cloud).
  4. Sends an iOS rich notification: title + reasoning in the body, the
     annotated frame as an inline image, and a tap action that opens the
     /local image (full preview) instead of just the HA app.

Runs as a no_agent cron job (every 15 min). Silent unless an accident is
detected or a real error occurs.

All inference is local; nothing leaves the LAN except the iOS push (Apple/HA).

Pipeline:
  go2rtc frame.jpeg -> VLM verdict (+reason) -> [if yes] VLM bbox -> draw box
                    -> scp to HA /config/www -> HA mobile_app notify (image)

Notes / design decisions:
  * Cron runs scripts under hermes-agent's venv (sys.executable), which has
    NO Pillow. Box-drawing is therefore shelled out to the Homebrew python
    (HOMEBREW_PY) which has Pillow — keeps the prod hermes venv untouched.
    If that python or Pillow is missing, we degrade gracefully and send the
    un-annotated frame (still with preview + reason).
  * Frames are fetched from go2rtc (reliable real frames), NOT Frigate's
    latest.jpg (which serves a placeholder during detect reconnects).
"""

import base64
import json
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---- config ----
# Cameras to monitor: go2rtc stream name -> friendly label (for the alert).
CAMERAS = {
    "cat_room": "Cat Room",
    "basement": "Basement",
    "foyer": "Foyer",
    "kitchen_display": "Kitchen",
}

GO2RTC_FRAME = "http://192.168.86.85:1984/api/frame.jpeg?src={cam}"
VLM_URL = "http://192.168.86.201:8090/v1/chat/completions"
VLM_MODEL = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"

HA_HOST = "homeassistant.local"
HA_SSH_PORT = "2222"
HA_URL = "http://192.168.86.2:8123"
HA_NOTIFY = "notify/mobile_app_adams_iphone_16"
HA_WWW = "/config/www"  # served at {HA_URL}/local/
# Public base for image URLs in the push. Nabu Casa cloud is active, so the
# HA companion app resolves /local/... both on-LAN and remotely. Using the
# relative /local path lets the app pick the right base itself.
IMG_URL_TMPL = "/local/accident_{cam}.jpg"

MIN_FRAME_BYTES = 5000
FRAME_RETRIES = 3
FRAME_RETRY_SLEEP = 5
STATE_FILE = Path.home() / ".hermes" / "logs" / "cat_accident_state.json"
COOLDOWN_SEC = 3600  # don't re-alert within 1h per camera
SNAPSHOT_DIR = Path("/tmp")

# Homebrew python (has Pillow) for the box-drawing subprocess.
HOMEBREW_PY = "/opt/homebrew/bin/python3"

# Per-request timeouts (the whole script must finish < cron's 120s budget,
# so keep VLM calls bounded; we only do the 2nd bbox call on a positive).
VLM_TIMEOUT = 45
FRAME_TIMEOUT = 15

PROMPT = (
    "You are inspecting a floor for genuine pet accidents (urine, feces, or vomit). "
    "IGNORE all of the following normal things, which are NOT accidents: "
    "water bowls and food bowls (round dishes, sometimes shiny), litter boxes, "
    "scattered litter, toys, pet beds, mats, rugs, cat trees, furniture, and pets. "
    "CRITICAL: bright sunlight, window light pools, glare, sheen, and reflections "
    "on tile/hardwood/laminate floors are NOT puddles — hard floors are shiny and "
    "reflect light normally. Do NOT report a puddle just because the floor looks "
    "bright, shiny, or reflective. "
    "Flag ACCIDENT: yes ONLY if you clearly see an actual liquid puddle with a "
    "distinct irregular edge sitting ON the floor (not light), a solid pile of "
    "feces, or vomit. When uncertain, answer no. "
    "In WHY, explain in one sentence exactly what you see and where it is "
    "(e.g. 'brown solid pile on tile near the left wall'). "
    "Respond exactly in this format: "
    "ACCIDENT: yes/no | WHY: one sentence | CONFIDENCE: high/medium/low"
)

# Second-pass grounding prompt (only run on a positive verdict).
BBOX_PROMPT_TMPL = (
    'There is a pet accident in this image, described as: "{what}". '
    "Return a tight bounding box around ONLY that accident (the puddle/pile/vomit), "
    "not the whole floor. Respond ONLY as JSON with absolute pixel coordinates: "
    '{{"label":"accident","bbox_2d":[x1,y1,x2,y2]}}'
)


def ha_token():
    for line in (Path.home() / ".hermes" / ".env").read_text().splitlines():
        if line.startswith("HASS_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no HASS_TOKEN")


def get_frame(cam):
    """Fetch a real JPEG for `cam` from go2rtc, retrying past momentary blips."""
    url = GO2RTC_FRAME.format(cam=cam)
    for _ in range(FRAME_RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=FRAME_TIMEOUT) as r:
                data = r.read()
            if data and len(data) >= MIN_FRAME_BYTES and data[:2] == b"\xff\xd8":
                return data
        except Exception:
            pass
        time.sleep(FRAME_RETRY_SLEEP)
    return None


def ask_vlm(jpg_bytes, prompt, max_tokens=120):
    b64 = base64.b64encode(jpg_bytes).decode()
    body = json.dumps(
        {
            "model": VLM_MODEL,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
    ).encode()
    req = urllib.request.Request(VLM_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=VLM_TIMEOUT) as r:
        d = json.load(r)
    return d["choices"][0]["message"]["content"].strip()


def parse(verdict):
    acc = re.search(r"ACCIDENT:\s*(yes|no)", verdict, re.I)
    why = re.search(r"WHY:\s*([^|]+)", verdict, re.I)
    conf = re.search(r"CONFIDENCE:\s*(high|medium|low)", verdict, re.I)
    return (
        bool(acc and acc.group(1).lower() == "yes"),
        (why.group(1).strip() if why else verdict),
        (conf.group(1).lower() if conf else "unknown"),
    )


def get_bbox(jpg_bytes, what):
    """Ask the VLM for a bounding box of the accident. Returns [x1,y1,x2,y2]
    in absolute pixels, or None. Qwen2.5-VL returns bbox_2d JSON (possibly in
    a ```json fence and/or a list)."""
    try:
        raw = ask_vlm(jpg_bytes, BBOX_PROMPT_TMPL.format(what=what[:120]), max_tokens=120)
    except Exception:
        return None
    # strip code fences, find the first bbox_2d array
    m = re.search(
        r"bbox_2d\"?\s*:\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*,"
        r"\s*([\d.]+)\s*,\s*([\d.]+)\s*\]",
        raw,
    )
    if not m:
        return None
    try:
        box = [int(float(x)) for x in m.groups()]
    except Exception:
        return None
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def annotate(jpg_path, out_path, box, label):
    """Draw a red box + label on jpg_path -> out_path using Homebrew python's
    Pillow (the cron venv lacks Pillow). Returns True on success."""
    if not (box and Path(HOMEBREW_PY).exists()):
        return False
    code = (
        "import sys;from PIL import Image,ImageDraw,ImageFont\n"
        "src,dst,x1,y1,x2,y2,lbl=sys.argv[1],sys.argv[2],"
        "int(sys.argv[3]),int(sys.argv[4]),int(sys.argv[5]),int(sys.argv[6]),sys.argv[7]\n"
        "im=Image.open(src).convert('RGB');d=ImageDraw.Draw(im)\n"
        "w,h=im.size\n"
        "x1=max(0,min(x1,w-1));x2=max(0,min(x2,w));y1=max(0,min(y1,h-1));y2=max(0,min(y2,h))\n"
        "for o in range(4):d.rectangle([x1-o,y1-o,x2+o,y2+o],outline=(255,0,0))\n"
        "tb=[x1,max(0,y1-22),x1+9*len(lbl)+8,y1];d.rectangle(tb,fill=(255,0,0))\n"
        "d.text((x1+4,max(0,y1-20)),lbl,fill=(255,255,255))\n"
        "im.save(dst,'JPEG',quality=85)\n"
    )
    try:
        r = subprocess.run(
            [
                HOMEBREW_PY,
                "-c",
                code,
                str(jpg_path),
                str(out_path),
                str(box[0]),
                str(box[1]),
                str(box[2]),
                str(box[3]),
                label,
            ],
            capture_output=True,
            timeout=30,
        )
        return r.returncode == 0 and Path(out_path).exists()
    except Exception:
        return False


def push_to_ha_www(local_path, cam):
    """scp the annotated frame to HA /config/www/accident_<cam>.jpg so it is
    served at /local/accident_<cam>.jpg. Returns True on success."""
    dst = f"root@{HA_HOST}:{HA_WWW}/accident_{cam}.jpg"
    try:
        r = subprocess.run(
            [
                "scp",
                "-P",
                HA_SSH_PORT,
                "-o",
                "ConnectTimeout=8",
                "-o",
                "StrictHostKeyChecking=accept-new",
                str(local_path),
                dst,
            ],
            capture_output=True,
            timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def notify_ha(cam, label, what, confidence, image_url=None):
    token = ha_token()
    msg = f"{what} ({confidence} confidence)"
    data = {}
    if image_url:
        # iOS rich push: inline image + tap opens the full image in the app.
        data = {
            "image": image_url,
            "url": image_url,
            "push": {"category": "camera"},
            "tag": f"accident_{cam}",
            "group": "pet-accident",
        }
    body = json.dumps(
        {
            "title": f"Pet Accident? — {label}",
            "message": msg,
            "data": data,
        }
    ).encode()
    req = urllib.request.Request(
        f"{HA_URL}/api/services/{HA_NOTIFY}",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s))


def handle_positive(cam, label, what, confidence, jpg):
    """Build the annotated image, ship it to HA, and send the rich push.
    Returns a short status string for the cron log."""
    raw_path = SNAPSHOT_DIR / f"accident_{cam}_raw.jpg"
    raw_path.write_bytes(jpg)

    # 2nd pass: grounding box (best-effort; positive verdict only)
    box = get_bbox(jpg, what)
    send_path = raw_path
    annotated = False
    if box:
        ann_path = SNAPSHOT_DIR / f"accident_{cam}.jpg"
        if annotate(raw_path, ann_path, box, "ACCIDENT"):
            send_path = ann_path
            annotated = True
    if not annotated:
        # fall back to the raw frame as the served image
        (SNAPSHOT_DIR / f"accident_{cam}.jpg").write_bytes(jpg)
        send_path = SNAPSHOT_DIR / f"accident_{cam}.jpg"

    image_url = None
    if push_to_ha_www(send_path, cam):
        image_url = IMG_URL_TMPL.format(cam=cam)

    notify_ha(cam, label, what, confidence, image_url=image_url)
    tag = "boxed" if annotated else "no-box"
    img = "img" if image_url else "no-img"
    return f"{label}: {what} ({confidence}) [{tag},{img}]"


def check_camera(cam, label, now, last_alert):
    """Full per-camera pipeline. Returns an alert-status string if an alert
    fired (and the camera should have its cooldown stamped), else None.
    Runs in a worker thread — cameras are independent network I/O, so running
    them concurrently collapses wall-clock from sum(latencies) to max(latency).
    The slow cases are cold/off Nest streams burning frame-fetch retries
    (a dead battery cam can take ~60s of retries); serial that summed past
    the 120s cron budget, parallel does not."""
    jpg = get_frame(cam)
    if jpg is None:
        return None  # camera not serving a real frame (e.g. on battery/off)
    try:
        verdict = ask_vlm(jpg, PROMPT)
    except Exception as e:
        sys.stderr.write(f"{cam}: VLM error: {e}\n")
        return None
    is_accident, what, confidence = parse(verdict)
    if not (is_accident and confidence != "low"):
        return None
    if now - last_alert < COOLDOWN_SEC:
        return None
    try:
        return handle_positive(cam, label, what, confidence, jpg)
    except Exception as e:
        sys.stderr.write(f"{cam}: alert error: {e}\n")
        return None


def main():
    st = load_state()
    now = time.time()
    alerts = []
    # Process all cameras concurrently. Workers only read shared state; the
    # cooldown stamp is written here in the main thread after results land.
    with ThreadPoolExecutor(max_workers=len(CAMERAS)) as ex:
        futs = {ex.submit(check_camera, cam, label, now, st.get(cam, 0)): cam for cam, label in CAMERAS.items()}
        for fut in as_completed(futs):
            cam = futs[fut]
            try:
                status = fut.result()
            except Exception as e:
                sys.stderr.write(f"{cam}: worker error: {e}\n")
                continue
            if status:
                st[cam] = now
                alerts.append(status)
    save_state(st)
    if alerts:
        print("ALERTS sent: " + " | ".join(alerts))


if __name__ == "__main__":
    main()
