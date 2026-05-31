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

- Creates CT 170: 4 cores / 8 GiB RAM / 60 GiB rootfs on `nvme-data`.
- `eth0` on `vmbr0` (DHCP) so Frigate can reach the go2rtc RTSP source and HA
  on the LAN; `eth1` on the `private` SDN at `ip_frigate` (172.16.0.45).
- Deploys `config.yml` (one camera: `cat_room`, CPU detector, tracks
  person+cat, 2-day record retention) and `docker-compose.yml`.

## Not managed here

- **go2rtc** — the RTSP source `rtsp://192.168.86.2:8554/cat_room` is assumed
  already running on the HA host.
- **MQTT** — disabled by default (`frigate_mqtt_enabled: false`). The repo has
  no committed MQTT broker config or vault credentials, so HA event
  integration is off until a broker (Mosquitto add-on on the HA host) is
  confirmed and `frigate_mqtt_user`/`frigate_mqtt_password` are added as vault
  vars. See `defaults/main.yml`.

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
