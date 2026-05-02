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

| Service           | Hostname           | Private IP     | Public/LAN         | Description                                       |
| :---------------- | :----------------- | :------------- | :----------------- | :------------------------------------------------ |
| Gateway           | `proxmox` (VNet)   | `172.16.0.1`   | -                  | SDN gateway for the private network               |
| DNS               | `dns-01`           | `172.16.0.10`  | -                  | Internal Bind9 authority (`chi.lab.amd-e.com`)    |
| NTP               | `ntp-01`           | `172.16.0.11`  | -                  | Chrony, syncs against `time.nist.gov`             |
| Squid Proxy       | `proxy-01`         | `172.16.0.12`  | -                  | Outbound caching proxy                            |
| Identity          | `authentik`        | `172.16.0.20`  | `100.x.y.z` (TS)   | SSO provider; access via load balancer            |
| Load Balancer     | `lb-01`            | `172.16.0.30`  | LAN/DHCP           | Nginx Layer 7 proxy for the cluster and services  |
| Mail Forwarder    | `mail-01`          | `172.16.0.40`  | -                  | Postfix → iCloud SMTP relay for alert email       |
| VictoriaMetrics   | `vm-01`            | `172.16.0.42`  | -                  | TSDB + blackbox_exporter + Loki                   |
| Grafana           | `graf-01`          | `172.16.0.41`  | -                  | Dashboards + unified alerting + image renderer    |
| Tailscale GW      | `tailscale-gw`     | `172.16.0.101` | LAN + `100.x.y.z`  | Subnet router; ingress / NAT gateway              |

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
  - `ct:104` — Mail forwarder
  - `ct:106` — VictoriaMetrics (vm-01)
  - `ct:107` — Grafana (graf-01)

If a node fails, Proxmox HA automatically restarts protected containers on a healthy node. Check status with `ha-manager status` on any node.

### Observability

Single-host metrics + logs stack on `vm-01` and `graf-01`:

- **Agents** — Grafana Alloy is the unified telemetry agent on **every
  managed host except the Tanium appliances** (the `tanium_cluster`
  group). It runs `prometheus.exporter.unix` for node-exporter-shape
  metrics and `loki.source.journal` for the systemd journal, then pushes
  both via `prometheus.remote_write` (to VM at `:8428/api/v1/write`)
  and `loki.write` (to Loki at `:3100/loki/api/v1/push`). The
  `roles/alloy/` role supports apt (Debian/Ubuntu), dnf (RHEL 9+), dnf
  via shell (EL8 — python3.9 lacks dnf bindings), and zypper (SUSE).
  Tanium appliances run a narrow `node_exporter` install via
  `roles/tanium_node_exporter/` instead — different hardening profile.
- **Metrics** — VictoriaMetrics receives node_exporter-shape metrics
  two ways: pushed by Alloy (every Alloy host) and pulled at `:9100`
  from `tanium_cluster`. Blackbox_exporter probes also land in VM:
  - TCP probes to Tanium postgres (5432 on TS, 5433 on TMS) → `tanium_postgres_unreachable`
  - TCP probe to Tanium server console (:443) → `tanium_console_unreachable`
  - HTTPS probes to grafana / auth / proxmox public URLs → `https_endpoint_unreachable`,
    `cert_expiring_soon` (cert <14 days)
- **Logs** — Loki on `vm-01:3100`. All Alloy hosts ship via
  `loki.source.journal`; Tanium appliances don't ship logs. Labels
  (`host`, `job`, `unit`, `severity`, `nodename`) are stable across
  hosts. 14-day retention, filesystem storage. Loki is also a Grafana
  datasource — query logs in the same UI as metrics.
- **Alerts** — Grafana unified alerting. Rules live in
  `roles/grafana/templates/alerting_rules.yml.j2`. Categories:
  - **Reachability**: `host_down`, `https_endpoint_unreachable`,
    `tanium_postgres_unreachable`, `tanium_console_unreachable`.
  - **Capacity / health**: `disk_full`, `loki_disk_pressure`,
    `loki_write_errors`.
  - **Cert lifecycle**: `cert_renewer_wedged` (warning at <30 days
    runway — acme.sh's renewal cadence), `cert_expiring_soon`
    (critical at <14 days; backstop).
  - **Cluster**: `log_pve_replication_failed`, `log_pve_quorum_lost`.
  - **Log-backed events**: `log_oom_kill`, `log_service_restart_loop`,
    `log_ssh_brute_force`, `log_kernel_io_error`, `log_postgres_fatal`,
    `log_postfix_relay_failure`.
  - **Meta**: `dead_mans_switch` — always-firing rule routed exclusively
    to a healthchecks.io webhook so an outage of Grafana / mail-01 /
    the LAN doesn't leave you blind.
- **Delivery** — Three contact points:
  1. Home Assistant webhook → iOS critical push (`severity=critical`
     overrides Do Not Disturb; warnings come in as normal pushes).
  2. iCloud SMTP fallback via `mail-01` for resilience if HA is down.
  3. healthchecks.io webhook for the dead-man's-switch only — pages
     out-of-band (gmail, not via mail-01) if the rest of the pipeline
     is broken.

### Dependency tracking

Self-hosted Renovate runs weekly via GitHub Actions
(`.github/workflows/renovate.yml`). Tracks version pins in role
`defaults/main.yml` files plus a few Docker image tags:

- Binaries from GitHub releases: `alloy`, `blackbox_exporter`,
  `tanium_node_exporter` (node_exporter), `victoriametrics`, `loki`,
  `golang/go`, `grafana/grafana-image-renderer`.
- Docker images: `ghcr.io/goauthentik/server`, `docker.io/library/postgres`,
  `docker.io/library/redis` (all consumed by `roles/authentik_service/`).

A second weekly Action (`.github/workflows/renovate-backlog.yml`) fails
the run if more than 5 dependency-labeled PRs accumulate, so the
dashboard issue #1 doesn't get ignored silently.

### Security & access

- **Login auth** — every operator-facing UI flows through Authentik:
  Proxmox WebUI (OIDC), Grafana (OAuth2), Tanium console (SAML),
  VictoriaMetrics + whoami (nginx forward-auth via the Authentik
  embedded outpost). Grafana also has a local `admin` password as
  documented emergency-access fallback.
- **DNS** — `dns-01` (bind9) forwards upstream to AdGuard Home on the
  homeassistant host, which handles the encrypted DoT/DoH egress to
  Cloudflare and applies adblock lists. Lab queries fail closed if
  AdGuard is down (`forward only;`).
- **Per-CT firewalls** — authentik, mail-01, proxy-01, and all 6 Tanium
  CTs have allow-listed inbound rules. Other service CTs (tailscale-gw,
  dns-01, lb-01, ntp-01, vm-01, graf-01) live in the trusted-SDN zone.
  See `docs/network-security.md` for the full threat model.
- **pve hosts** — management plane (SSH, web UI, corosync) on `vmbr0`
  LAN only. The `private` SDN endpoint added by `roles/pve_private_ip/`
  is outbound-only via a `PRIVATE-MONITORING-IN` iptables drop chain.
- **Secrets** — Ansible Vault for everything; `gitleaks` runs in CI
  for accidental commits beyond pre-commit's PEM-only check.

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
- `install_dev_tools.sh` — install the lint/test toolchain (pre-commit + ansible-lint + collections from `ansible/requirements.yml`). macOS via Homebrew.
- `yubikey_vpn_connect.sh` — YubiKey-based VPN connection.
- `patch_binary.sh` — binary patching helper.
- `grafana_auth.py` + `grafana_curl.sh` — JWT-token extractor for browser-based Grafana SSO + curl wrapper that injects the token (see `README_GRAFANA_AUTH.md`).
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
