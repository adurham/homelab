# pet-accident-detector

Local-only, **event-driven** VLM pet-accident detector. It subscribes to
Frigate's MQTT event stream and, when a cat *leaves* a monitored room, asks a
local Qwen2.5-VL model "is there a genuine pet accident on the floor?" On a
confident yes it sends a rich iOS notification through Home Assistant with an
inline preview, the model's reason, and a red box drawn around the suspected
area.

Nothing leaves the LAN except the final Apple push notification.

## Trigger model (hybrid: event-driven + periodic)

The original version polled every camera every 15 minutes and ran the expensive
VLM blindly on a schedule. The correct design is: **Frigate detects the activity
→ that triggers the VLM** — but the cat room is a special case, so there are two
modes:

**Event-driven** (`EVENT_DRIVEN` in the daemon) — `basement`, `foyer`,
`kitchen_display`. These are visitor rooms that actually go EMPTY. The trigger is
a `cat` object event *ending* (`type == "end"`) — i.e. "the cat just left." That
is the right moment to look for a mess: the accident persists after the cat
leaves, and while the cat is in frame it's usually standing on or obscuring the
spot. The daemon waits `SETTLE_SEC` (30s) for the cat to clear the frame, then
grabs a fresh frame and checks it. The VLM only runs on real cat activity — a
quiet night is zero VLM calls instead of 96.

**Periodic** (`PERIODIC` in the daemon) — `cat_room`. The cat room ALWAYS has
cats in it, so the "cat left" trigger would never fire and the room never shows a
clear floor. Event-driven monitoring would effectively blind the single most
important camera (the litter area). So the cat room is checked on a fixed timer
instead — every 15 min, cats-in-frame and all (the VLM prompt is told to ignore
pets), with no settle delay (waiting wouldn't empty the room). The per-camera
1-hour cooldown still caps it to at most one alert per cycle.

To change which camera is in which mode, edit the `EVENT_DRIVEN` / `PERIODIC`
dicts at the top of `cat_accident_daemon.py`. `PERIODIC` maps
`camera -> (label, interval_seconds)`.

## Where it runs

Unlike the rest of this repo (Proxmox / LXC infra deployed by Ansible), the
detector daemon runs on the **MacBook Pro** (`192.168.86.74`) as a launchd
LaunchAgent. The canonical live copy lives at:

    ~/.hermes/pet-accident-detector/cat_accident_daemon.py
    ~/.hermes/pet-accident-detector/.venv/         (isolated venv: paho-mqtt + Pillow)

This directory is the **tracked source of truth**. After editing here, sync to
the live location and restart the daemon:

    cp pet-accident-detector/cat_accident_daemon.py ~/.hermes/pet-accident-detector/
    launchctl kickstart -k gui/$(id -u)/com.adurham.petaccident

## Architecture

```
Frigate (CT 170, detects cat/person on all cams)
   │  publishes object lifecycle events
   ▼
MQTT broker  ── Mosquitto add-on on HA host (core_mosquitto, :1883)
   │  topic: frigate/events   (login: frigate)
   ▼
cat_accident_daemon.py  (Mac, launchd, isolated venv)
   │  on cat event "end" in a monitored room:
   │    wait SETTLE_SEC → go2rtc fresh frame → Qwen2.5-VL verdict (+reason)
   │    └─ if confident accident: Qwen2.5-VL bbox → draw red box (Pillow, in-proc)
   │       → scp annotated frame to HA /config/www → HA mobile_app notify
   ▼
iPhone rich push: title + reason + inline boxed preview (works remotely via Nabu Casa)
```

Also, because HA's own MQTT integration is wired to the same broker, Frigate's
events now flow into HA as **native entities** (cat occupancy binary sensors per
camera, clip/snapshot browsing) — a free bonus of doing MQTT properly, usable
well beyond this detector.

## Components

| Piece            | Where                                                        | Notes |
|------------------|-------------------------------------------------------------|-------|
| Detector daemon  | `~/.hermes/pet-accident-detector/cat_accident_daemon.py`    | launchd LaunchAgent, isolated venv |
| Process manager  | `~/Library/LaunchAgents/com.adurham.petaccident.plist`      | RunAtLoad + KeepAlive (restart on crash/reboot) |
| MQTT broker      | Mosquitto add-on (`core_mosquitto`) on HA host `:1883`      | logins: `frigate`, `homeassistant`; passwords NOT in repo |
| Event source     | Frigate `frigate/events` MQTT topic                         | `frigate_mqtt_enabled: true` in `roles/frigate_host` |
| VLM server       | Mac Studio node 1 `192.168.86.201:8090`                     | `Qwen2.5-VL-7B-Instruct-4bit`, isolated venv |
| Frame source     | go2rtc `192.168.86.85:1984/api/frame.jpeg`                  | reliable real frames |
| Notification     | HA `notify/mobile_app_adams_iphone_16`                      | iOS rich push (`data.image`) |
| Image hosting    | HA `/config/www/accident_<cam>.jpg` → `/local/...`          | resolves on-LAN AND remotely via Nabu Casa cloud |

Monitored cameras: `basement`, `foyer`, `kitchen_display` (event-driven) and
`cat_room` (periodic, every 15 min).

## Secrets (none committed)

- Broker passwords for `frigate` / `homeassistant` were generated at setup and
  live only in the Mosquitto add-on options and:
  - Frigate side: vault var `frigate_mqtt_password` in
    `ansible/inventory/group_vars/all.yml` (ansible-vault encrypted).
  - Daemon side: `FRIGATE_MQTT_PASSWORD` in `~/.hermes/.env` (local, gitignored).
  - HA core's broker password lives in HA's MQTT config entry.
- SSH key for shipping frames to HA: `id_petaccident` (ed25519) at
  `~/.hermes/pet-accident-detector/`. Only `id_petaccident.pub` is committed;
  the private key is gitignored. The pubkey is in the `core_ssh` add-on's
  `authorized_keys` option.

## Why a dedicated on-disk SSH key (the image-attachment gotcha)

The notification's inline image is the annotated frame, served from HA
`/config/www`. The daemon `scp`s the frame there. **It must use a dedicated
on-disk key (`-i id_petaccident -o IdentitiesOnly=yes`), NOT an ssh-agent key.**

The daemon runs under launchd, which has **no access to the user's ssh-agent**.
The interactive shell authenticates to HA with an agent-only key (the on-disk
`id_*` files don't even exist), so `scp` "just works" by hand — but under
launchd it fails with `Permission denied (publickey)`. When that happens the
frame never reaches HA, `notify_ha` is called with no image URL, and the push
arrives as **text-only with nothing to expand to**. The daemon log line shows
`img=False` in that failure mode. The fix is the committed dedicated key.

(To view a working alert's image on iOS: long-press / pull down the
notification to expand it — the boxed image is an attachment, not shown in the
collapsed banner.)

## Notification design

iOS *rich* notification:
- **Title:** `Pet Accident? — <Camera>`
- **Body:** the model's one-sentence reason + confidence.
- **Inline image:** annotated frame with a red box around the suspected area
  (from a Qwen2.5-VL grounding pass). Tapping opens the full image.

The image URL is the relative `/local/accident_<cam>.jpg`; Nabu Casa cloud means
the companion app resolves it at home and away.

> One-time HA setup that makes `/local/` work: HA only registers the `www`
> static route at startup. After first creating `/config/www`, HA was restarted
> once. Noted here for rebuilds.

## Tuning / false-positive control

There are three layers, all aimed at the dominant failure mode (false positives —
a 7B model glancing at a busy room):

1. **Prompt** (`PROMPT`). Ignores the common cat-room FP sources (water/food
   bowls, litter boxes, litter, toys, beds, mats, and especially light pools /
   glare / reflections on hard floors). Hardened 2026-06-02 against the observed
   "dark/irregular puddle near the center" pattern, which is almost always a
   shadow or a darker tile, not liquid: the prompt now demands positive evidence
   of WETNESS (glossy sheen, meniscus/edge, specular highlight, spreading stain),
   not just a dark shape, and treats soft-edged dark shapes as shadows.

2. **Multi-frame consensus** (`CONSENSUS_FRAMES` / `CONSENSUS_GAP_SEC` /
   `CONSENSUS_NEEDED`). When the first frame says "accident," the daemon grabs N
   more frames a few seconds apart and only alerts if all agree. A real accident
   is stable across seconds; transient triggers (shadows, shifting glare, a cat
   moving through, motion blur) flicker between frames and get filtered out. This
   is the structural FP killer — verified against the exact frames that flip-
   flopped "puddle"/"clean" minutes apart in early testing. Default 3/3 (strict).

3. **Evidence corpus** (`EVIDENCE_DIR`, `~/.hermes/pet-accident-detector/
   evidence/`, gitignored). Every candidate positive saves its frames + verdicts,
   tagged by outcome: `rejected` (first glance yes, consensus no — the most
   valuable FP examples), `alert` (consensus confirmed), and a ~10% sample of
   `negative` frames for balance. Auto-pruned to `EVIDENCE_KEEP_DAYS` (14) so it
   can't grow unbounded. This is what makes *evidence-based* prompt tuning
   possible: after a few days, look at the `rejected`/`alert` frames and tune the
   prompt against real images that actually fooled (or nearly fooled) the model,
   instead of guessing.

Per-camera 1-hour cooldown (`COOLDOWN_SEC`) still caps repeat alerts while a real
accident persists.

The notification also carries the frame + boxed area + reason, so a live false
alert is itself a tuning example — expand it, and tell me; I'll tune the prompt
against that exact frame (the way the water-bowl and shadow-puddle FPs were
killed).

### Tuning workflow (after corpus builds up)

```bash
ls ~/.hermes/pet-accident-detector/evidence/        # *_rejected.* are the gold
# eyeball the rejected/alert .jpg + .txt pairs, then adjust PROMPT in the daemon
# (or the CONSENSUS_* knobs), re-sync, restart:
cp pet-accident-detector/cat_accident_daemon.py ~/.hermes/pet-accident-detector/
launchctl kickstart -k gui/$(id -u)/com.adurham.petaccident
```

## Operate

```bash
# status
launchctl list | grep petaccident
tail -f ~/.hermes/logs/cat_accident_daemon.log

# restart after an edit
launchctl kickstart -k gui/$(id -u)/com.adurham.petaccident

# stop / start
launchctl bootout  gui/$(id -u)/com.adurham.petaccident
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.adurham.petaccident.plist
```

The daemon logs every event it sees and every verdict, so the log is the source
of truth for "did it look, and what did it decide."
