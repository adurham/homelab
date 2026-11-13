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
| Grafana | 107 /.41 pve03 · 141 /.45 pve01 | → Patroni; → Discord, mail-01 | both 200 |
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
