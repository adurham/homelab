# roles/monitoring_host

Provisions Debian 12 LXC containers on the Proxmox cluster for the
monitoring stack. Currently used for `vm-01` (VictoriaMetrics + blackbox
+ Loki + Alloy, CT 106) and `graf-01` (Grafana, CT 107).

## What it does

- `pveam update` + cluster-wide check for the CT's vmid in
  `pvesh /cluster/resources`. Skips create steps if the CT already
  exists anywhere in the cluster.
- `pct create` with two NICs (eth0 LAN DHCP, eth1 private static),
  internal DNS (`ip_dns_primary`, `searchdomain chi.lab.amd-e.com`),
  unprivileged, `nesting=1`, sshpubkey from the calling node's
  `/root/.ssh/authorized_keys`.
- For already-existing CTs: idempotent `pct set --nameserver/--searchdomain`
  plus an `ssh + pct exec + tee` push of `/etc/resolv.conf` so the
  internal-DNS fix lands on the running container without rebuild. CT
  owner is discovered from pmxcfs so HA migrations are handled.
- `pct start` only on first create (HA owns running-state after that).

## Required variables (passed by the caller via `include_role`)

- `vmid` — Proxmox VMID for the container.
- `inventory_hostname` — used as the CT's `--hostname`.
- `net_private_ip` — `172.16.0.x/24` for eth1.
- `template` — `pveam` template filename (`debian-12-standard_...`).
- `lxc_root_pass` — vaulted CT root password
  (`{{ vm_01_root_pass }}` / `{{ graf_01_root_pass }}`). Required; no
  unsafe default is provided.

## Where it's invoked

`deploy_monitoring.yml`'s play 1 (`Provision Monitoring Containers`),
once per monitoring CT.
