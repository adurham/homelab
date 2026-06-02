# pet-accident-detector

Local-only, **event-driven** VLM pet-accident detector. It subscribes to
Frigate's MQTT event stream and, when a cat *leaves* a monitored room, asks a
local Qwen2.5-VL model "is there a genuine pet accident on the floor?" On a
confident yes it sends a rich iOS notification through Home Assistant with an
inline preview, the model's reason, and a red box drawn around the suspected
area.

Nothing leaves the LAN except the final Apple push notification.

## Why event-driven (and not polling)

The original version polled every camera every 15 minutes and ran the expensive
VLM blindly on a schedule. That's wasteful and slow to react. The correct design
is: **Frigate detects the activity → that triggers the VLM**.

Specifically, the trigger is a `cat` object event *ending* (`type == "end"`) on
a monitored camera — i.e. "the cat just left." That is the right moment to look
for a mess: the accident persists after the cat leaves, and while the cat is in
frame it's usually standing on or obscuring the spot. So the daemon waits
`SETTLE_SEC` for the cat to clear, then grabs a fresh frame and checks it.

Result: the VLM only runs on real cat activity. A quiet night = zero VLM calls
instead of 96.

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

Monitored cameras: `cat_room`, `basement`, `foyer`, `kitchen_display`.

## Secrets (none committed)

- Broker passwords for `frigate` / `homeassistant` were generated at setup and
  live only in the Mosquitto add-on options and:
  - Frigate side: vault var `frigate_mqtt_password` in
    `ansible/inventory/group_vars/all.yml` (ansible-vault encrypted).
  - Daemon side: `FRIGATE_MQTT_PASSWORD` in `~/.hermes/.env` (local, gitignored).
  - HA core's broker password lives in HA's MQTT config entry.

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

## Tuning

The detection prompt (`PROMPT`) ignores the common cat-room false-positive
sources: water/food bowls, litter boxes, scattered litter, toys, beds, mats, and
especially **light pools / glare / reflections on hard floors**. It flags only a
liquid puddle with a distinct irregular edge, a solid feces pile, or vomit; when
uncertain it answers no. Per-camera 1-hour cooldown (`COOLDOWN_SEC`) prevents
repeat spam while a real accident persists.

It is a 7B model watching a busy room — expect occasional misjudgements. Tune the
prompt against real false/missed examples (the notification now carries the frame
+ boxed area + reason, which is exactly what you need to tune against).

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
