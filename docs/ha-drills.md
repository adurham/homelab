# HA drills

Real fault-injection runs against the live lab, each with measured results. Re-run the scripts after any change to the
tier they cover. The health polls in the scripts skip TLS verification on purpose: they only read our own `/-/health/ready/`
endpoint and a failed handshake must count as downtime, not abort the drill.

| Date | Drill | Result |
| :-- | :-- | :-- |
| 2026-11-16 | Load balancers: `systemctl stop keepalived` on lb-01, hold, start again (`scripts/ha_drills/lb_failover_drill.py`) | VIP on lb-02 about 5 s after the stop (command overhead included); back on lb-01 (preempt) ~9 s after the start. 1 of 127 polls of the public auth endpoint failed, during the failback. Found and fixed beforehand: lb-02 had no `curl`, so its health check had never run, and its stock nginx `default` site would have stopped nginx on the next package-triggered restart. |
| 2026-11-16 | Patroni: `systemctl stop patroni` on the leader (pg-02), then start it (`scripts/ha_drills/patroni_drill.py`) | pg-01 promoted in 7 s. pg-02 rejoined as Sync Standby 6 s after the start with no manual repair (the 2026-11-15 incident needed a hand `reinit`). authentik readiness failed for ~7 s (5 of 58 polls); both Grafana replicas stayed `database: ok`. |
| 2026-11-16 | etcd: `systemctl kill -s TERM etcd` on pg-dcs-03 (a clean exit, the exact class that left the old vm-01 member down for 8 h) | systemd restarted it in 11 s; 3/3 members healthy; Patroni untouched. `roles/etcd_member` sets `Restart=always` on all three members. |

Not drilled yet: a whole PVE node loss (power-cycle with HA fencing). It takes down the guests on that node until they restart
elsewhere, so run it deliberately, in a window, with `ha-manager status` open.

```bash
python3 scripts/ha_drills/lb_failover_drill.py       # ~1 min, brief VIP move
python3 scripts/ha_drills/patroni_drill.py            # ~1 min, ~7 s of authentik write downtime
```
