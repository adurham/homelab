# pet-accident-detector (v4)

An event-driven pet-accident detector for the Frigate cameras. When a cat
leaves a room, it grabs a fresh frame, asks a vision model whether there is a
genuine accident on the floor, confirms across several frames, and pushes a
rich iOS notification through Home Assistant with the annotated frame.

This is the revival of the 2026 `pet-accident-detector` daemon that used to run
on the MacBook against the exo cluster. The trigger model and prompt are
inherited; the runtime is now a systemd user service on `amd-workstation`
(always on, no laptop required), and the VLM is the same `gemma4:31b` the
Hermes vision tool uses.

## Flow

```
Frigate (CT 170)  --frigate/events-->  MQTT (HA Mosquitto)
                                          |
                                          v
                             detector.py (systemd --user)
                                          |
              cat event ends, settle 30s, fresh /api/<cam>/latest.jpg
                                          |
                         local gate (floor-change score, shadow)
                                          |
                       gemma4 verdict (+ 2 more frames, 3/3 consensus)
                                          |
                   bbox pass -> annotate -> scp to HA /config/www
                                          |
                     notify.mobile_app_* (image + reason + confidence)
```

## Cameras / trigger model

| Camera | Mode | Why |
|---|---|---|
| `foyer` | event | room empties; check when the cat leaves |
| `basement` | event | same, as soon as its Nest stream is healthy |
| `cat_room` | periodic (15 min) | litter area is never empty, so "cat left" never fires |

`mode: event` cameras are checked on a Frigate `cat` event of type `end`, after
`settle` seconds so the cat clears the frame. `mode: periodic` cameras are
checked on a fixed interval and the prompt tells the model to ignore pets.

## The local detector (current state and honest limits)

A generic pretrained detector cannot tell urine from a shadow; that is the
whole difficulty of this task. So the local part is a **pre-gate**, not a
verdict: `localgate.py` compares the current frame against a per-camera
"clean floor" baseline in CIELAB space and scores the largest changed blob,
requiring a **colour** change so that shadows and light pools (which are
multiplicative luminance changes) do not score. It is numpy + Pillow, a few
milliseconds per frame.

- `gate.mode: shadow` (default) scores every check and writes the score into
  the evidence file, but still runs the VLM. This is how the gate gets
  calibrated against real frames without risking missed accidents.
- `gate.mode: enforce` skips the VLM when the score is below the threshold.
- `gate.mode: off` disables it.

The evidence corpus (`~/.local/share/pet-accident-detector/evidence/`) keeps
every alert, every consensus rejection, and a 10% sample of negatives, with the
gate score and the VLM verdict. That corpus is the training set for the real
local detector: once enough labelled floor crops exist, a small
MobileNet/EfficientNet-class classifier (ONNX, ~10 ms on CPU) can replace most
VLM calls, with the VLM kept as the fallback for uncertain cases.

The old June corpus (84 events) is all negatives/rejections - the detector has
no confirmed accident frames yet. That is why the local classifier is a
follow-up, not something that can be trained today.

### Fully local VLM

`analyzer` speaks the Ollama HTTP API, so pointing it at a local ollama
(`http://127.0.0.1:11434`) makes the whole pipeline local. The workstation has
no discrete GPU, so a 4B-class VLM runs on CPU (tens of seconds per frame);
that is fine for event-driven checks but has not been quality-tested against
gemma4:31b yet. The cloud default is deliberate: it is the accuracy baseline.

The better local target is one of the Mac Studios: an M4 Max with unified
memory runs `gemma4:31b` (19 GB Q4) on Metal comfortably, which gives the same
model quality with no cloud call. Install ollama there, pull `gemma4:31b`, set
`analyzer.base_url` to the Studio's tailnet address and keep the cloud entry as
`analyzer.fallback` so a sleeping Studio degrades instead of going blind.

## Files

| File | Purpose |
|---|---|
| `detector.py` | daemon + CLI (`--check`, `--notify-test`, `--gate`, `--fetch`) |
| `localgate.py` | CIELAB floor-change scorer |
| `config.yaml` | cameras, timings, analyzer, gate, notify |
| `deploy/pet-accident-detector.service` | systemd user unit |
| `requirements.txt` | paho-mqtt, pyyaml, pillow, numpy |

Runtime state, baselines, evidence and logs live in
`~/.local/share/pet-accident-detector/`.

## Install / operate

Production runs in the lab as CT 171 (`pet-detector-01`, pve03, .18), deployed
with `ansible-playbook deploy_pet_detector.yml`; see
`ansible/roles/pet_detector/README.md` for the one-time CT creation and the
hand-provisioned secrets. The workstation user unit below is for development
only.

```bash
cd ~/repos/homelab/pet-accident-detector
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp deploy/pet-accident-detector.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pet-accident-detector.service

journalctl --user -u pet-accident-detector.service -f
.venv/bin/python detector.py --check foyer     # one-shot verdict, no alert
.venv/bin/python detector.py --gate foyer      # gate score vs baseline
.venv/bin/python detector.py --notify-test foyer
```

On the CT, use `journalctl -u pet-accident-detector -f` instead. Secrets are
read from `~/.hermes/.env` (`HASS_URL`, `HASS_TOKEN`, `OLLAMA_API_KEY`) and
`~/.config/pet-accident-detector/env` (all four vars on the CT, mode 600). The
HA image upload uses the dedicated `id_petaccident` key against HA's
`core_ssh` add-on on port 2222.

## Operational notes

- **Nest/go2rtc stream flapping.** Frigate's six Nest cameras do not all stay
  up at once: after a container restart `cat_room` and `foyer` came back while
  `basement`, `driveway`, `backyard` and `front_porch` dropped with go2rtc
  "Output file does not contain any stream". The detector logs a black frame
  as "camera offline" and skips it rather than alerting on it. This is a
  Frigate/go2rtc concurrency problem, not a detector bug; `cat_room` (the one
  that matters most) is healthy after a restart.
- **False positives are the failure mode.** The prompt rejects glare, shiny
  floors, shadows and bowls, and a candidate must survive 3/3 consensus
  several seconds apart. A real accident is stable; a shadow flickers.
- **Every check is inspectable.** The evidence `.txt` records the gate score
  and each frame's raw verdict, so a bad alert comes with the exact frames
  needed to tune against.
- **Cooldown** is per camera (1 h) so a persistent mess does not spam.
