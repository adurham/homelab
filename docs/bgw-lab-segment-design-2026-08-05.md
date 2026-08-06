# Lab-side internet segment via BGW port 1 + new 2.5Gb switch — design (2026-08-05)

Status: **DECIDED (architecture), NOT YET IMPLEMENTED.** One cable is
required (BGW port 1 -> new 2.5Gb switch). No config changes have been
made to any host, the BGW, or the Nest. This doc captures the full
diagnostic story, the chosen architecture, the migration checklist, and
the open decisions.

## 1. The problem (measured, 2026-08-05)

The Google Nest Wifi Pro mesh (main unit + 3 pods, all WIRED backhaul,
fw 3.78.518349) is the single bottleneck for internet throughput on
this LAN. It loses roughly **half of download and more than half of
upload** for every device behind it — wired or WiFi, any depth of switch
chain, any test server. The loss is in the Nest's general forwarding
fabric, is NOT the NAT engine (IPv6 = IPv4 throughput), is NOT
fixable by any Google-side setting (no Priority/QoS option present;
CVE-2023-6339 root exploit patched in this firmware; OpenWRT does not
support the Pro — locked bootloader, no dev-mode button, no USB-C; the
EL3 fault-injection research needs lab equipment), and is NOT fixable
by bridge mode (Google's bridge mode only works with a SINGLE unit, so
the mesh cannot be demoted to APs without replacing it — user is
keeping the pods).

The user's requirement: **full speed (~800 Mbps) on the Lab side**,
with the Home side (HA, IoT, phones, TVs) staying on the Nest at its
"unreliable but acceptable" 200-700 Mbps. No new hardware beyond what's
already been purchased. HA stays on the Home side; access to the Lab
from Home goes over Tailscale.

### Evidence table (all real measurements, 2026-08-05)

| Path | Down | Up | Test |
| :--- | :--- | :--- | :--- |
| BGW's own speed test (BGW -> AT&T) | 1187-1255 | 1165-1255 | BGW admin `/cgi-bin/speed.ha` (Aug 3 history) |
| Laptop DIRECT to BGW port 1 (NAT'd 192.168.1.x) | ~750-830 | ~620-800 | Cloudflare 4-flow, repeated |
| Laptop WiFi -> Nest (6GHz) | ~230-350 | ~230-385 | Cloudflare 4-flow |
| Laptop WiFi -> Nest (2.4GHz, post-reboot association) | ~28 | ~55 | Cloudflare 4-flow — band mis-association, fixed by WiFi bounce |
| Laptop WiFi -> Nest (speedtest.net browser) | 713 | 569 | speedtest.net (outlier, not reproducible) |
| Mac Studio wired -> Nest (Ookla) | 405-494 | 243-374 | Ookla CLI |
| HA box wired -> Nest (hourly speedtest.net history) | 6-504 | 2-443 | swings hour to hour — no stable ceiling |
| Mac Studio <-> Mac Studio, LAN-only (switch chain, no Nest) | 941 | 941 | raw TCP socket |

Conclusions from the evidence:

1. **The BGW's NAT to a LAN device does ~830/800.** Proven twice with
   the laptop plugged directly into BGW port 1. The 1GbE BGW LAN port is
   NOT the limit (941 Mbps LAN-to-LAN through the same class of port).
2. **The switch chain is NOT the limit** (941 Mbps LAN-only test;
   laptop at 2-3 switches deep equals laptop at 1 switch deep through
   the Nest).
3. **The Nest is the loss** — every device behind it lands in the
   200-700 band with huge hour-to-hour variance; the same devices
   direct to the BGW land at 750-830 consistently.
4. **BGW320-500 is in optimal passthrough config**: IP Passthrough
   DHCPS-fixed to the Nest's MAC, Packet Filter Off, Firewall Advanced
   all toggles Off (verified via admin UI), port 2 (Nest uplink) at
   1Gbps full duplex, zero errors.
5. **The BGW's own speed test measures BGW->AT&T only** (per its own
   page text) — it cannot test the LAN path, which is why the direct
   laptop test was needed.

## 2. Chosen architecture: physical Lab segment off BGW port 1

```
AT&T fiber
  └─ BGW320-500 (192.168.1.254; LAN DHCP pool 192.168.1.64-253; NAT ~830/800 proven)
       ├─ port 2 ──> Nest Wifi Pro ──> HOME SIDE (192.168.86.0/24)
       │              • HA box, IoT (Shelly/Hue/Shark/ecobee/TVs), phones, laptops
       │              • AdGuard Home DNS/DHCP at 192.168.86.2 (unchanged)
       │              • Nest port-forward 80/443 -> lb-01 (public ingress — SEE 4.4)
       │              • ~200-700 Mbps, unreliable, ACCEPTED by user
       │
       └─ port 1 ──> NEW 2.5Gb SWITCH (user-purchased) ──> LAB SIDE (192.168.1.0/24)
                      • pve01/02/03 (via USB 2.5GbE adapters where installed)
                      • macstudio-m4-1 / macstudio-m4-2 (exo cluster)
                      • tailscale-gw LXC (CT 101) — SDN egress + Tailscale subnet router
                      • private SDN 172.16.0.0/24 (VXLAN overlay, rides the PVE nodes)
                      • ~750-830 Mbps via BGW NAT — the requirement
```

Key properties:

- **Physically separate L2 domains.** The Lab switch connects ONLY to
  BGW port 1 and the Lab boxes. The Home chain connects only to the
  Nest. This eliminates the dual-DHCP hazard of the earlier shared-L2
  design entirely (no rogue DHCP from the BGW can reach Home devices,
  and vice versa). No L2 loop is possible (each switch has exactly one
  upstream).
- **Lab boxes live on 192.168.1.x** (the BGW's default LAN subnet).
  Static addresses below the BGW DHCP pool (.64) or DHCP reservations
  in the BGW's DHCP server page (`/cgi-bin/dhcpserver.ha` — requires
  the device access code; the pool is 192.168.1.64-253, so statics in
  .2-.63 are collision-free).
- **Home side untouched.** Nest config, AdGuard, HA, IoT, WiFi — zero
  changes.
- **No forwarding router, no per-box dual-homing.** The earlier
  dual-homed design (keep 86.x + add 1.x default route) was reviewed by
  Fable and found sound-with-caveats (macOS scoped-default ambiguity,
  tailscale-gw ingress-reply hazard, no real failover), but the user
  prefers the cleaner split: Lab boxes are single-homed on the Lab
  segment. This is simpler and removes those caveats at the cost of
  cross-network reachability, which Tailscale covers (see 4.3).

## 3. What changes where (checklist)

### 3.1 Physical

1. Run cable: **BGW port 1 -> new 2.5Gb switch**.
2. Move Lab boxes to the new switch:
   - pve01/02/03: USB 2.5GbE adapters (Sabrent NT-UA25, RTL8156BG —
     r8152 driver support since Linux 5.13, PVE kernel is past that;
     confirmed in the managed-switch session 2026-08-04) into the 2.5Gb
     switch where installed. Onboard NICs (I219-LM, 1GbE) can also be
     used if the USB adapters aren't installed yet — the BGW link is
     1GbE regardless; the 2.5Gb switch matters for Lab-internal LAN
     traffic (replication, exo, migration), not the WAN link.
   - macstudio-m4-1/2: onboard 1GbE into the new switch (or USB 2.5GbE
     if added later).
   - tailscale-gw (CT on pve01): its eth0 (vmbr0 veth) follows pve01's
     network; on the Lab segment it takes a 192.168.1.x address.
3. Confirm the new switch's model/managed-ness (see 5.1).

### 3.2 Addressing (proposed statics, below BGW DHCP pool)

| Host | Current (Home) | New (Lab) |
| :--- | :--- | :--- |
| pve01 | 192.168.86.11 | 192.168.1.11 |
| pve02 | 192.168.86.12 | 192.168.1.12 |
| pve03 | 192.168.86.13 | 192.168.1.13 |
| macstudio-m4-1 | 192.168.86.201 | 192.168.1.21 |
| macstudio-m4-2 | 192.168.86.202 | 192.168.1.22 |
| tailscale-gw eth0 | 192.168.86.82 (DHCP) | 192.168.1.2 (static) |
| Default gateway (all) | 192.168.86.1 (Nest) | 192.168.1.254 (BGW) |
| DNS (all) | AdGuard 192.168.86.2 | see 4.1 |

(Numbering is a proposal; adjust to taste. Keep them out of the BGW's
DHCP pool .64-253.)

### 3.3 Config surface

- **BGW**: no changes required (passthrough stays pinned to the Nest;
  the BGW NATs the 1.x LAN normally). Optional: disable BGW LAN DHCP
  (`/cgi-bin/dhcpserver.ha`) if the Lab uses statics, so no device can
  get an unplanned address.
- **PVE nodes**: `/etc/network/interfaces` (vmbr0 address + gateway),
  corosync ring0 address, Proxmox UI/API listeners if pinned to 86.x
  (they bind 0.0.0.0 by default — verify), unattended-upgrades egress
  (now via BGW — fine), pveproxy/pve-firewall rules that reference
  `pve_mgmt` IPSET (the IPSET contains 192.168.86.0/24 + private SDN +
  Tailscale + BWT — the NEW Lab subnet 192.168.1.0/24 must be added to
  the cluster firewall's `pve_mgmt` IPSET, or mgmt access from the
  tailnet/Home breaks).
- **Mac Studios**: static IP + router + DNS in System Settings;
  remove the stale 192.168.0.210 alias on en0 (leftover from the Aug 3
  Netgear discovery) while in there. NOTE: exo cluster control-plane
  configs referencing 86.201/.202 must be updated (see 4.5).
- **tailscale-gw**: eth0 static 192.168.1.2; keep SDN eth1 (172.16.0.1)
  and BWT eth2 (10.99.0.3) untouched; dnsmasq forwarder target change
  (see 4.1); add Tailscale subnet route advertisement for
  192.168.1.0/24 (see 4.3).
- **Private SDN CTs (lb-01, vm-01, graf-01, frigate-01, tanium, ...)**:
  NO changes inside the CTs — they only know the SDN (172.16.0.x) and
  their gateway 172.16.0.1 (tailscale-gw). Their egress follows
  tailscale-gw's, which is now the fast BGW path. Their LAN legs
  (lb-01 eth1, frigate-01 eth0 — on vmbr0) move with pve01's network —
  see 4.4/4.6.
- **HA box**: NO changes (stays Home-side).

## 4. Things that break / need solving before cutover

### 4.1 DNS on the Lab side (MUST FIX)

AdGuard Home at 192.168.86.2 is unreachable from the Lab segment.
Lab hosts currently resolve everything through it, including the
internal hostnames (`*.chi.lab.amd-e.com` DNS rewrites).

Fix: dnsmasq on tailscale-gw (already the SDN's resolver at 172.16.0.1)
becomes the Lab's DNS server. It already serves the SDN; extend it to:
- forward non-internal queries to a public resolver (1.1.1.1 / 8.8.8.8)
  instead of AdGuard 192.168.86.2;
- serve the internal names directly (hosts/`addn-hosts` entries:
  gallery.chi.lab.amd-e.com -> 172.16.0.30 (lb-01 SDN IP), grafana.chi
  -> 172.16.0.41, auth.chi -> 172.16.0.30, etc. — mirror the AdGuard
  rewrite set; source of truth is `ansible/roles/dns_server/` and the
  AdGuard UI).

Then set Lab hosts' resolv.conf to 192.168.1.2 (tailscale-gw) or
172.16.0.1 where reachable.

### 4.2 Home->Lab / Lab->Home reachability (Tailscale)

- Home devices (laptop, phone, HA) reach Lab hosts via the tailnet:
  tailscale-gw already advertises 172.16.0.0/24; ADD advertisement of
  the new Lab subnet 192.168.1.0/24 (`tailscale set
  --advertise-routes=172.16.0.0/24,192.168.1.0/24` + approve in admin
  console) so tailnet devices can reach pve01/02/03 and the studios at
  their Lab addresses.
- Lab -> Home: only needed for (a) vm-01 scraping HA (see 4.6) and
  (b) anything still pinned to 86.x — audit and re-point or proxy via
  the tailnet. The user's stated model: "HA stays Home-side; use
  Tailscale to get into the Lab" — so Lab->Home is minimized by design.
- NOTE: this Mac (adams-macbook-pro-m4) currently has Tailscale STOPPED
  (`tailscale status` -> stopped). Any verification that depends on the
  tailnet requires the Mac's Tailscale running.

### 4.3 Public ingress — lb-01 (MUST DECIDE)

Today: Nest port-forwards 80/443 -> lb-01's LAN leg 192.168.86.86;
the public IP is on the Nest (passthrough). If the Lab moves off the
86.x L2, the Nest can no longer reach lb-01, and **auth.chi.lab /
tanium.chi / any public CNAME dies**.

Options (pick one):
1. Keep a thin Home-side presence: a dual-homed CT (e.g. lb-01 keeps a
   86.x leg via a Home-side bridge on pve01 — requires pve01 to retain
   a Home-side NIC/bridge, i.e. pve01 stays dual-NIC: onboard -> Home
   chain for mgmt+ingress, USB -> Lab switch). This preserves ingress
   exactly as-is with the least churn, but makes pve01 dual-homed
   (which the user wanted to avoid for the Lab boxes — note pve01
   ALREADY needs to reach the Home side for corosync/replication unless
   those move fully onto the Lab switch — see 4.7).
2. Cloudflare Tunnel / Tailscale Funnel from lb-01 (outbound-only
   ingress; changes public DNS CNAMEs; no inbound port-forward needed).
3. Accept public ingress downtime until a later decision.

This is the single biggest open decision. RECOMMENDED: option 1, since
pve01 is likely dual-homed anyway (see 4.7), and it keeps DNS rewrites,
Authentik, and certs untouched.

### 4.4 HA <-> Lab monitoring (vm-01 scrapes HA)

VictoriaMetrics (vm-01, SDN) scrapes HA at 192.168.86.2:8123 outbound
via NAT (PULL model). With the Lab off 86.x this breaks unless HA is
reached via the tailnet (HA has a Tailscale add-on at 100.77.245.39 per
memory) or a proxy. Fix: point the scrape at HA's tailnet IP (or add a
dnsmasq/Tailscale route). Also frigate-01 and any other SDN host that
talks to HA or other 86.x services needs an audit.

### 4.5 exo cluster (Mac Studios) references

The exo cluster configs/scripts may reference the studios by their
86.201/.202 addresses (cluster discovery, `start_cluster.sh`, ansible
inventory in `~/repos/exo` + homelab). Audit for hardcoded IPs; the
studios' new addresses (192.168.1.21/.22) need to propagate to:
- homelab ansible inventory (`ansible/inventory/proxmox.yml` /
  group_vars — the studios aren't PVE-managed; check `macstudio`
  entries and `ipam.md`);
- exo repo if it hardcodes 86.201/.202 (the RDMA interconnects are
  Thunderbolt and unaffected; only control-plane IPs matter);
- anything referencing `adams-mac-studio-m4-1.local` (mDNS — actually
  mDNS survives subnet changes on the same switch? NO — mDNS is L2
  multicast; the studios moving to the Lab switch means `.local`
  resolution from the Home side breaks; tailnet/MagicDNS or hosts
  entries needed).

### 4.6 Proxmox cluster (corosync + replication) — MUST NOT SPLIT

All three PVE nodes must remain on the SAME L2 for corosync and ZFS
replication (they use multicast + direct peer traffic). Moving all
three to the Lab switch together keeps them together — fine. But:

- The **VLAN 20 / 172.20.0.0/24 PVE Sync network** design (2026-08-04)
  physically confines corosync+replication to Netgear switch ports
  3/4/5 via tagged VLANs on vmbr0. If the nodes move to the new switch,
  that physical isolation is lost unless the new switch supports VLANs
  (see 5.1 — is it managed?). On an unmanaged 2.5Gb switch the tagged
  frames still work end-to-end between the nodes (same switch), but the
  isolation property (separating sync traffic from everything else on
  the shared uplinks) disappears — which was the whole point of the
  VLAN 20 design. On the new topology, the Lab switch carries ONLY Lab
  traffic, so the contention the VLAN design protected against is
  largely gone anyway — document the trade, don't silently keep stale
  config.
- Corosync ring addresses (currently 172.20.0.11/12/13 on vmbr0.20)
  must be updated if vmbr0's physical path changes, and the cluster
  firewall `pve_mgmt` IPSET must include 192.168.1.0/24 (and the VLAN
  20 net if it survives).

### 4.7 pve01 dual-home question

If ingress (4.3 option 1) or any Home-side service must stay reachable
from the PVE nodes, pve01 needs a second NIC (onboard -> Home chain,
USB -> Lab switch). This is the ONE place dual-homing is justified and
probably unavoidable; the user's "keep the Lab on the Lab side"
preference applies to the Lab boxes' general networking, not to
pve01's ingress/mgmt leg. Decide this together with 4.3.

## 5. Open decisions (need user input)

1. **New switch model / managed-ness** — is the 2.5Gb switch managed
   (VLAN-capable) or unmanaged? Affects 4.6 (VLAN 20 survival) and
   whether the PVE migration VLAN 21 work can move onto it.
2. **Ingress strategy** (4.3): dual-homed pve01 (keep as-is) vs
   Cloudflare tunnel vs accept downtime.
3. **Statics vs BGW DHCP** for the Lab boxes (recommend statics below
   .64; BGW DHCP server can then be disabled).
4. **DNS**: confirm tailscale-gw dnsmasq becomes the Lab resolver and
   the internal-name set to mirror (4.1).
5. **USB 2.5GbE adapters** on the studios too, or onboard 1GbE only
   for now (BGW link is 1GbE either way).

## 6. Rejected alternatives (with reasons)

- **CT-as-forwarding-router between subnets** (e.g. tailscale-gw
  routing 86.x <-> 1.x): rejected by user — CT can migrate between PVE
  hosts, becomes SPOF for the whole homelab, and the earlier design
  review (Fable) found a real ingress-reply hazard: flipping
  tailscale-gw's default route to the BGW breaks lb-01's public
  ingress because reply traffic for Nest-port-forwarded flows would
  exit via the BGW's NAT, which has no conntrack for those flows.
- **Dual-homed Lab boxes (keep 86.x + add 1.x default route)**: fully
  designed and Fable-reviewed (policy routing, BGW DHCP disable,
  macOS scoped-default caveats, rp_filter checks) but the user prefers
  the cleaner physical split. Documented here for reference — the
  design would have kept per-box dual-homing complexity and the
  dual-DHCP hazard on the shared L2.
- **Bridge mode on the Nest**: impossible — Google bridge mode is
  single-unit only; the mesh can't be demoted without replacing it.
- **Nest replacement / new router hardware**: deferred by user (too
  invested in the pods). If this ever changes, the BGW-side segment
  above already proves the ~830/800 path and the topology survives.
- **Modding the Nest** (root/CVE-2023-6339/OpenWRT): no practical path
  — patched firmware, no dev-mode button/USB-C, no OpenWRT support.

## 7. BGW320-500 admin reference (reverse-engineered 2026-08-05)

- Login: GET `https://192.168.1.254/cgi-bin/login.ha` (cookie jar) ->
  extract `nonce` -> POST `/cgi-bin/login.ha` with `nonce`,
  `password=**********`, `hashpassword=hex_md5(access_code + nonce)`,
  `Continue=Continue` -> 302 to `/cgi-bin/home.ha` = logged in.
- Access code: `023/%?*40@` (user-provided). NOTE: code may have
  changed; verify before relying on it.
- Key pages: `speed.ha` (BGW->AT&T test only; server flaky — fails
  often), `firewall.ha` (status), `dosprotect.ha` (firewall-advanced
  toggles), `ippass.ha` (passthrough mode), `dhcpserver.ha` (LAN DHCP),
  `lanstatistics.ha` (port stats), `sysinfo.ha` (model/uptime).
- Current verified state: BGW320-500 fw 6.34.7, IP Passthrough
  DHCPS-fixed, packet filter OFF, firewall advanced all OFF, LAN DHCP
  192.168.1.64-253, port 2 = Nest at 1Gbps full duplex zero errors.
- BGW speed-test history showed 1187-1255 Mbps to AT&T (Aug 3) and 496
  (Aug 2) — the WAN path varies but is not the bottleneck; the BGW NAT
  to LAN devices does ~830/800 (measured).

## 8. Deploy order (when cable is run)

1. Physically: BGW port 1 -> 2.5Gb switch; move Lab boxes; confirm
   link/addresses (static 192.168.1.x per 3.2).
2. tailscale-gw: static eth0 192.168.1.2, dnsmasq forwarder + internal
   names (4.1), advertise 192.168.1.0/24 on Tailscale (4.2).
3. PVE nodes: interfaces + corosync ring + cluster firewall `pve_mgmt`
   IPSET += 192.168.1.0/24 (and VLAN 20 net if kept). Keep all three on
   the same L2 at all times (4.6) — sequence node-by-node, verify
   quorum after each.
4. Studios: static config, remove stale 192.168.0.210 alias, update
   exo/homelab references (4.5), verify `.local`/tailnet reachability.
5. Verify: `curl`-4 speed test on each Lab box (expect ~750-830),
   ping AdGuard/HA/lb-01 from Home side over tailnet, one exo cluster
   inference, one corosync quorum check, replication job timing.
6. Decide + apply ingress (4.3) and vm-01->HA scrape fix (4.4).
7. Update `ipam.md` Networks table + switch chain + this doc's status.
