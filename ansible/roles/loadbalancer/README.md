# Load balancer HA (lb-01 + lb-02, keepalived VIP)

`172.16.0.30` is a **floating VIP**, not a host address. Every DNS record and
every hardcoded client (ack-bot contact point, vhost upstreams) keeps using
it; keepalived moves it between the two LBs.

| Node | Host address | Role | VRRP priority |
|---|---|---|---|
| lb-01 (CT 103) | 172.16.0.29 | MASTER | 150 |
| lb-02 (CT 146) | 172.16.0.31 | BACKUP | 100 |

VRRP runs **unicast** (`unicast_src_ip` / `unicast_peer`) because multicast on
the SDN bridge is not dependable. `chk_nginx` tracks `/usr/bin/pgrep -x nginx`
with `weight -20`, so a node whose nginx died yields the VIP.

## Rules that bit us

- **Never issue `pct set -net0` without `hwaddr=`.** PVE generates a new MAC,
  and the SDN fabric does not learn it — the container pings locally but every
  connection to the rest of the SDN fails. Always carry the existing MAC over.
- **nginx must `listen <port>` (all interfaces), not `listen <ip>:<port>`.**
  A backup node does not hold the VIP, so an address-specific bind fails and
  nginx will not start.
- **The ack bot's iptables allow-list must include `.29`, `.30` and `.31`** —
  whichever node is master proxies to the bot, and its source address is its
  own host IP, not the VIP.

## Failover test (what "working" looks like)

```
pct exec 103 -- systemctl stop keepalived      # master yields
sleep 8
pct exec 146 -- ip -4 -br a show eth0          # VIP must appear on .31
curl -sk --resolve grafana.chi.lab.amd-e.com:443:<backup LAN IP> \
     https://grafana.chi.lab.amd-e.com/api/health   # 200
pct exec 103 -- systemctl start keepalived     # master preempts (150 > 100)
```

Test through a **LAN interface IP with `--resolve`**, not through an SDN
address: amd-workstation routes 172.16.0.x over tailscale, so direct curls to
`.30` leave via the tailnet and prove nothing.
