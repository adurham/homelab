# roles/windows_exporter

Installs `prometheus-community/windows_exporter` on Windows Server VMs
via `ansible.windows.win_package` over WinRM. Closes the gap flagged
2026-08-04: every other guest in the fleet has in-guest metrics (Linux
LXCs/VMs via Alloy) or hypervisor-level metrics (via
`roles/pve_metrics_export` / `roles/pve_exporter`), but the Windows
VMs (`win-sql-01`, `win-ts-01`, `win-tms-01`, `win-tzs-01`) had neither
Alloy nor an equivalent -- Alloy's install role only has package logic
for Debian/RHEL/SUSE.

## Status (2026-08-04)

Built but NOT yet run against a live VM -- all four Windows VMs are
currently powered off. Baked into the golden-template workflow
(`ansible/docs/windows_template_guide.md` step "E") so future clones
get it automatically; also runnable standalone
(`ansible/deploy_windows_exporter.yml`) against an already-existing VM
once it's booted and reachable over WinRM. See docs/ipam.md "Windows
VMs" for the current gap/next-step tracking.

## Auth / connection

Uses WinRM over plain HTTP on 5985 (Basic auth, unencrypted) -- matches
what's actually configured by the existing
`ansible/files/enable_winrm.ps1` (`Enable-PSRemoting -Force` +
`AllowUnencrypted=$true`), which is already baked into the golden
template's `Unattend.xml` `FirstLogonCommands`. NOT HTTPS/5986 -- that
script never sets up a TLS listener or cert, so claiming
`ansible_winrm_scheme: https` would be describing infrastructure that
doesn't exist. If HTTPS WinRM is ever added, update
`deploy_windows_exporter.yml`'s connection vars to match.

## What it does

1. Downloads the MSI from the upstream GitHub release
   (`windows_exporter_version` in `defaults/main.yml`, currently
   0.30.5).
2. Opens the Windows Firewall for the metrics port (9182).
3. Installs via `win_package` with `ENABLED_COLLECTORS=[defaults],process`
   + `LISTEN_ADDR`/`LISTEN_PORT` MSI properties (silent-install pattern
   confirmed from the project's own Chocolatey package script and
   multiple independent install guides).
4. Starts the service, set to auto-start.
5. Cleans up the downloaded MSI.

### Idempotency note

Uses `creates_service: windows_exporter` rather than `product_id`
(ProductCode GUID) for the idempotency check -- the real GUID isn't
knowable without installing the MSI once first. The service name
`windows_exporter` is confirmed from the project's own docs and every
third-party install guide found during research, but NOT independently
verified against the MSI's actual WiX build source. Double-check
`Get-Service windows_exporter` after the first real install on a live
VM; if the name is wrong, `win_package` will just always reinstall
instead of correctly detecting "already present" -- annoying but not
destructive.

## Collectors

`[defaults]` (cpu, cs, logical_disk, net, os, service, system,
textfile, memory) plus `process` for per-process CPU/mem. Deliberately
NOT adding role-specific collectors (e.g. `iis`, `mssql`) yet -- what's
actually installed/running on these VMs is unconfirmed since they're
currently powered off; add once verified rather than guessing from
hostname alone.

## Where it's invoked

- `ansible/deploy_windows_exporter.yml` -- standalone playbook, pass
  `-i "hostname," -e ansible_host=<ip> -e ansible_password=...` for a
  VM not yet in static inventory.
- Golden-template build: `ansible/docs/windows_template_guide.md`
  step "E", run before Sysprep so it's baked into every future clone.

## Scrape config

`roles/victoriametrics/templates/prometheus.yml.j2` (job
`windows_exporter`), targets from `windows_exporter_scrape_targets`
(`roles/victoriametrics/defaults/main.yml`) -- empty by default until
a real VM is up with a stable IP, same pattern as `exo_scrape_targets`.
