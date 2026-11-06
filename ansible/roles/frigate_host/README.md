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
