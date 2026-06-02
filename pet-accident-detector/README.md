# pet-accident-detector

Local-only VLM pet-accident detector. Every 15 minutes it samples frames from
the hardwired Nest cameras (via go2rtc), asks a local Qwen2.5-VL model "is there
a genuine pet accident on the floor?", and on a confident yes sends a rich iOS
notification through Home Assistant with an inline preview, the model's reason,
and a red box drawn around the suspected area.

Nothing leaves the LAN except the final Apple push notification.

## Where it runs

Unlike the rest of this repo (Proxmox / LXC infra deployed by Ansible), this
detector runs as a **Hermes cron job on the MacBook Pro** (`192.168.86.74`),
not on a server. The canonical copy of the script lives at:

    ~/.hermes/scripts/cat_accident_check.py

This directory is the **tracked source of truth**. After editing here, sync to
the live location:

    cp pet-accident-detector/cat_accident_check.py ~/.hermes/scripts/cat_accident_check.py

(There is no Ansible role because there is no remote host to provision — the
script, the VLM, and the cron all live on the Mac.)

## Pipeline

```
go2rtc frame.jpeg  ->  Qwen2.5-VL verdict (+reason)
                       └─ if "accident: yes" (not low-confidence):
                            -> Qwen2.5-VL bounding box (grounding 2nd pass)
                            -> draw red box + "ACCIDENT" label (Pillow)
                            -> scp annotated frame to HA /config/www
                            -> HA mobile_app notify (inline image + reason)
```

## Components

| Piece            | Where                                            | Notes |
|------------------|--------------------------------------------------|-------|
| Detector script  | `~/.hermes/scripts/cat_accident_check.py`        | no_agent Hermes cron, `*/15 * * * *` |
| VLM server       | Mac Studio node 1 `192.168.86.201:8090`          | `mlx-community/Qwen2.5-VL-7B-Instruct-4bit`, isolated venv — separate from exo/DeepSeek |
| Frame source     | go2rtc `192.168.86.85:1984/api/frame.jpeg`       | reliable real frames; NOT Frigate's flaky `latest.jpg` |
| Notification     | HA `notify/mobile_app_adams_iphone_16`           | iOS rich push (`data.image`) |
| Image hosting    | HA `/config/www/accident_<cam>.jpg`              | served at `/local/...`, resolves on-LAN AND remotely via Nabu Casa cloud |

Cameras monitored: `cat_room`, `basement`, `foyer`, `kitchen_display`.

## Notification design

The push is an iOS *rich* notification:
- **Title:** `Pet Accident? — <Camera>`
- **Body:** the model's one-sentence reason + confidence (e.g.
  "brown solid pile on tile near the left wall (high confidence)").
- **Inline image:** the annotated frame with a red box around the suspected
  area. Tapping it opens the full image, not just the HA app.

The image URL is the relative `/local/accident_<cam>.jpg`. Because Nabu Casa
cloud is active, the HA companion app resolves that both at home and away.

> One-time setup that makes `/local/` work: HA only registers the `www` static
> route at startup. After first creating `/config/www`, HA must be restarted
> once. Already done — noted here for rebuilds.

## Why it's structured the way it is

- **Concurrent camera checks.** Cameras are independent network I/O. A cold or
  battery-off Nest stream can burn ~60s of frame-fetch retries; checking the 4
  cameras serially summed past the Hermes cron 120s budget (causing
  "script failed" timeouts). Running them in a thread pool collapses wall-clock
  to the *slowest single camera* (~60s worst case), comfortably under budget.
  This is the real fix for the timeouts, not a raised timeout.
- **Box-drawing shells out to Homebrew python.** Hermes cron runs scripts under
  hermes-agent's venv, which has no Pillow. Rather than pollute that prod venv,
  the annotation step subprocesses to `/opt/homebrew/bin/python3` (Pillow
  present). If that's unavailable it degrades gracefully to the un-annotated
  frame (still with preview + reason).
- **go2rtc, not Frigate `latest.jpg`.** Frigate's snapshot endpoint serves a
  placeholder during detect reconnects even while detection/recording keep
  working; go2rtc's `frame.jpeg` returns real frames with retry.

## Tuning

The detection prompt (`PROMPT` in the script) is tuned to ignore the common
false-positive sources in a busy cat room: water/food bowls, litter boxes,
scattered litter, toys, beds, mats, and especially **light pools / glare /
reflections on hard floors** (the big one). It flags only a liquid puddle with
a distinct irregular edge, a solid feces pile, or vomit; when uncertain it
answers no.

Per-camera 1-hour cooldown (`COOLDOWN_SEC`) prevents repeat spam while a real
accident persists.

It is a 7B model watching a busy room — expect occasional misjudgements. Tune
the prompt against real false/missed examples as they come in.

## Cron job

Hermes cron job `dd1e51ead3be` ("Pet accident detector"), `no_agent`,
`*/15 * * * *`. Silent unless an alert fires or the script errors.

## Manual run / test

```bash
# real run (silent unless an accident is detected)
~/repos/hermes-agent/.venv/bin/python ~/.hermes/scripts/cat_accident_check.py
```
