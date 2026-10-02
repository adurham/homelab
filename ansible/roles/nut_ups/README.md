# roles/nut_ups

NUT (Network UPS Tools) for the lab-corner CyberPower GX1500U UPS —
driver (`usbhid-ups`) + data server (`upsd`) + monitor-only `upsmon`,
plus a Prometheus textfile dump that rides the existing Alloy textfile
collector into VictoriaMetrics.

## Why this exists

Added 2026-10-01 with the UPS itself. Background: the recurring lab-corner
power events (three pve nodes + the Netgear GS108 switch dying together
on a seconds-long sag — docs/ipam.md "INCIDENT CLASS B" / "EVENT
2026-10-01") could only ever be diagnosed AFTER the fact from crash
artifacts. The agreed remediation/measurement plan was: put the corner on
a UPS so it (a) rides out the sags and (b) LOGS a transfer event for any
mains disturbance with a timestamp. This role is (b) — without it the
UPS still mitigates, but nothing records the transfer, and the
"was it the old strip / was it upstream" verdict keeps depending on
reconstructing crashes.

The event-critical path is `upsmon`'s own syslog (polls the device every
2s; shipped to Loki by Alloy; alerted by the `ups_on_battery_transfer`
Grafana rule). The textfile metrics are the trend/dashboard layer
(input voltage, load, battery state) and give the same events a second,
metric-shaped record.

## What it does

- apt-installs `nut-client` + `nut-server`, sets `MODE=standalone`.
- Renders `/etc/nut/{ups.conf,upsd.conf,upsd.users,upsmon.conf}`.
  - `ups.conf`: `[{{ nut_ups_name }}]` section (`usbhid-ups`,
    `vendorid=0764`, `pollinterval=2`). The section name is also the
    systemd unit instance: Debian's `nut-driver@.service` resolves its
    device via `nut-driver-enumerator.sh --get-device-for-service <name>`.
  - `upsd.conf`: LOOPBACK-ONLY on purpose (v1) — `LISTEN 127.0.0.1 3493`,
    `ALLOW 127.0.0.1`. Zero new open ports, zero cluster-firewall changes.
  - `upsd.users`: `[upsmon]` account, password from vault
    (`vault_nut_upsmon_password`), upsmon role only — no `instcmds`/actions.
  - `upsmon.conf`: **MONITOR-ONLY**. `MONITOR ... 0 upsmon <pw> primary`,
    `MINSUPPLIES 0`, `SHUTDOWNCMD "/bin/true"`, `POLLFREQ 2`. These are
    the documented NUT pattern for "this system takes no power from the
    monitored UPS and never shuts down because of it" (see the NUT wiki's
    "Monitoring-only NUT clients" page and upsmon.conf(5)). Do NOT raise
    `MINSUPPLIES` or wire a real `SHUTDOWNCMD` without a deliberate
    decision — that would arm an automatic cluster shutdown.
- `nut-driver-enumerator.service` syncs unit instances from ups.conf;
  `nut-driver@{{ nut_ups_name }}`, `nut-server`, `nut-monitor`, and
  `nut.target` are started + enabled (nut.target is the boot hook —
  enabling IT is what pulls the whole tree up on boot).
- Installs `/usr/local/bin/nut-ups-textfile.sh` + a systemd service/timer
  (`{{ nut_ups_interval }}`, default 15s) writing
  `{{ nut_ups_textfile_dir }}/nut_ups.prom` atomically. Metrics:
  `nut_ups_scrape_success`, `nut_ups_info{model,mfr,serial,firmware,driver}`,
  `nut_ups_status_bit{status="OL|OB|LB|..."}`,
  `nut_ups_input_voltage`, `nut_ups_output_voltage`,
  `nut_ups_battery_charge`, `nut_ups_battery_runtime`,
  `nut_ups_battery_voltage`, `nut_ups_load`, `nut_ups_input_frequency`,
  `nut_ups_realpower`.
- A verification probe (`upsc`) prints the live state and a wait loop
  gives the driver up to 60s to appear on first deploy.

## Alloy wiring

`roles/alloy/templates/config.alloy.j2` gates its `textfile` collector on
`smartctl_exporter_enabled OR nut_ups_enabled` (both write the SAME
directory, `/var/lib/node_exporter/textfile_collector` — one dir, one
collector). The flag lives on the owning host in `inventory/proxmox.yml`.

## Where it's invoked

- Its own playbook: `ansible/deploy_nut_ups.yml` (role + Alloy re-render
  on pve01 only) — the targeted path for UPS/monitor changes.
- `ansible/deploy_monitoring.yml` — a `hosts: proxmox_nodes` play gated
  on `nut_ups_enabled`, placed BEFORE the Alloy play so the first dump
  exists before Alloy's config renders and restarts.

## Documented extensions (deliberately NOT deployed)

- **Remote monitoring from pve02/pve03**: switch `upsd.conf` to
  `LISTEN 192.168.86.11 3493` + `ALLOW 127.0.0.1 192.168.86.0/24`, add an
  `IN ACCEPT -source +pve_nodes -p tcp -dport 3493` to
  `/etc/pve/firewall/cluster.fw` (via `pve_host_hardening.yml`'s
  template — it full-file-overwrites cluster.fw), and render a
  `MONITOR {{ nut_ups_name }}@192.168.86.11 0 upsmon <pw> secondary` upsmon.conf
  on the other nodes. Do the firewall rule and the LISTEN change in the
  SAME session — one without the other is a silent failure.
- **Ordered shutdown policy**: requires a deliberate decision first
  (MINSUPPLIES/powervalue + a real SHUTDOWNCMD + secondaries on the other
  nodes). Until then, monitor-only is the whole point.

## Verification

On the owning node:
```
upsc {{ nut_ups_name }} ups.status input.voltage battery.charge ups.load
cat /var/lib/node_exporter/textfile_collector/nut_ups.prom
systemctl status nut-driver@{{ nut_ups_name }} nut-server nut-monitor
```
In VictoriaMetrics: `curl "http://172.16.0.42:8428/api/v1/query?query=nut_ups_info"`.
Alert rules: `ups_on_battery_transfer` (Loki, transfer events) and
`ups_monitor_stale` (VM, scrape_success==0) in
`roles/grafana/templates/alerting_rules.yml.j2`.
