# nat_metrics

Small systemd timer that writes the SDN egress path's NAT/iptables
invariants into `/var/lib/node_exporter/textfile_collector/` so Alloy's
textfile collector ships them to VictoriaMetrics.

## Why

On 2026-10-20 a routine container patch run restarted
`nftables.service`, whose `ExecStop` is `/usr/sbin/nft flush ruleset`.
The containers never used nftables (all real state is iptables, saved by
`netfilter-persistent`), but the service still existed and still ran its
stop command. It wiped `tailscale-gw`'s three nat `POSTROUTING`
`MASQUERADE` rules, and the entire `172.16.0.0/24` SDN lost internet for
about an hour:

- `dns-01` answered authoritative queries but every recursion timed out;
- `hermes-gw-01` and `gallery-01` run with a MagicDNS-only
  `resolv.conf`, so their `tailscaled` died and they fell off the tailnet;
- nothing alerted, because nothing probed egress, recursion, or the
  gateway's rule inventory.

The end-to-end probes (`blackbox_internet_egress`,
`blackbox_dns_recursion`, `blackbox_tailnet_nodes` in
`roles/victoriametrics/templates/prometheus.yml.j2`) catch the symptom.
This role exists to name the cause without an SSH session.

## Metrics

| metric | meaning |
| --- | --- |
| `tailscale_gw_nat_masquerade_rules` | total nat `POSTROUTING` `MASQUERADE` rules; expected **3** |
| `tailscale_gw_nat_sdn_masquerade_rules` | the subset scoped to `172.16.0.0/24` |
| `tailscale_gw_ts_iptables_chains` | `-N ts-*` chains (Tailscale's own); `0` = tailscaled's chains missing, traffic still passes on a permissive policy |
| `tailscale_gw_nftables_service_active` | must stay **0** — the service is masked precisely so its `ExecStop` can never flush the ruleset again |

## Wiring

- Runs on the `tailscale` group (currently only `tailscale-gw`).
- The host needs `textfile_collector_enabled: true` in
  `inventory/proxmox.yml`, which turns on the textfile collector in
  `roles/alloy/templates/config.alloy.j2`.
- Deployed by a play in `deploy_monitoring.yml` that sits **before**
  "Install Telemetry Agents" — the first `.prom` file has to exist before
  Alloy renders its textfile block and restarts.

## Alerting

`nat_masquerade_rules_missing` (critical, 2m) in
`roles/grafana/templates/alerting_rules.yml.j2` fires on
`tailscale_gw_nat_masquerade_rules < 3`.
