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
import random
import re
import threading
import time
import urllib.request
from io import BytesIO
from pathlib import Path

import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw

# ---- config ----
# Two trigger modes, because the cat room is a special case.
#
# EVENT_DRIVEN: visitor rooms that actually go EMPTY. We check when a cat LEAVES
# (Frigate event type=="end"), after a settle delay so the cat clears the frame.
# Cheap and accurate — the VLM only runs on real cat activity.
EVENT_DRIVEN = {
    "basement": "Basement",
    "foyer": "Foyer",
    "kitchen_display": "Kitchen",
}
# PERIODIC: rooms that are NEVER empty (the cat room always has cats), so the
# "cat left" trigger would never fire / never see a clear floor. Check these on
# a fixed timer instead, cats-in-frame and all (the VLM is told to ignore pets).
# Map: Frigate camera name -> (friendly label, interval seconds).
PERIODIC = {
    "cat_room": ("Cat Room", 15 * 60),
}
TRIGGER_LABELS = {"cat"}  # which object labels arm an event-driven check

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
# Dedicated, on-disk SSH key for shipping frames to HA /config/www. MUST be a
# file (not an ssh-agent key): the daemon runs under launchd, which has NO
# access to the user's ssh-agent, so an agent-only key fails with
# "Permission denied (publickey)" and the notification ships with no image.
# This key's pubkey is in core_ssh's authorized_keys (add-on options).
HA_SSH_KEY = str(Path.home() / ".hermes" / "pet-accident-detector" / "id_petaccident")
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

# Multi-frame consensus (false-positive killer). A real accident is STABLE across
# seconds; transient triggers (shadows, shifting glare/light pools, a cat moving
# through, motion blur) flicker between frames. So when the first frame says
# "accident", we grab CONSENSUS_FRAMES frames CONSENSUS_GAP_SEC apart and only
# alert if at least CONSENSUS_NEEDED of them agree it's an accident.
CONSENSUS_FRAMES = 3
CONSENSUS_GAP_SEC = 4
CONSENSUS_NEEDED = 3  # all must agree — strict, because FPs are the main problem

STATE_FILE = Path.home() / ".hermes" / "logs" / "cat_accident_state.json"
LOG_FILE = Path.home() / ".hermes" / "logs" / "cat_accident_daemon.log"
SNAPSHOT_DIR = Path("/tmp")
ENV_FILE = Path.home() / ".hermes" / ".env"

# Evidence capture: every positive (confirmed OR rejected-by-consensus) saves its
# frames + verdicts here, plus a sampled fraction of negatives, so the prompt can
# be tuned against REAL frames that fooled (or nearly fooled) the model. Pruned
# to EVIDENCE_KEEP_DAYS so it can't grow unbounded.
EVIDENCE_DIR = Path.home() / ".hermes" / "pet-accident-detector" / "evidence"
EVIDENCE_KEEP_DAYS = 14
NEGATIVE_SAMPLE_RATE = 0.10  # keep ~10% of negative frames for balance/tuning

PROMPT = (
    "You are inspecting a floor for genuine pet accidents (urine, feces, or vomit). "
    "IGNORE all of the following normal things, which are NOT accidents: "
    "water bowls and food bowls (round dishes, sometimes shiny), litter boxes, "
    "scattered litter, toys, pet beds, mats, rugs, cat trees, furniture, and pets. "
    "CRITICAL: bright sunlight, window light pools, glare, sheen, and reflections "
    "on tile/hardwood/laminate floors are NOT puddles — hard floors are shiny and "
    "reflect light normally. Do NOT report a puddle just because the floor looks "
    "bright, shiny, or reflective. "
    # First-pass FP hardening (observed 2026-06-02): the model repeatedly called a
    # 'dark/irregular puddle near the center' on a clean floor — that pattern is
    # almost always a SHADOW (from a cat, furniture, or the camera) or a darker
    # floor tile/seam, not liquid. Demand positive evidence of WETNESS, not just
    # a dark shape.
    "A DARK or irregular SHAPE on the floor is NOT enough — dark shapes are "
    "usually shadows, darker tiles, grout lines, or mats. Only call a puddle if "
    "you can see actual signs of LIQUID: a wet glossy sheen with a meniscus/edge, "
    "a specular highlight on a wet surface, or a visible spreading stain. "
    "Shadows have soft fuzzy edges and no wet sheen — those are NOT accidents. "
    "Flag ACCIDENT: yes ONLY if you clearly see an actual liquid puddle with a "
    "distinct irregular edge AND a wet sheen sitting ON the floor (not light, not "
    "a shadow), a solid pile of feces, or vomit. "
    "If you are not confident it is genuinely wet or solid waste, answer no. "
    "When uncertain, answer no. "
    "In WHY, explain in one sentence exactly what you see and where it is, and "
    "for a puddle state what makes it look WET (e.g. 'wet glossy puddle with "
    "reflective sheen on tile near the left wall'). "
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
                "-i",
                HA_SSH_KEY,
                "-o",
                "IdentitiesOnly=yes",
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


def prune_evidence():
    """Delete evidence files older than EVIDENCE_KEEP_DAYS so the folder can't
    grow unbounded."""
    try:
        cutoff = time.time() - EVIDENCE_KEEP_DAYS * 86400
        for p in EVIDENCE_DIR.glob("*"):
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
    except Exception:
        pass


def save_evidence(cam, kind, frames, verdicts):
    """Persist the triggering frame(s) + verdict text for later prompt tuning.
    kind: 'alert' (consensus confirmed), 'rejected' (first frame yes but
    consensus said no — the most valuable FP examples), or 'negative' (sampled).
    Returns the saved dir path or None."""
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        stem = f"{ts}_{cam}_{kind}"
        for i, fr in enumerate(frames):
            if fr:
                (EVIDENCE_DIR / f"{stem}_f{i}.jpg").write_bytes(fr)
        (EVIDENCE_DIR / f"{stem}.txt").write_text(
            f"camera: {cam}\nkind: {kind}\ntime: {ts}\n\n"
            + "\n".join(f"frame {i}: {v}" for i, v in enumerate(verdicts))
        )
        prune_evidence()
        return EVIDENCE_DIR / stem
    except Exception as e:
        log(f"[{cam}] evidence save error: {e}")
        return None


def consensus_check(cam):
    """First frame already said 'accident'. Grab CONSENSUS_FRAMES frames spaced
    CONSENSUS_GAP_SEC apart and re-run the VLM on each. A real accident is stable
    across all of them; a transient (shadow/glare/cat/motion) won't be. Returns
    (confirmed: bool, frames: list[bytes], verdicts: list[str], yes_count: int).

    The caller already evaluated frame 0; we re-grab fresh frames here so each
    vote is an independent look (and so we capture the evidence set)."""
    frames, verdicts, yes = [], [], 0
    for i in range(CONSENSUS_FRAMES):
        if i > 0:
            time.sleep(CONSENSUS_GAP_SEC)
        fr = get_frame(cam)
        if fr is None:
            verdicts.append(f"frame {i}: no frame")
            frames.append(None)
            continue
        try:
            v = ask_vlm(fr, PROMPT)
        except Exception as e:
            v = f"VLM error: {e}"
        a, what, conf = parse(v)
        vote = bool(a and conf != "low")
        yes += 1 if vote else 0
        frames.append(fr)
        verdicts.append(f"vote={'YES' if vote else 'no'} conf={conf} :: {what}")
        log(f"[{cam}] consensus {i + 1}/{CONSENSUS_FRAMES}: {'YES' if vote else 'no'} ({conf}) :: {what}")
    return (yes >= CONSENSUS_NEEDED, frames, verdicts, yes)


def check_camera(cam, label, settle=SETTLE_SEC, reason="cat left"):
    """Optionally settle, grab a fresh frame, run the VLM. On a candidate
    accident, require multi-frame CONSENSUS before alerting (kills transient
    false positives), and save evidence frames for later tuning. Serialized by
    _vlm_lock so concurrent checks don't overload the single VLM server.

    settle: seconds to wait before grabbing the frame. Event-driven checks pass
    SETTLE_SEC so the departing cat clears the frame; periodic checks pass 0
    (the room is never empty, waiting wouldn't help)."""
    # cooldown check up front (cheap) before we even settle
    st = load_state()
    if time.time() - st.get(cam, 0) < COOLDOWN_SEC:
        log(f"[{cam}] within cooldown, skipping")
        return
    if settle > 0:
        log(f"[{cam}] {reason} — settling {settle}s then checking")
        time.sleep(settle)
    else:
        log(f"[{cam}] {reason} — checking now")
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
            # sample a fraction of negatives for a balanced tuning corpus
            if random.random() < NEGATIVE_SAMPLE_RATE:
                save_evidence(cam, "negative", [jpg], [f"frame 0: {verdict}"])
            return

        # Candidate positive — demand consensus across several frames.
        log(f"[{cam}] candidate accident — running {CONSENSUS_FRAMES}-frame consensus")
        confirmed, frames, verdicts, yes = consensus_check(cam)
        all_frames = [jpg] + frames
        all_verdicts = [f"frame 0 (trigger): {verdict}"] + verdicts

        if not confirmed:
            # The single most valuable FP examples: first glance said accident,
            # consensus disagreed. Save them all for tuning.
            ev = save_evidence(cam, "rejected", all_frames, all_verdicts)
            log(f"[{cam}] consensus REJECTED ({yes}/{CONSENSUS_FRAMES} agreed) — no alert. evidence: {ev}")
            return

        # re-check cooldown (another thread may have alerted while we settled)
        st = load_state()
        if time.time() - st.get(cam, 0) < COOLDOWN_SEC:
            log(f"[{cam}] cooldown hit after consensus, skipping alert")
            return
        # use the last consensus frame (freshest) for the alert image
        best = next((f for f in reversed(frames) if f), jpg)
        box = get_bbox(best, what)
        send = annotate(best, box) if box else best
        image_url = IMG_URL_TMPL.format(cam=cam) if push_to_ha_www(send, cam) else None
        save_evidence(cam, "alert", all_frames, all_verdicts)
        try:
            notify_ha(cam, label, what, confidence, image_url=image_url)
            st[cam] = time.time()
            save_state(st)
            log(
                f"[{cam}] ALERT sent ({confidence}) consensus={yes}/{CONSENSUS_FRAMES} "
                f"boxed={bool(box)} img={bool(image_url)}: {what}"
            )
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
    if cam in EVENT_DRIVEN and label in TRIGGER_LABELS:
        friendly = EVENT_DRIVEN[cam]
        log(f"event: {label} ended on {cam} (score={after.get('top_score')})")
        threading.Thread(target=check_camera, args=(cam, friendly), daemon=True).start()


def periodic_loop(cam, label, interval):
    """Timer-based checks for a never-empty room (the cat room). Runs the same
    check_camera path with settle=0, every `interval` seconds, forever. The
    per-camera COOLDOWN_SEC still caps alerts; for the cat room interval and
    cooldown are both ~1h-ish so at most one alert per cycle."""
    log(f"[{cam}] periodic checks every {interval}s (never-empty room)")
    # small initial offset so we don't fire the instant the daemon boots
    time.sleep(min(60, interval))
    while True:
        try:
            check_camera(cam, label, settle=0, reason="periodic check")
        except Exception as e:
            log(f"[{cam}] periodic check error: {e}")
        time.sleep(interval)


def main():
    pw = env_val("FRIGATE_MQTT_PASSWORD")
    if not pw:
        raise SystemExit("no FRIGATE_MQTT_PASSWORD in .env")
    log(f"pet-accident daemon starting (event-driven: {sorted(EVENT_DRIVEN)} | periodic: {sorted(PERIODIC)})")
    # Start periodic-check threads for never-empty rooms (e.g. cat room).
    for cam, (label, interval) in PERIODIC.items():
        threading.Thread(target=periodic_loop, args=(cam, label, interval), daemon=True).start()
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
