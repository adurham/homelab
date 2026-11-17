#!/usr/bin/env python3
"""Camera health watchdog (frigate-01).

Problem it solves: a Nest camera can stay *connected* (go2rtc producer alive,
WebRTC peer reachable) while no longer delivering frames. Frigate then reports
camera_fps 0 and /api/<cam>/latest.jpg serves its built-in placeholder, which is
what shows up on the HA dashboard as "No frames have been received".

The previous version of this script only restarted Frigate when **4 or more**
cameras were stalled, so the common case (one to three cameras dead) logged
"waiting for recovery" forever while the tiles stayed broken.

Recovery that actually works here is a full `docker compose restart frigate`:
the stalled sessions are released and every camera re-offers a fresh WebRTC
session. Per-camera recovery is not possible - go2rtc refuses to delete a stream
that comes from config.yml (`DELETE /api/streams?src=X` -> 400), and re-PUTting
an identical source is a no-op (verified 2026-11-10).

Because a restart drops all six cameras for ~40 s, this script:
  - restarts only after a camera has read 0 fps on DEAD_CHECKS consecutive runs
    (6 x 5-minute cron = ~30 minutes of genuinely dead video). Shorter thresholds
    restart healthy cameras during a flap: a Nest session drop takes 1-2 minutes
    to re-establish, so a 10-minute rule fired on ordinary churn,
  - never restarts more than once per RESTART_COOLDOWN,
  - remembers both across cron ticks in STATE_PATH,
  - logs one line per decision so /var/log/frigate_health.log stays readable.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

FRIGATE = os.environ.get("FRIGATE_URL", "http://localhost:5000")
COMPOSE_DIR = "/opt/frigate"
STATE_PATH = "/var/lib/frigate-camera-health.json"

DEAD_CHECKS = int(os.environ.get("DEAD_CHECKS", "2"))              # consecutive ticks (~10 min)
RESTART_COOLDOWN = int(os.environ.get("RESTART_COOLDOWN", "3600"))  # full container restart
GO2RTC_COOLDOWN = int(os.environ.get("GO2RTC_COOLDOWN", "900"))     # go2rtc-only bounce
DRY = "--dry-run" in sys.argv


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def stats():
    with urllib.request.urlopen(f"{FRIGATE}/api/stats", timeout=10) as resp:
        return json.loads(resp.read())


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def restart_frigate():
    subprocess.run(
        ["docker", "compose", "-f", f"{COMPOSE_DIR}/docker-compose.yml", "restart", "frigate"],
        capture_output=True, timeout=180,
    )


def restart_go2rtc():
    """Re-dial every nest source without touching Frigate.

    s6 supervises go2rtc inside the container, so killing the process brings it
    straight back (~5 s) and all six cameras negotiate fresh WebRTC sessions.
    This is the cheap first-line recovery: it costs 6 ExecuteDeviceCommand calls
    (well inside the 10/min budget) and does not disturb Frigate's detect
    threads, recordings or the API.
    """
    subprocess.run(
        ["docker", "exec", "frigate", "pkill", "-f", "/config/go2rtc"],
        capture_output=True, timeout=30,
    )


def missing_capture_cams(cams):
    """Cameras whose frigate.capture process no longer exists inside the container.

    The kernel OOM killer takes out the biggest process in the container's cgroup, which on this
    box is a single leaking `frigate.capture:<cam>` (2026-11-17: basement, 10 GB). The container
    itself keeps running, so docker never restarts it, and Frigate keeps serving that camera's last
    stats: camera_fps stays at a stale non-zero value (92 here) and latest.jpg stays frozen. The
    0-fps test above can never see it. Stats expose the (container-namespace) capture_pid, so ask
    the container whether that pid still exists.

    Fails open: if the container cannot be queried at all, report nothing rather than every camera.
    """
    pids = {k: v.get("capture_pid") for k, v in cams.items() if v.get("capture_pid")}
    if not pids:
        return set()
    try:
        res = subprocess.run(["docker", "exec", "frigate", "ls", "/proc"],
                             capture_output=True, text=True, timeout=20)
    except Exception:  # noqa: BLE001
        return set()
    if res.returncode != 0:
        return set()
    alive = {int(x) for x in res.stdout.split() if x.isdigit()}
    return {k for k, p in pids.items() if int(p) not in alive}


def main():
    try:
        st = stats()
    except Exception as exc:  # noqa: BLE001
        log(f"Cannot reach Frigate API: {exc}")
        sys.exit(1)

    cams = st.get("cameras") or {}
    gone = missing_capture_cams(cams)
    if gone:
        log(f"capture process missing for {sorted(gone)} (killed - stale stats would hide it)")
    dead = sorted(k for k, v in cams.items() if not v.get("camera_fps") or k in gone)
    state = load_state()
    streak = state.get("streak") or {}
    now = time.time()

    if not dead:
        log(f"All {len(cams)} cameras OK")
        if streak or state.get("last_restart"):
            save_state({})
        return

    for cam in list(cams):
        if cam in dead:
            streak[cam] = int(streak.get(cam, 0)) + 1
        else:
            streak.pop(cam, None)

    ripe = [c for c in dead if streak.get(c, 0) >= DEAD_CHECKS]
    last_restart = float(state.get("last_restart", 0) or 0)
    last_go2rtc = float(state.get("last_go2rtc", 0) or 0)

    if not ripe:
        log(f"{len(dead)} camera(s) at 0 fps {dead} - first sighting, rechecking next tick")
        state["streak"] = streak
        save_state(state)
        return

    # A killed capture process is not a stream problem: re-dialling go2rtc cannot bring it back, so
    # skip the cheap first line and go straight to the Frigate restart when that is all that is wrong.
    only_gone = all(c in gone for c in ripe)

    # Cheap first line: bounce go2rtc (re-dials all six, Frigate untouched).
    if not only_gone and now - last_go2rtc >= GO2RTC_COOLDOWN:
        log(f"{len(ripe)} camera(s) dead {ripe} - restarting go2rtc to re-dial")
        if DRY:
            return
        try:
            restart_go2rtc()
        except Exception as exc:  # noqa: BLE001
            log(f"go2rtc restart failed: {exc}")
        state["last_go2rtc"] = now
        state["streak"] = {}
        save_state(state)
        return

    if now - last_restart < RESTART_COOLDOWN:
        left = int(RESTART_COOLDOWN - (now - last_restart))
        log(f"{len(ripe)} camera(s) dead {ripe} - go2rtc already bounced, "
            f"restart suppressed, {left}s of cooldown left")
        state["streak"] = streak
        save_state(state)
        return

    log(f"{len(ripe)} camera(s) still dead {ripe} after a go2rtc bounce - restarting Frigate")
    if DRY:
        return
    try:
        restart_frigate()
    except Exception as exc:  # noqa: BLE001
        log(f"restart failed: {exc}")
        sys.exit(1)
    save_state({"last_restart": now, "last_go2rtc": last_go2rtc, "streak": {}})


if __name__ == "__main__":
    main()
