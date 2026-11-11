# HA configs captured from the live lab (2026-11-11)

These files mirror what is running now. They are not yet driven by Ansible —
see "Not yet automated" below. Until a role consumes them, treat the live
files as the source of truth and this directory as the record of intent.

## Load balancer VIP (`keepalived-lb.conf`)

lb-01 `172.16.0.29` (MASTER, prio 150) / lb-02 `172.16.0.31` (BACKUP,
prio 100), unicast VRRP, VIP `172.16.0.30`, `chk_nginx` health script.
Every DNS record and every client points at the VIP.

Traps learned the hard way:
- `pct set -net0` without `hwaddr=` regenerates the MAC and the SDN fabric
  will not learn it — the container pings locally but loses every SDN
  connection.
- nginx must `listen <port>` (all interfaces); a backup node does not hold
  the VIP and an address-specific bind makes nginx fail to start.
- LB-originated upstream traffic is sourced from `.29`/`.31`, **never** the
  VIP `.30` — destination firewalls must allow both.

## DNS VIP (`keepalived-dns.conf`)

dns-01 `172.16.0.9` (MASTER) / dns-02 `172.16.0.14` (BACKUP), VRRP id 52,
VIP `172.16.0.10`, `chk_named` health script. `172.16.0.10` is the address
every lab host already uses, so the VIP move is invisible to clients.

dns-02 is a BIND **secondary** (`type secondary; masters { 172.16.0.9; }`)
for `chi.lab.amd-e.com` and `lab.amd-e.com`; the primary carries
`allow-transfer { 172.16.0.14; }` and `also-notify { 172.16.0.14; }`.

## Postgres endpoint (`haproxy-pg.cfg`)

Each Grafana replica and authentik's CT run their **own** HAProxy on
`127.0.0.1:5432` (Grafana) or `0.0.0.0:5432` (authentik's CT, so its docker
containers can reach it), health-checking Patroni's `:8008/primary`. There is
no shared DB load balancer in the path.

## authentik outpost (`authentik-outpost.compose.yml`)

`ghcr.io/goauthentik/proxy` on CT 148 (`172.16.0.50`) with
`--network host`, listening on `:9300`; both LBs' `auth_request` point at it.
authentik 2026.8 does not serve `/outpost.goauthentik.io` from the server
container, so this outpost is required.

## Not yet automated

- BIND secondary + both keepalived pairs are live-only.
- The nginx vhost file (`/etc/nginx/sites-available/proxmox`) is hand-managed
  and not in the repo.
- New CTs (149 dns-02, 148 outpost, 142/143 VM cluster) are not in the
  nightly backup jobs.
