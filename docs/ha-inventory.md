# HA inventory — what is actually redundant (2026-11-13)

Read from the live cluster (`/cluster/resources`, `ha-manager status`, `pvesr status`
per node, per-service probes), not from the older IPAM table, which has drifted.
Re-run before trusting: this is a snapshot.

## 3-node (quorum systems — survive one node loss)

| Service | Members | Backs | State at capture |
|---|---|---|---|
| etcd (DCS) | 140 /.44 pve03 · 144 /.48 pve01 · 106 /.42 pve02 | Patroni | 3 of 3 (member on 106 was dead 02:53–11:00, restarted, `Restart=always` set) |
| Garage S3 | 151 /.71 pve01 · 152 /.72 pve03 · 153 /.74 pve02 | Loki chunks | 3 of 3, layout zone redundancy maximum |
| Loki | 154 /.75 pve01 · 155 /.76 pve03 · 156 /.77 pve02 | log queries | `/ready` 200; historical range queries answer in 0.2 s |

## 2-node (pairs — one replica survives)

| Service | Members | Backs / depends on | State at capture |
|---|---|---|---|
| Postgres / Patroni | pg-02 `.48` pve01 leader · graf-db-01 `.44` pve03 sync (lag 0) | Grafana + authentik | healthy |
| Grafana | 107 /.41 pve03 · 141 /.45 pve01 | → Patroni; → Discord, mail-01 | both 200; alerting gossip on :9094 now actually clustered (see below) |
| authentik servers | 100 /.20 pve01 · 150 /.60 pve02 | → Patroni | live + ready 200 |
| authentik outposts | 148 /.50 pve03 · second on 150 /.60 | ← LB `auth_request` | 302 gate verified through VIP and both LBs |
| Load balancer | 103 /.29 pve03 · 147 /.31 pve01, VIP `.30` | fronts every vhost | VIP on lb-01; HTTP liveness check with Host header — hung-nginx failover proven (SIGSTOP → VIP moved → SIGCONT → returned) |
| BIND (lab zone) | 102 /.9 pve03 · 149 /.14 pve01, VIP `.10` | lab service names | both answer |
| LAN DNS + DHCP (AdGuard/Kea) | 130 /.4 pve01 · 131 /.5 pve02 | LAN clients | hot-standby |
| **VictoriaMetrics cluster** | 142 /.57 pve01 · 143 /.58 pve03 · **145 /.59 pve02 (new)** | ← vmagent .42/.45 | 3 storage nodes, RF=2 → survives one node loss (proven: writes accepted + stored with .59 vmstorage stopped) |
| **Mail** | 104 /.17 pve03 · **158 /.18 pve01 (new)**, VIP `.40` | Grafana/authentik/pve alert mail → iCloud relay | failover proven both directions; queued mail on the failed node is stranded until it returns |
| **NTP** | 105 /.15 pve03 · **157 /.16 pve01 (new)**, VIP `.11` | every lab client | failover proven; VIP holder requires `chronyc tracking` = Leap status Normal |
| media-ingest | 116 /.47 pve02 · 117 /.80 pve01 | → gallery bucket | independent sources, not replicas |

## restart-HA only (single instance, pvesr + HA manager restarts it elsewhere)

tailscale-gw 101 · proxy-01 108 · adblock-proxy-01 118 · frigate-01 170 ·
ps5forge-rig 240 · mitm-generic 241

## No HA at all

gallery-01 115 · print-01 119 · pet-detector-01 171 · bwt-dhcp 114 ·
Tanium appliances 200–205 · tc-* clients 301–314 · templates 9000–9002

## What backs what

- `VIP .30` → Grafana, Loki, Garage S3, vmselect/vminsert, authentik + outpost, gallery.
- Grafana and authentik each run a **local HAProxy on `:5432`** → Patroni pair → etcd trio.
- Loki stores no chunks locally: every chunk is an S3 object in Garage, via `VIP:3900`.
- vmagent on .42 and .45 → vminsert `VIP:8428` → vmstorage `.57`/`.58`/`.59`; Grafana reads `VIP:8481`.
- Grafana alert rules → Discord webhook + mail `VIP .40` SMTP + healthchecks.io dead-man switch.
- Backups: nightly vzdump per node → `vzdump-nvme` (keep-last=1) → weekly encrypted GDrive → workstation copy.

## Address map for the 2026-11-13 additions
| Guest | VMID | IP | Node | Notes |
|---|---|---|---|---|
| vm-clus-03 | 145 | 172.16.0.59 | pve02 | vmstorage + vminsert + vmselect, rootfs on `local-lvm` (nvme-data on pve02 is 97 % full) |
| ntp-02 | 157 | 172.16.0.16 | pve01 | chrony + keepalived VIP .11, VRID 53 |
| mail-02 | 158 | 172.16.0.18 | pve01 | postfix twin of mail-01, keepalived VIP .40, VRID 54 |
| tc-rhel9 | 312 | 172.16.0.90 | pve03 | moved off .72 (was hijacking garage-02) |
| tc-rhel8 | 314 | 172.16.0.91 | pve03 | moved off .74 (was hijacking garage-03) |

## Alerting path — what broke and how it was found (2026-11-13)

Grafana's own alert state is readable with the account in `/etc/grafana/grafana.ini`
(`admin` + `admin_password`; the earlier 401s were a probe sending an empty
username, not a bad password). What that state showed, once readable:

- **The two replicas were never clustered.** `[unified_alerting]` appeared twice
  in grafana.ini — once carrying `ha_listen/ha_advertise/ha_peers`, once with
  `enabled = true` — and the duplicate section wins, so the ha_* keys were
  ignored. Beyond that, graf-01's nftables baseline (`harden_host_firewalls.yml`)
  did not allow TCP 9094, so graf-02 logged
  `Failed to join 172.16.0.41:9094: dial tcp ... i/o timeout`. Both fixed: the
  sections are merged and 9094 is in the allowlist. Proof is the log pair
  `Waiting for gossip to settle` → `gossip settled` and zero
  `refresh result=failure` on both replicas.
- **pve_exporter was dead** with `No usable temporary directory` after the 08:53
  event, which latched `Start request too quickly`; `reset-failed` + start
  brought it back. It then 500'd because the scrape config had drifted to bare
  IP targets while the exporter verifies TLS: PVE's cert is issued for
  `pveNN.chi.lab.amd-e.com`, so `certificate verify failed: IP address mismatch`.
  Targets are FQDNs again (matching `prometheus.yml.j2`), and both vmagent
  instances now scrape one exporter at `172.16.0.42:9221` instead of each
  assuming a loopback copy.
- **`adguard_dns_down` / `dnsmasq_dhcp_down` were paused.** They watch the HA
  Green at `192.168.86.2`, which no longer serves the LAN: DHCP option 6 hands
  out `192.168.86.4/.5` (AdGuard on CT 130/131, Kea hot-standby). Both fired
  critical continuously. A real replacement should be a `dig`-based probe
  against the AdGuard pair, not an API check against a retired add-on.

