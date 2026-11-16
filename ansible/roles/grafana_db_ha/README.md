# Grafana database HA (Patroni + etcd + HAProxy)

The Grafana database is a synchronous streaming pair, fronted by a single
stable endpoint. Grafana never talks to a specific Postgres node.

## Topology

| Piece | Where | Notes |
|---|---|---|
| `pg-01` | CT 140, 172.16.0.44 (pve03) | Patroni-managed PostgreSQL 15 |
| `pg-02` | CT 144, 172.16.0.48 (pve01) | Patroni-managed PostgreSQL 15 |
| etcd | 172.16.0.44 (pg-01), 172.16.0.48 (pg-02), 172.16.0.43 (`pg-dcs-03`, CT 146 on pve02) | 3 voters on 3 different PVE nodes; `roles/etcd_member` |
| HAProxy | lb-01, 172.16.0.30:5432 | routes to the Patroni leader |

Scope `grafana`, database `grafana_prod`. `synchronous_mode: true`, so a
committed write exists on both nodes before Grafana sees it.

## Why the pieces are where they are

- Two DB nodes on different PVE nodes, both HA-managed with a pvesr replica
  on the third node, so a node loss restarts one elsewhere.
- etcd needs three voters for quorum and each must sit on a different PVE node, so a node loss never takes two.
  The third voter used to live inside the metrics CT (vm-01); on 2026-11-16 it moved to its own CT 146 (`pg-dcs-03`),
  and the member in vm-01 was removed from the cluster. Do not HA-migrate CT 146 onto pve01/pve03.
- HAProxy health-checks Patroni's `:8008/primary`, which answers 200 only on
  the leader, so the endpoint follows promotions without client changes.

## Grafana side

`grafana_db_host: "172.16.0.30"` in `group_vars/all/vars.yml`. Both Grafana
replicas use it; the datasource/dashboards are file-provisioned.

**Restart Grafana after a failover.** HAProxy is TCP mode, so an established
connection stays pinned to the node it was opened against. A promoted standby
leaves the old pool talking to a read-only replica; restarting
`grafana-server` on both replicas rebuilds the pool against the new leader.

## Client config (Patroni)

`templates/patroni.yml.j2` renders `/etc/patroni/config.yml` (what the Debian unit reads) via `deploy_patroni.yml`
(`serial: 1`, SIGHUP reload, never a restart). `etcd3.hosts` is derived from the `etcd` inventory group, the shared
superuser/replication password is `vault_patroni_password`.

Both nodes need `/etc/postgresql/15/main/{postgresql.conf,pg_hba.conf}`
present (Debian keeps them outside the data dir), and the data dir needs a
one-line `postgresql.conf` that includes the Debian one so Patroni can take
it over.

## HAProxy config

`files/haproxy.cfg` — replaced wholesale on lb-01; only the `pg` frontend is
homelab-specific.
