# roles/tanium_node_exporter

Hardened node_exporter install for Tanium TanOS appliances. The general
`roles/alloy/` (which everything else uses) is .deb/.rpm package-based
and would conflict with TanOS's static iptables rules.

## Why a separate role

TanOS is Rocky 8.10 underneath but with hardened defaults: SELinux
Enforcing, `iptables -P INPUT DROP`, no firewalld, no package install
of monitoring agents. This role:

- Drops in the `node_exporter` binary directly (no apt/dnf).
- Adds a single targeted INPUT rule allowing vm-01
  (`{{ tanium_node_exporter_scrape_src }}`) to scrape `:9100`.
- Doesn't touch the Tanium iptables config.

## Key variables (`defaults/main.yml`)

- `tanium_node_exporter_version` — Renovate-tracked against
  `prometheus/node_exporter`. Only consumer of node_exporter in the repo.
- `tanium_node_exporter_scrape_src` — `{{ ip_vm }}`, the only host
  allowed inbound on `:9100`.

## Where it's invoked

`deploy_monitoring.yml`'s last play (`Install Node Exporter on Tanium
appliances`).
