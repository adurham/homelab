#!/usr/bin/env python3
"""
Cat-room pet-accident detector  (v3 — EVENT-DRIVEN via Frigate MQTT)

This replaces the v2 "poll every camera every 15 min" cron. Instead it is a
long-running daemon that subscribes to Frigate's `frigate/events` MQTT topic
and only runs the expensive local VLM when it actually makes sense:

  Trigger: a `cat` tracked object event ENDS (type=="end") on a monitored
  camera. That is the right moment to look for an accident — the mess persists
  after the cat leaves, and while the cat is in frame it's usually standing on
  or obscuring the spot. "Cat just left" >> "cat present".

  On that trigger we wait SETTLE_SEC for the cat to actually clear the frame,
  grab a fresh frame from go2rtc, ask the local Qwen2.5-VL VLM "is there a
  genuine accident?", and on a confident yes: get a grounding bounding box,
  draw it, ship the annotated frame to HA /config/www, and send a rich iOS
  notification (inline preview + reason + boxed area).

Why a daemon, not a cron: MQTT subscription is inherently push. The VLM fires
on real cat activity only — zero VLM calls on a quiet night, instead of 96.

All inference is local. Nothing leaves the LAN except the Apple push.

Runs under its own isolated venv (~/.hermes/pet-accident-detector/.venv) with
paho-mqtt + Pillow, kept separate from the hermes-agent and exo/VLM envs.

Process management: launched + kept alive by cat_accident_daemon_keepalive.sh
(a launchd/cron sidecar). Logs to ~/.hermes/logs/cat_accident_daemon.log.
"""

import base64
import json
import re
import threading
import time
import urllib.request
from io import BytesIO
from pathlib import Path

import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw

# ---- config ----
# Cameras to monitor for accidents: Frigate camera name -> friendly label.
# (Frigate names match go2rtc stream names.)
MONITORED = {
    "cat_room": "Cat Room",
    "basement": "Basement",
    "foyer": "Foyer",
    "kitchen_display": "Kitchen",
}
TRIGGER_LABELS = {"cat"}  # which object labels arm a check on event end

# MQTT broker (Mosquitto add-on on the HA host).
MQTT_HOST = "192.168.86.2"
MQTT_PORT = 1883
MQTT_USER = "frigate"
MQTT_TOPIC = "frigate/events"

GO2RTC_FRAME = "http://192.168.86.85:1984/api/frame.jpeg?src={cam}"
VLM_URL = "http://192.168.86.201:8090/v1/chat/completions"
VLM_MODEL = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"

HA_HOST = "homeassistant.local"
HA_SSH_PORT = "2222"
HA_URL = "http://192.168.86.2:8123"
HA_NOTIFY = "notify/mobile_app_adams_iphone_16"
HA_WWW = "/config/www"
IMG_URL_TMPL = "/local/accident_{cam}.jpg"

SETTLE_SEC = 30  # wait after cat leaves before grabbing a frame
COOLDOWN_SEC = 3600  # per-camera min seconds between alerts
MIN_FRAME_BYTES = 5000
FRAME_RETRIES = 3
FRAME_RETRY_SLEEP = 5
VLM_TIMEOUT = 45
FRAME_TIMEOUT = 15

STATE_FILE = Path.home() / ".hermes" / "logs" / "cat_accident_state.json"
LOG_FILE = Path.home() / ".hermes" / "logs" / "cat_accident_daemon.log"
SNAPSHOT_DIR = Path("/tmp")
ENV_FILE = Path.home() / ".hermes" / ".env"

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
BBOX_PROMPT_TMPL = (
    'There is a pet accident in this image, described as: "{what}". '
    "Return a tight bounding box around ONLY that accident (the puddle/pile/vomit), "
    "not the whole floor. Respond ONLY as JSON with absolute pixel coordinates: "
    '{{"label":"accident","bbox_2d":[x1,y1,x2,y2]}}'
)

# Serialize VLM work so overlapping events don't hammer the single VLM server.
_vlm_lock = threading.Lock()
_state_lock = threading.Lock()


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def env_val(key):
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def ha_token():
    t = env_val("HASS_TOKEN")
    if not t:
        raise SystemExit("no HASS_TOKEN in .env")
    return t


def get_frame(cam):
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
    try:
        raw = ask_vlm(jpg_bytes, BBOX_PROMPT_TMPL.format(what=what[:120]), max_tokens=120)
    except Exception:
        return None
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


def annotate(jpg_bytes, box, label="ACCIDENT"):
    """Draw a red box + label on the frame. Pillow is in this daemon's venv,
    so we draw in-process (no subprocess). Returns annotated JPEG bytes, or the
    original bytes on any failure."""
    try:
        im = Image.open(BytesIO(jpg_bytes)).convert("RGB")
        d = ImageDraw.Draw(im)
        w, h = im.size
        x1 = max(0, min(box[0], w - 1))
        x2 = max(0, min(box[2], w))
        y1 = max(0, min(box[1], h - 1))
        y2 = max(0, min(box[3], h))
        for o in range(4):
            d.rectangle([x1 - o, y1 - o, x2 + o, y2 + o], outline=(255, 0, 0))
        tb = [x1, max(0, y1 - 18), x1 + 9 * len(label) + 8, y1]
        d.rectangle(tb, fill=(255, 0, 0))
        d.text((x1 + 4, max(0, y1 - 16)), label, fill=(255, 255, 255))
        out = BytesIO()
        im.save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:
        return jpg_bytes


def push_to_ha_www(jpg_bytes, cam):
    """Write annotated frame and scp to HA /config/www/accident_<cam>.jpg."""
    local = SNAPSHOT_DIR / f"accident_{cam}.jpg"
    local.write_bytes(jpg_bytes)
    dst = f"root@{HA_HOST}:{HA_WWW}/accident_{cam}.jpg"
    import subprocess

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
                str(local),
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
    data = {}
    if image_url:
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
            "message": f"{what} ({confidence} confidence)",
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
    with _state_lock:
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}


def save_state(s):
    with _state_lock:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(s))


def check_camera(cam, label):
    """Settle, grab a fresh frame, run the VLM, alert on confident accident.
    Serialized by _vlm_lock so concurrent events don't overload the VLM."""
    # cooldown check up front (cheap) before we even settle
    st = load_state()
    if time.time() - st.get(cam, 0) < COOLDOWN_SEC:
        log(f"[{cam}] within cooldown, skipping")
        return
    log(f"[{cam}] cat left — settling {SETTLE_SEC}s then checking")
    time.sleep(SETTLE_SEC)
    with _vlm_lock:
        jpg = get_frame(cam)
        if jpg is None:
            log(f"[{cam}] no real frame available, skipping")
            return
        try:
            verdict = ask_vlm(jpg, PROMPT)
        except Exception as e:
            log(f"[{cam}] VLM error: {e}")
            return
        is_accident, what, confidence = parse(verdict)
        log(f"[{cam}] verdict: accident={is_accident} conf={confidence} :: {what}")
        if not (is_accident and confidence != "low"):
            return
        # re-check cooldown (another thread may have alerted while we settled)
        st = load_state()
        if time.time() - st.get(cam, 0) < COOLDOWN_SEC:
            log(f"[{cam}] cooldown hit after settle, skipping alert")
            return
        box = get_bbox(jpg, what)
        send = annotate(jpg, box) if box else jpg
        image_url = IMG_URL_TMPL.format(cam=cam) if push_to_ha_www(send, cam) else None
        try:
            notify_ha(cam, label, what, confidence, image_url=image_url)
            st[cam] = time.time()
            save_state(st)
            log(f"[{cam}] ALERT sent ({confidence}) boxed={bool(box)} img={bool(image_url)}: {what}")
        except Exception as e:
            log(f"[{cam}] notify error: {e}")


# ---- MQTT callbacks (paho v2 API) ----
def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        client.subscribe(MQTT_TOPIC)
        log(f"connected to broker, subscribed {MQTT_TOPIC}")
    else:
        log(f"connect failed rc={reason_code}")


def on_disconnect(client, userdata, flags, reason_code, properties=None):
    log(f"disconnected rc={reason_code} (paho will auto-reconnect)")


def on_message(client, userdata, msg):
    try:
        ev = json.loads(msg.payload.decode())
    except Exception:
        return
    if ev.get("type") != "end":
        return
    after = ev.get("after") or ev.get("before") or {}
    cam = after.get("camera")
    label = after.get("label")
    if cam in MONITORED and label in TRIGGER_LABELS:
        friendly = MONITORED[cam]
        log(f"event: {label} ended on {cam} (score={after.get('top_score')})")
        threading.Thread(target=check_camera, args=(cam, friendly), daemon=True).start()


def main():
    pw = env_val("FRIGATE_MQTT_PASSWORD")
    if not pw:
        raise SystemExit("no FRIGATE_MQTT_PASSWORD in .env")
    log("pet-accident daemon starting (event-driven via frigate/events)")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pet-accident-detector")
    client.username_pw_set(MQTT_USER, pw)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as e:
            log(f"loop error: {e}; retrying in 10s")
            time.sleep(10)


if __name__ == "__main__":
    main()
