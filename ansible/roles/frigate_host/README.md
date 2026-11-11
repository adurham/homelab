# roles/frigate_host

Provisions the Frigate NVR LXC (`frigate-01`, CT 170) on `pve01` and deploys
Frigate as a Docker container inside it for CPU-based object detection.

LXC creation mirrors `roles/monitoring_host` exactly (pveam template fetch →
cluster-wide existence check via `pvesh get /cluster/resources` → `pct create`
→ internal-DNS resolver fix → post-create start). The container is
**unprivileged with `nesting=1`** because Frigate runs in Docker, which needs
nesting.

The second half installs Docker (get.docker.com convenience script) and brings
up Frigate via `docker compose`, all dispatched through `pct exec` from the
proxmox host — so the whole stand-up is one play against `pve01`.

## What it does

- Creates CT 170: 8 cores / 8 GiB RAM / 60 GiB rootfs on `nvme-data`.
- `eth0` on `vmbr0` (DHCP) so Frigate can reach HA's MQTT on the LAN;
  `eth1` on the `private` SDN at `ip_frigate` (172.16.0.45).
- Deploys `config.yml` (Nest cameras via go2rtc, CPU detector, tracks
  person+cat, snapshots only — no recording) and `docker-compose.yml`.
- Mounts a **patched go2rtc binary** at `/config/go2rtc` inside the Frigate
  container. The patch fixes the Nest stream-extend timer bug (stock go2rtc
  fires the timer once and never re-arms, so each Nest WebRTC session dies
  ~5 min in). The patched binary re-arms in a loop indefinitely.

### Upgrading the patched go2rtc binary

The binary has to track upstream: HA's `go2rtc` integration raises a
`recommended_version` repair whenever the connected server is older than the
version it recommends (`current_version < recommended_version`), and
`configuration.yaml` points HA at this Frigate's go2rtc on `:1984`. Version
2026.11 recommends **1.9.15**; the binary shipped here was `1.9.14+dev.dc1685e`.

The carried patch lives in `files/go2rtc-nest.patch` and applies cleanly to
upstream `v1.9.15`. `files/build-go2rtc-patched.sh` does the whole cycle on
frigate-01 (build needs no root; the install step is sudo/YubiKey-gated):

```
scp ansible/roles/frigate_host/files/{go2rtc-nest.patch,build-go2rtc-patched.sh} amd@frigate-01:/tmp/
ssh -tt -A amd@frigate-01 'bash /tmp/build-go2rtc-patched.sh 1.9.15 --install'
```

Notes that cost time to rediscover:

- **Static build only** (`CGO_ENABLED=0`) — a dynamic build from a newer glibc
  dies in Frigate's Bookworm image (`Verneed record`). The old failing binary is
  still on disk as `go2rtc_patched.broken`; ignore/remove it.
- Build the Go toolchain locally under `~/go-toolchain`; the CT ships no Go.
  v1.9.15's `go.mod` requires `go >= 1.26`.
- The version string comes from VCS stamping, so a patched tree reports
  `1.9.15+dev.<sha>` — that is intentionally *greater* than `1.9.15` for
  awesomeversion and clears the repair.
- **sudo on fleet hosts needs a TTY plus agent forwarding** (`ssh -tt -A` with
  `~/.ssh/id_ansible`); without `-tt`, `sudo` fails with "a password is
  required" even though the YubiKey is signing.
- HA never deletes the `recommended_version` issue once raised (the component
  only deletes `unsupported_version`); after upgrading, clear the stale entry
  with `repairs/ignore_issue {domain: go2rtc, issue_id: recommended_version}` —
  it would otherwise linger until a Core restart deactivates it.

### Camera tile placeholders = a stalled Nest session, not an HA problem

A tile reading **"No frames have been received, check error logs"** is Frigate's
own placeholder JPEG (byte-identical every time, ~51.8 kB) served by
`/api/<cam>/latest.jpg` when that camera has produced nothing for a while. The
HA card is innocent - it renders whatever that URL returns.

Diagnose from Frigate, not HA: `/api/stats` shows `camera_fps` per camera, and
0.0 for a camera whose go2rtc `nest:` session is still *connected* but no longer
delivering frames (`/api/streams?src=<cam>_raw` still shows a live WebRTC
producer with bytes flowing). `docker compose restart frigate` clears it and the
cameras come back in ~2 minutes; per-camera recovery is **not** possible -
go2rtc refuses to delete a config-defined stream (`DELETE /api/streams?src=X`
-> 400) and re-PUTting an identical source is a no-op.

`/opt/frigate/camera_health.py` (installed by this role, cron every 5 min) does
that restart automatically. It waits for `DEAD_CHECKS` consecutive 0-fps ticks
(30 min) with a 1-hour cooldown: a drop takes 1-2 min to re-establish, so
shorter thresholds restart healthy cameras during ordinary churn. The previous
version required **4 or more** stalled cameras before acting, so the common
case - one to three dead - sat broken indefinitely while the log said
"waiting for recovery".

### Quota limiter (carried patch) — what it fixed and what it did not

Google's Device Access limits every `ExecuteDeviceCommand` call (both
`GenerateWebRtcStream` and `ExtendWebRtcStream`) to **10 per minute per project
and user**, 5/min per device+command, 30/min and 100/h per camera. Six cameras
dialing at boot, plus go2rtc's 3x30s retry loop, spent that in seconds and the
whole fleet starved on `429 RESOURCE_EXHAUSTED`.

`files/go2rtc-nest-quota.patch` (built after `go2rtc-nest.patch`) adds
`pkg/nest/limiter.go`: a sliding-window limiter that books a slot in every
applicable window *before* a call goes out, fails a dial fast (5 s) so Frigate
retries later instead of storming, lets keep-alives wait up to 50 s, and holds
the project off for a minute after a real 429. Instrumented builds log
`nest: call dev=… cmd=… status=…` and `nest: throttled …`.

Verified 2026-11-10: in steady state every call returns 200 and there are no
429s — the API layer is now healthy. It did **not** stop the cameras dropping:
sessions still lapse every 1-2 minutes while extends return 200, which points at
the media path (UDP/NAT between Nest's WebRTC peer and this CT), not the API.

### Disable HA's Nest integration while Frigate owns the cameras

HA's `nest` config entry competes for the same SDM sessions: while it was loaded,
go2rtc's keep-alives came back `400 FAILED_PRECONDITION` ("invalid session or user
id mismatch") every couple of minutes for the two cameras the integration was
touching (basement, driveway) - Google treats the second client as taking over the
session. Disabling the entry (Settings -> Devices & Services -> Nest -> Disable)
left every SDM call at `status=200` with no 400s and no 429s in a 10-minute
window. Nothing in the repo used the integration's entities (its only camera,
`camera.basement_camera`, has no consumer), so it stays disabled.

### WebRTC media needs a public mapping — and Nest Wifi only speaks NAT-PMP

Nest's peer sends media to the candidate we advertise. With only a private
`192.168.86.17:8555` candidate, `tcpdump -ni any "udp port 8555"` on the CT shows
**nothing**: no media ever arrives, Frigate reports 0 fps, and go2rtc cannot even
produce a frame.jpeg from the stream while the SDM API happily returns 200.

The gateway here is a **Nest Wifi**: no admin API, no UPnP IGD (`upnpc -s` only
finds the Hue bridge), but it *does* answer **NAT-PMP**. `frigate-natpmp-renew.sh`
(+ `frigate-natpmp.timer`, every 30 min) maps public UDP 8555 -> the CT, and
go2rtc advertises `stun:8555` so it learns that public ip:port itself. That is
the whole router-side setup - nobody needs to open the Google Home app.

### Experiments that did NOT fix the media decay (do not repeat)

Every one of these was measured on the live fleet, 2026-11-10/11:

| change | result |
|---|---|
| quota limiter (10/min project budget) | fixes 429 storms, calls all 200 — **keep** |
| HA `nest` integration disabled | `400 invalid session` disappears — **keep disabled** |
| NAT-PMP mapping + `stun:8555` candidate | media flows for a while, then decays |
| drop go2rtc `preload` | no 400s at all, but **0/6 live** — preload is required |
| read `<cam>_raw` directly (no restream) | 1/6 |
| only 3 cameras enabled (concurrency test) | **0/3** — not a concurrency limit |
| upstream PR #2493 (`nest: keep sessions alive…`) | 0–2/6, worse than the carried patch |

Pattern in every case: SDM dials and extends return 200, then the media stops
after 1–2 minutes and Frigate's fps falls to 0.

### Last-good frames: kill the placeholder tiles

Frigate's placeholder is what makes a stalled camera look *broken*. `lastgood.py`
(systemd `frigate-lastgood.service`, port 8099) polls `/api/<cam>/latest.jpg`
every 15 s, keeps the newest frame whose md5 is not the placeholder and whose
size clears 20 kB, and serves it at `http://<frigate>:8099/<cam>.jpg` with
`Cache-Control: no-store`.

The six generic-camera config entries now use that URL as `still_image_url`, so
a camera that is mid-flap shows its last good picture instead of the error card.
Change it through the **options flow**, and leave `stream_source` **empty** for
these: if a stream URL is supplied the flow opens it to validate and fails with
`{'stream_source': 'timeout'}` whenever that camera happens to be down (which is
most of the time). The tiles use `camera_view: image`, so no stream is needed.

Also: `platform: generic` is **not** available as YAML — the camera integration
rejects it ("does not support platform setup"), so a YAML fallback camera is not
an option; the config entry is the only route.

### The real cause of the 1-3 minute drops: a per-user SDM rate limit

Measured 2026-11-10 by calling the SDM API directly with the same OAuth client
(no go2rtc involved):

```
429 {"code": 429, "message": "Rate limited for the GenerateWebRtcStream API for the user.",
     "status": "RESOURCE_EXHAUSTED"}
429 {"code": 429, "message": "Rate limited for the ExecuteDeviceCommand API for the user.",
     "status": "RESOURCE_EXHAUSTED"}
```

Google limits stream generation and extends **per user (Nest account)**, not per
camera. Six cameras negotiating at boot plus one extend each per few minutes
sits right at that ceiling, and every other consumer on the same account - HA's
own Nest integration, any manual probing - eats the same budget. When a call
429s, go2rtc's retry loop (in `rtcConn`: 3 attempts, 30 s apart) multiplies the
call rate, so one 429 snowballs into every camera dying.

Do NOT "fix" it by backing off inside go2rtc. Tried: a global 5 s gap between
SDM calls with a 429 penalty growing 10s -> 60s. Result was worse - the penalty
also delays the *extend* calls, sessions lapse while queued, and the fleet goes
to 0/6 live. The patch was reverted; `go2rtc-nest.patch` (per-camera API
instances, re-arming extend timer, serialised dial) is the last known-good.

What actually helps, in order:
1. Fewer concurrent WebRTC streams on the account (the ceiling is the account's,
   not the per-camera one). Moving cameras from Nest/SDM to RTSP removes them
   from this budget entirely.
2. No other SDM consumers on the same Nest account while Frigate is running
   (HA's Nest integration included).
3. Last-good frames on the dashboard (see below) so the user never sees the
   placeholder while the balance is bad.

### Consumers of `frigate_lan_ip` — a stale copy means dead camera tiles in HA

The LAN address is baked into more places than this role. When CT 170 moved from
`192.168.86.85` to `192.168.86.17` (2026-09-18, out-of-pool static), the six
**generic-camera config entries** in Home Assistant kept the old host and every
camera tile on the dashboard went blank — Core logged `Error getting new camera
image from 192_168_86_85: All connection attempts failed` every 5 s, and each
tile was labelled `<entry title> <camera>` (i.e. `192_168_86_85 Cat Room`).

Each Generic Camera entry (Settings → Devices & Services) carries both URLs:

```
still_image_url: http://192.168.86.17:5000/api/<camera>/latest.jpg
stream_source:   rtsp://192.168.86.17:8554/<camera>
```

The still comes from **Frigate's own decoded frame**, not from go2rtc's
`:1984/api/frame.jpeg`. That endpoint spins up a decoder per request and
occasionally hands back a *partial* frame — the bottom ~20-30 px of the JPEG is
the last decoded slice row repeated, i.e. a smeared band along the bottom edge of
every tile. Measured on 2026-11-05: 2 of 15 `frame.jpeg` samples carried a
20+ row identical band, 0 of 15 `/api/<cam>/latest.jpg` samples did, and 0 of 20
after the switch. Frigate's snapshot is a decode of the same
`rtsp://127.0.0.1:8554/<cam>` remux that HA's live view uses, so a clean snapshot
also proves the live stream is clean.

Fix them through the **options flow** (it fetches the still and probes the RTSP
stream before letting you save) — never by editing `.storage`, which HA holds in
memory. Other consumers that must match: `homeassistant/sensors.yaml` (REST
sensor), `homeassistant/configuration.yaml` (go2rtc url),
`automations/mailbox_truck.yaml`, `automations/frigate_watchdog.yaml`, the
Grafana alert description, and the pet-accident detector's out-of-repo copy.

Naming: the entry title is derived from the URL host and cannot be renamed
(`POST/PATCH` on the entry return 405), so the devices are permanently named
`192_168_86_85`. The dashboard tiles therefore set an explicit `name:` on each
`picture-entity` card (`Cat Room`, `Foyer`, …) instead of relying on the entity's
composed friendly name.


The Basement camera is live as of 2026-11-05 (it was offline in Google's cloud
from 2026-10-23 and dropped from Frigate in the interim — see the dated note in
`defaults/main.yml`). Its entry follows the same two URLs as the rest.

## Architecture

Nest WebRTC sources are defined **directly in Frigate's go2rtc config block**
(no standalone go2rtc container). Detection consumes MP4-over-HTTP from
Frigate's own go2rtc on localhost (carries inband H264 SPS/PPS that RTSP
drops). Port 1984 is exposed for the pet-accident detector's frame.jpeg
endpoint.

## Prerequisites before deploy

- Add `frigate_01_root_pass` as a vault var in
  `inventory/group_vars/all.yml` (mirrors `vm_01_root_pass` etc.). The
  playbook references it; deploy will fail without it.

## Deploy

```
cd ansible
ansible-playbook deploy_frigate.yml
```

Frigate UI: `http://<frigate-01 LAN IP>:5000` (or `:8971` for the
authenticated UI).
