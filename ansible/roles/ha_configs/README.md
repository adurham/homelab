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

## Outpost HA (second proxy outpost)

authentik allows **one live connection per outpost token** — a second proxy
container reusing the first outpost's token gets `403 Forbidden`. HA requires
a second registered outpost with its own token and service account
(`ak-outpost-<uuid>`), created via the Django model:

```
Outpost.objects.create(name="proxy-2", type=OutpostType.PROXY)
# do NOT pass config={} — the property calls asdict() and a plain dict raises
# TypeError: asdict() should be called on dataclass instances
```

Run the container in **bridge mode, not host mode** — under `--network host`
it collides with the authentik server's :9000 and crash-loops:

```
docker run -d --name ak-proxy -p 9300:9300 -p 9444:9000 --restart always \
  -e AUTHENTIK_HOST=http://172.16.0.20:9000 -e AUTHENTIK_INSECURE=true \
  -e AUTHENTIK_TOKEN=<new outpost token> ghcr.io/goauthentik/proxy:2026.8.4
```

Both LBs carry `upstream outpost_backend` with `.50:9300` and `.60:9300`.

## HA requires replication, not just the HA manager

A guest can be entered into `ha-manager` and still be unstartable elsewhere:
HA will try to start it on a surviving node, but with no replication job
there is no disk image there. Audit both together:

```
ha-manager status | grep -oE 'ct:[0-9]+'          # what HA manages
pvesr status | awk '/Yes/{print $1}'              # what has a live replica
```

Anything in the first list but not the second is a trap. This audit found
CT 106 (vm-01/Loki), 130/131 (DNS pair), 141 (graf-02) and 142 (VM cluster
storage) in that state; jobs were added for both other nodes each:

```
pvesr create-local-job <vmid>-0 <node-b>
pvesr create-local-job <vmid>-1 <node-c>
```

Note `pvesr status` only lists jobs owned by the local node — check from the
node that hosts the guest, or the jobs look missing.

## Loki HA: 3x Loki + 3-node Garage

Loki is a **quorum** system: `replication_factor` must divide into a member
count that still has a majority after one loss. RF=2 over 2 nodes means a
write needs both (quorum 2/2), so losing one node stops all ingestion —
strictly worse than a single node. RF=3 over 3 nodes tolerates one loss.

Guests (pinned to their node, **never** under pvesr/HA-manager — migrating a
ring member resurrects a stale replica under the same identity):

| role    | CT  | addr        | node  |
|---------|-----|-------------|-------|
| garage  | 151 | 172.16.0.71 | pve01 |
| garage  | 152 | 172.16.0.72 | pve03 |
| garage  | 153 | 172.16.0.74 | pve02 |
| loki    | 154 | 172.16.0.75 | pve01 |
| loki    | 155 | 172.16.0.76 | pve03 |
| loki    | 156 | 172.16.0.77 | pve02 |

Endpoints are single URLs through the VIP, never a node IP:

- S3:   `http://172.16.0.30:3900` (nginx http proxy, **Host $http_host** —
        `$host` strips the port and breaks SigV4)
- Loki: `http://172.16.0.30:3100` (nginx upstream, /tail upgraded)

### Traps that cost real time

- **Bind addresses must be IPv4.** `[::]` / `*:3100` in these containers
  accepts no IPv4 connections (bindv6only), so a peer on the LAN sees
  "connection refused" while `ss` shows the port listening. Pin
  `0.0.0.0` (Garage) or the node IP (Loki `http_listen_address`).
- **Garage S3 region must match.** Loki signs with region `dummy` by
  default; Garage answers `AuthorizationHeaderMalformed … expected
  'garage'`. Set `region: garage` in the Loki S3 block.
- **Kill stale processes** after editing bind addresses — an old garage
  holding the socket makes a correct config look ignored.
- **Never trust `ping` for a free IP.** `172.16.0.73` looked free and was
  in use; it ARPed to a MAC that belonged to another guest. Verify with
  `grep` across `/etc/pve/nodes/*/{lxc,qemu-server}/*.conf` **and** an ARP
  check, and compare the responder MAC to the guest's `hwaddr`.

### Chunk migration (filesystem -> S3) is NOT a file copy

The filesystem client stores chunks as `fake/<fp>/<base64(from:through:checksum)>`;
S3 keys are the decoded form `fake/<fp>/<from>:<through>:<checksum>`. A
verbatim `rsync`/`aws s3 sync` of `chunks/fake` produces objects Loki never
looks up, and every historical query 500s. Decode the name, then upload.

Index files (`chunks/index/...tsdb.gz`) are not encoded and copy verbatim —
but sync them **after** stopping the old instance, since the old compactor
rewrites them while running.

Retention is the silent-loss trap: if the destination's
`limits_config.retention_period` is shorter than the migrated history, the
new compactor deletes the chunks hours after they land.

## vmselect must run with -replicationFactor=2

vminsert writes with `-replicationFactor=2`, but vmselect defaults to
**1** unless told otherwise. With RF=1 a vmselect that cannot reach one
vmstorage returns a *partial* result with no error — Grafana shows a
silently reduced graph rather than a failure.

Both vmselect units carry:

```
-replicationFactor=2 -dedup.minScrapeInterval=1m
```

The dedup interval must equal the scrape interval. Dedup shorter than the
scrape interval puts the two agents' samples in different buckets, so
nothing is collapsed and storage doubles.

## Postgres clients follow the leader via local HAProxy, not a hardcoded IP

Each Grafana host runs HAProxy on 127.0.0.1:5432 with:

```
option httpchk GET /primary
server pg-01 172.16.0.44:5432 check port 8008
server pg-02 172.16.0.48:5432 check port 8008 backup
```

`/primary` only answers on the current leader, so a demotion fails the
check and traffic moves. Verified by a live `patronictl switchover`:
both Grafana instances reported `database: ok` and authentik returned 302
with no intervention.

A vip-manager float would add a third arbitration layer on top of Patroni
and HAProxy for no functional gain — do not add one. The prerequisite for
it is also unmet: Patroni binds `postgresql.listen` to the node's own IP,
so a floating VIP would ping but 5432 would refuse.
