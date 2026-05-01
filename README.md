# Homelab Infrastructure Repository

A personal homelab managed as code: Proxmox-based hyper-converged private cloud, Home Assistant smart home automation, and a collection of utility scripts.

## Architecture

This repository manages a hyper-converged private cloud built on Proxmox VE. The lab is treated as a software-defined datacenter, with Ansible providing end-to-end automation of infrastructure, networking, and services.

- **Orchestrator**: Ansible (roles & playbooks).
- **Hypervisor**: Proxmox VE — 3-node cluster (`pve01`, `pve02`, `pve03`).
- **Networking**:
  - **Physical**: LAN (`vmbr0`, `192.168.86.0/24`).
  - **SDN**: VXLAN-based private network (`172.16.0.0/24`) for isolated service communication.
  - **Ingress**: Tailscale Gateway (`172.16.0.101`) for secure remote access and NAT.
- **Identity**: Authentik (`auth.chi.lab.amd-e.com`) with OIDC integration for Proxmox SSO.
- **Storage**: ZFS (NVMe) with automated replication for High Availability.

### Core Services & Addressing

| Service          | Hostname           | Private IP     | Public/LAN         | Description                                       |
| :--------------- | :----------------- | :------------- | :----------------- | :------------------------------------------------ |
| Gateway          | `proxmox` (VNet)   | `172.16.0.1`   | -                  | SDN gateway for the private network               |
| DNS              | `dns-01`           | `172.16.0.10`  | -                  | Internal Bind9 authority (`chi.lab.amd-e.com`)    |
| Identity         | `authentik`        | `172.16.0.20`  | `100.x.y.z` (TS)   | SSO provider; access via load balancer            |
| Load Balancer    | `lb-01`            | `172.16.0.30`  | -                  | Nginx Layer 7 proxy for the cluster and services  |
| Tailscale GW     | `tailscale-gw`     | `172.16.0.101` | `100.x.y.z`        | Ingress / NAT gateway                             |

External access URL: `https://proxmox.chi.lab.amd-e.com` → `lb-01`.

### High Availability

The core infrastructure survives a single-node failure (N-1 redundancy).

- **Mechanism**: Proxmox HA Manager (watchdog) + ZFS replication.
- **Replication rate**: every 15 minutes.
- **Target nodes**: all peers (`pve02`, `pve03`).
- **Protected resources**:
  - `ct:100` — Authentik
  - `ct:101` — Tailscale GW
  - `ct:102` — DNS
  - `ct:103` — Load Balancer

If a node fails, Proxmox HA automatically restarts protected containers on a healthy node. Check status with `ha-manager status` on any node.

## Repository Layout

### `ansible/` — automated provisioning

Manages the lifecycle of LXC containers, VMs, and cluster configuration.

- **Inventory**: `ansible/inventory/proxmox.yml` defines nodes and static IPs for core services.
- **Playbooks** (selected):
  - `deploy_dns.yml` — Bind9 DNS (`dns-01`).
  - `deploy_authentik.yml` — Authentik IDP.
  - `deploy_loadbalancer.yml` — Nginx LB (`lb-01`).
  - `deploy_tailscale_gw.yml` — Tailscale gateway.
  - `configure_sso.yml` — Proxmox OIDC realm & permissions.
  - `manage_ha.yml` — ZFS replication & HA resources.
  - `manage_authentik.yml` — declarative Authentik config (providers, apps, groups).
  - `deploy_tanium_clients.yml` — Tanium client install across mixed OS targets.
  - `deploy_monitoring.yml` — VictoriaMetrics + Grafana.

### `homeassistant/` — smart home automation

Home Assistant configuration deployed to the HA host. Notable subsystems:

- **Water heater circulator pump** — occupancy-driven, with daily runtime limits and cooldown.
- **Lighting automations** — cat room, front porch sconces, garage door motion, stair lighting.
- **Climate control** — Flair vents, Ecobee sensors.
- **Deployment** — `homeassistant/deploy_homeassistant.sh` syncs configs and reloads.

### `scripts/` — utilities

- `bootstrap.sh` — restore terminal/shell setup on a fresh machine (macOS, Debian/Ubuntu, RHEL family, Arch).
- `yubikey_vpn_connect.sh` — YubiKey-based VPN connection.
- `patch_binary.sh` — binary patching helper.
- `tanium/` — Tanium platform tooling (client API, TDS, performance testing, sensors, etc.).

## Operational Procedures

### Deploying Ansible changes

```bash
ansible-playbook -i ansible/inventory/proxmox.yml ansible/<playbook_name>.yml
```

Verify via `https://proxmox.chi.lab.amd-e.com` or SSH.

### Deploying Home Assistant changes

```bash
# Fast path — automations / templates / sensors / inputs / apps.yaml
# (everything that can be hot-reloaded). Reloads automations via API, no
# restart, ~5 seconds.
ansible-playbook ansible/deploy_ha_automations.yml

# Slow path — same plus a full `ha core restart`. Use when
# configuration.yaml changes (anything that requires a restart to take
# effect).
ansible-playbook ansible/deploy_ha_automations.yml -e ha_restart=true
```

### Bootstrapping a new workstation

```bash
./scripts/bootstrap.sh
```

### Opening Tanium Postgres for the lab subnet

Lab-only convenience: adds a passwordless ("trust") `pg_hba.conf` entry
scoped to `172.16.0.0/24` and opens the listener port in iptables on all
four Tanium platform appliances (TS x2, TMS x2). Auto-detects whichever
postgres service is enabled per host and reloads it on change.

The play also installs `/usr/local/bin/open_psql.sh` and a oneshot
systemd unit pulled in by `postgresql-ts.service` and
`postgresql-tms.service`, so the rules survive reboots — iptables state
is reapplied on every postgres start (`pg_hba.conf` already persists).

```bash
ansible-playbook -i ansible/inventory/proxmox.yml \
  ansible/apply_tanium_postgres_trust.yml
```

`scripts/tanium/open_psql.sh` is the per-host script the systemd unit
runs; you can also invoke it directly on an appliance for one-off
recovery.

## Secrets & Credentials

- **Ansible Vault** is the single source of truth for ansible secrets.
  Inline `!vault |` blocks in `ansible/inventory/group_vars/all.yml` and a
  fully-encrypted `ansible/group_vars/all/vault.yml`. Decrypted at runtime
  using `.vault_pass` (gitignored).
- **`ansible.log` is disabled** in `ansible/ansible.cfg` — `ansible-inventory --host`
  and any debug task that prints vars dumps decrypted hostvars to log_path,
  so we don't write logs to disk. See the comment in ansible.cfg.
- **Home Assistant** secrets in `/config/secrets.yaml` on the HA host
  (gitignored locally; see `homeassistant/secrets.yaml.example`).

## Linting & CI

GitHub Actions runs four lint jobs on push and PR (see `.github/workflows/lint.yml`):

- `ansible-lint` (configured by `ansible/ansible.cfg` + `.ansible-lint`)
- `shellcheck` (configured by `.shellcheckrc`)
- `yamllint` (configured by `.yamllint`)
- `ruff` for Python (configured by `pyproject.toml`)

To get the same enforcement on your laptop, run the installer once:

```bash
./scripts/install_dev_tools.sh
```

It installs `pre-commit`, `ansible-core`, `ansible-lint`, the ansible
collections, and wires up the git hooks. After that, hooks run on every
`git commit`; to lint the whole tree manually:

```bash
pre-commit run --all-files
```

## License

Personal homelab configuration. Use at your own discretion and adapt as needed.
