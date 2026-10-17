# IPAM — IP and VMID allocation

Single source of truth for IP allocations and Proxmox VMIDs. Keep this in
sync when adding/removing/moving CTs or VMs.

## Networks

| Network         | CIDR              | Bridge  | Purpose                                    |
| :-------------- | :---------------- | :------ | :----------------------------------------- |
| LAN             | `192.168.86.0/24` | `vmbr0` | Home LAN — DHCP from the Nest router       |
| Private (VXLAN) | `172.16.0.0/24`   | `private` | SDN private subnet for service traffic   |
| BWT Lab (VXLAN) | `10.99.0.0/24`    | `bwt`     | Isolated subnet for Tanium bandwidth-throttle repro (NEC 00271560 et al) |
| PVE Sync (VLAN 20) | `172.20.0.0/24` | `vmbr0.20` | Isolated L2 segment for corosync + ZFS replication, physically confined to switch ports 3/4/5 — see below |
| PVE Migrate (VLAN 21) | `172.21.0.0/24` | `vmbr0.21` | Isolated L2 segment for live-migration traffic + its node-to-node SSH transport, same physical ports 3/4/5 — see below |

### LAN static-IP allocations (outside the Nest router's DHCP pool)

Google Nest/Wifi's default DHCP pool is **192.168.86.20-250** (confirmed
via vendor docs + a live nmap sweep 2026-09-10 finding active DHCP
leases scattered up to .235, consistent with that default never having
been customized). That leaves **.2-.19** and **.251-.254** safe for
static allocations. No local API/CLI exists to change or query this
scope directly (Nest's local HTTP API needs cloud/app auth; there's no
SSH/SNMP access) — the Google Home app is the only way to verify/change
the actual pool boundary if it's ever suspected to have changed.

Current static allocations in the safe-outside-DHCP range:

| IP | Host | Notes |
| :--- | :--- | :--- |
| `192.168.86.1` | Nest router | gateway |
| `192.168.86.2` | Home Assistant (HAOS) | hosts AdGuard Home add-on for DoT upstream + iOS push |
| `192.168.86.11` | `pve01` | |
| `192.168.86.12` | `pve02` | |
| `192.168.86.13` | `pve03` | |
| `192.168.86.16` | `tailscale-gw` | eth0/vmbr0 -- was DHCP until 2026-09-10 (see Service CTs table below for why) |
| `192.168.86.17` | `frigate-01` | eth0/vmbr0 -- was DHCP until 2026-09-18 (lease drifted to .45 after a cluster-wide reboot, breaking every hardcoded consumer of this IP; same failure class as tailscale-gw above). Moved .85 -> .17 on 2026-10-15: .85 sat INSIDE the Nest router's DHCP pool (.20-.250) with no reservation, so the router could hand it to a new device and collide. .17 is out-of-pool and free (verified: no ping/HTTP/ARP). NOTE: `netgear-switch-01` (.51) and `lb-01` (.86) are still in-pool -- accepted precedent, but the same migration applies if either ever collides. |

`.14`/`.15` also showed as live in the same nmap sweep — identity not
confirmed, left alone. `.18`-`.19` still free if another static
allocation is needed (`.17` taken by frigate-01 as of 2026-10-15).

## Physical switch chain (LAN, non-Proxmox)

Physical topology upstream of pve01/02/03 and the exo cluster Mac Studios:

```
AT&T BGW (IP Passthrough)
  -> Google Nest Wifi Pro (main unit, living room)
       -> TP-Link TL-SG105E (5-port managed, .15) — first hop off the Nest
            -> 8-port basement "trunk" switch (unmanaged) — branch hub
                 -> 5-port under-work-desk switch (unmanaged) — DIRECT cable
                    from the trunk; no pod in the path (since 2026-09-30)
                      -> NETGEAR GS108Ev4 (lab switch, .51) -> PVE
                         nodes + Mac Studios + Nest Wifi Pro basement pod
                         (.40) as a LEAF (user, 2026-09-30: "off the homelab
                         switch"; port not verified) — nothing on the pod's
                         LAN port, no structural traffic through it
                 -> game-room switch (unmanaged) — pod there was reset
                    2026-09-25; a second Nest pod answers at .39 (uptime 3.7 d
                    on 2026-09-30). That it IS the game-room pod, and how it
                    is cabled, are NOT verified (rule: leaf only, nothing in
                    its LAN port)
```

(Re-cabled 2026-09-30 14:50-14:56 CDT per the user: pod removed from the path
— direct trunk -> under-desk cable, pod re-attached as a leaf. This replaces
the 2026-09-25 diagram in which the basement pod sat INLINE between the trunk
and the under-desk switch (the SPOF in the incident below). Chain + ordering
per user description; port-level interconnects below the trunk are not
individually verified.)

### INCIDENT 2026-09-25 evening: basement pod inline = whole-homelab SPOF (CONFIRMED)

User had been trying to force the basement pod onto wired backhaul, couldn't,
and removed it from the mesh via the Google Home app (not a power-cycle).
Within minutes, pve01/02/03, both Mac Studios, and (transiently) the SG105E/
HA/frigate/lb-01 all went unreachable — a live re-run of the same
"unexplained blackout" fingerprint logged twice earlier that day, but this
time root-caused in real time by a Hermes session.

**Confirmed root cause:** the pod, being wired INLINE between the basement
trunk switch and the under-desk switch (see corrected diagram above) rather
than as a leaf, stopped bridging its WAN<->LAN ports entirely once pulled
from the mesh — a known Nest pod failure mode when de-meshed via software
instead of power-cycled. That silently cut the ONLY path to the under-desk
switch, the Netgear homelab switch, all 3 PVE nodes, and both Mac Studios,
while leaving WiFi clients, the Nest's own WAN, and anything not behind the
pod (HA, frigate, lb-01, tailscale-gw, SG105E) only transiently affected by
initial mesh-reconfig churn (self-recovered within ~10 min).

**Proof it was a pure path cut, not a power/host event (verified via SSH the
moment the path came back):** all three PVE nodes' `uptime` traced back to
the EARLIER same-day 14:53 boot (the previously-logged 14:48-14:53 crash
event) — none of them rebooted during this incident. `pvecm status` showed
`Quorate: Yes, Nodes: 3` throughout on recheck, and no new NIC link-down
events appeared in any node's dmesg. This makes sense structurally: corosync
traffic between the 3 PVE nodes flows through the Netgear switch, which sits
entirely DOWNSTREAM of the dead pod alongside the nodes themselves, so
inter-node cluster traffic never had to cross the broken link at all — only
reachability FROM outside the pod (this laptop, upstream generally) was cut.

**Fix applied (temporary):** user re-added the pod to the mesh (~19:34-19:41
CDT); forwarding resumed and the whole path stabilized by ~19:45, confirmed
clean for 6+ continuous minutes plus live SSH/pvecm checks after.

**Root-cause fix — APPLIED 2026-09-30 ~14:50-14:56 CDT** (user re-cabled;
verification in the 2026-09-29/30 storm entry below): a direct cable now runs
from the basement trunk switch to the under-desk switch, bypassing the pod
entirely, so the PVE cluster + both Mac Studios are no longer structurally
dependent on any Nest pod's mesh membership/backhaul state. This also resolves the original "can't force wired backhaul"
complaint for free — once the pod carries no structural traffic, there's
nothing that needs forcing; it can stay on wireless backhaul (or unplugged)
as pure WiFi coverage with zero blast radius if it acts up again. Given this
network has already burned through 2 confirmed-degraded pod units (fact
1650/1649) that showed exactly this kind of "won't behave" symptom before
failing outright, treat this pod's original wired-backhaul refusal as a
possible early warning sign worth revisiting, not just user error.

**Post-incident verification (~20:00-20:05, same evening):** user confirmed
via the Google Home app's Device settings screen that the basement pod
(LAN IP **192.168.86.40**, model G6ZUC) now shows **Connection type: Wired**
— the re-add did restore wired backhaul, not just mesh membership. Cross-
checked locally: `.40` pings tight (avg 9ms, stddev 4ms — matches the
documented wired-pod ping-jitter signature) and returns a plain HTTP 404
rather than a refused connection (unlike real pod hardware, which refuses
every port — worth noting as a device-type distinction if `.40` gets probed
again later). Main/living-room unit confirmed LAN IP 192.168.86.1, WAN IP
108.88.208.88, model G6ZUC also. The two net_a1_6e76/net_a1_c76a mDNS names
at .218/.220 seen earlier in this incident are NOT the basement pod (that
guess was wrong) — likely the game-room pod (reported unplugged/reset
earlier the same day) in some transient state, or stale entries; not
resolved on a later targeted re-check, not chased further since they're
outside what was actually being verified.

**Loop-prevention state across the chain (2026-09-25):**

| Switch | Type | Loop prevention |
| :--- | :--- | :--- |
| NETGEAR GS108Ev4 (.51) | managed | **OFF** (user, 2026-09-25) — its LED "both LEDs blink at constant speed" report had been seen; disabling caused no storm (verified host-side) |
| TP-Link TL-SG105E (.15) | managed | ON — and demonstrably NOT blocking: backbone ports 1/5 forwarding ~2.8k pkt/s each (measured 2026-09-25). No action needed. |
| Basement trunk (8-port) | unmanaged | DIP OFF (user) |
| Game-room / under-work-desk | unmanaged | physical DIPs, if present — per-switch basic detection only; leave as-is. These toggles are NOT a fix for anything; they only decide whether that switch auto-blocks a port when it detects a loop. |

Managed switches keep their loop prevention under DIAGNOSTICS → LOOP
PREVENTION; the TL-SG105E exposes `lpEn` on `/LoopPreventionRpm.htm`.

**Storm re-check + two real LAN blackouts (2026-09-25 ~15:00, re-verified on
user challenge).** No storm in any measured window: multi-vantage byte/packet
rates at every layer normal, zero CRC/error counters, no duplicate-source
traffic. The `SUSPECT-STORM` lines in the studios' `/tmp/netwatch24.log`
(13:42 and ~15:00) coincide with the port-mapping bulk transfers run by the
earlier session — the 15:00 one is byte-verified (pve02 `tap200i0`/VM200 rx
peak 14.42 MB/s = the 400 MB download) — and the watcher's ~1,000 pkt/s
threshold is far too low: **treat any future `SUSPECT-STORM` line as needing
a byte-rate check before it is called a storm.**

Separately, TWO real transient segment blackouts were found that had not
been recorded: **12:28:29–12:28:58** (all three pve NIC links dropped
simultaneously ~30 s; corosync lost quorum, recovered) and
**~14:48:59–14:53** (gateway unreachable from MacBook + studios; at ~14:50
all three pve nodes hard-reset uncleanly — `last` shows "crash", fsck ran at
boot — back up 14:54–14:56). House power stayed up through the window (HA
whole-home power sensors kept reporting). A storm floods; these were
blackouts (loss + LOW counters). Cause NOT yet identified. Watch items: this
is the same simultaneous-3-node reboot class as 2026-09-20 (power-event
precedent); pve03's boot HDD (ata1) threw SATA link resets again at 15:06;
Netgear port 5 (documented = pve01) reads `100M full` while pve01's own NIC
reports 1000 Mb/s — verify mapping/renegotiation. Loss-triggered watchers
armed on both studios (`/tmp/netwatch_power.log`).

### INCIDENT 2026-09-29/30: overnight LAN storm -> Healthchecks DOWN; pod removed from the path

**Symptom.** Healthchecks.io `homelab-grafana-watchdog` went DOWN 00:43:05 CDT
and back UP 00:48:00 (email: "downtime 4 minutes, 55 seconds"). Grafana
(graf-01, CT107 on pve01) never stopped — rules evaluated every minute all
night. Its dead-man's-switch pings to hc-ping.com failed at ~00:38:25 and
~00:43 with `TLS handshake timeout` (other windows: DNS timeouts to
172.16.0.10): off-segment TCP was failing, the lab's own services were not.
The later resets that day (pve02 02:34; all three nodes 13:01 = INCIDENT
CLASS B) post-date the alert and are NOT its cause.

**The night (CDT).** Onset 2026-09-29 20:29:17 after a clean 7.5 h (first
gateway=DOWN in both studios' `labwatch.log`). labwatch state transitions per
hour (macstudio-m4-1): 20h 21, 21h 18, 22h 95, 23h 161; 09-30 00h 215, 01h 153,
02h 99, 03h 50, 04h 86, 05-08h 25/24/59/41, 09-11h 8/2/12, 12h 19 (last flap
12:14:35), then quiet 12:14-14:50 bar the 13:01 reset. Both studios' `netwatch`
logged 100% loss to the gateway with `link=active` — the PHY never dropped, no
NIC link-down on any node. Kernel `vmbr0: received packet on nic0 with own
address as source address` (L2 loop/echo fingerprint), per Loki over 09-29
evening + 09-30: ~2.4k / 2.7k / 2.4k on pve01/02/03 (0-4 on the quiet days 09-26..28; 5-29 on the
09-25 blackout day). Corosync KNET flapping, tailscale-gw relay churn and outbound failures
on lb-01 / hermes-gw-01 / vm-01 in the same windows.

**Who flapped, who didn't.**
- Clean: AT&T BGW320 (uptime counter: no reboot since 09-25; WAN 0 errors, GPON
  O5), Nest main (no reboot since 09-28), every node NIC, graf-01 itself.
- Flapped in lockstep on DIFFERENT paths: the wired lab corner (studios ->
  gateway loss, SG105E .15, KNET); Home Assistant (.2, wired on the trunk,
  upstream of the pod zone — Emporia cloud poll 59 unavailable windows overnight
  vs 1-5 on quiet nights); WiFi-only clients (Sony TV 100 unavailable windows
  18:00-06:00 vs 0/1/4 on clean nights; Shelly/EcoNet/heat-pump entities).
- Reading: a disturbance on the flat LAN that reached at least the trunk/SG105E
  layer AND the WiFi side while sparing the BGW/WAN => Nest main + the L2 fabric
  under it, not the ISP. A single failing port cannot explain flapping on paths
  that share none. TRIGGER NOT IDENTIFIED (nothing logged at 20:29; the GS108's
  own counters/uptime are not readable remotely without the 1Password login).

**Change (user, 2026-09-30 14:50-14:56 CDT; the watchers show the gateway /
SG105E / pod blip while cables moved, settled 14:55:56).** Basement pod taken
out of the path (direct trunk -> under-desk cable; pod now a leaf off the lab
switch, nothing on its LAN port). It rebooted at ~14:54:30 (status-API uptime) and answered pings again at 14:55:38 (labwatch).
Effect: the lab corner no longer depends on any pod's mesh/backhaul state
(closes the 2026-09-25 SPOF) and the inline-bridge loop surface is gone.

**Verification 14:56 -> 17:17 CDT (2h21m), all read live:**
- dup-source-MAC kernel lines: 0 on all three nodes since 14:56, by the nodes'
  journals AND by Loki (independent of them; journal ingest confirmed flowing
  the whole window; Loki checked through 17:35). Last events before the change,
  per Loki: pve02 ~08:55, pve01 ~11:07, pve03 ~12:10. Caveat: pve02/pve03
  journals are Storage=volatile and were wiped by the 13:01 reset, so only Loki
  (and pve01's persistent journal) can see earlier. Corosync KNET events: 0.
  Quorate 3/3.
- Active echo test (10 broadcasts out per node; inbound frames carrying the
  node's OWN source MAC): 0 returned on pve01/02/03.
- Natural canary: an ecobee thermostat (192.168.86.22, MAC 44:61:32:df:66:47)
  ARP-sweeps the whole /24 at 60-100 frames/s (seen in every capture today; a reported
  ecobee quirk; 84-95% of all broadcast frames; ~6 KB/s, trivial bandwidth). In a loop every such frame
  arrives 2+ times: 0 of 2,745 broadcast/multicast frames in 26 s on pve01 had
  an identical twin within 30 ms.
- labwatch (both studios): 0 state transitions since 14:55:56; netwatch: 0 loss
  lines. Loss from pve01: 0% to gateway .1 (0.5-0.8 ms), SG105E .15 (2.2),
  basement pod .40 (0.42 — wired-fast; the WiFi-only ecobee averages 16 ms),
  HA .2 (0.39), GS108 .51 (1.9), studios .47/.48 (0.36).
- HA, 166 WiFi/cloud-side entities: 1 transition to unavailable since 14:56 (a
  Shelly temperature sensor) vs 55 flap-minutes in last night's worst hour.
- Fleet: all CTs running, tms-01 up (:22/:5433); the only down scrape targets
  are the two un-launched exo nodes (expected). The 21 stopped VMs on pve01
  (usda-*, win-*, templates) are onboot=0 by design.

**NOT proven.** The same watchers had a 2.5 h quiet spell (12:14-14:50) before
the change and the dup-frame counter had already stopped by ~12:10, so a clean
afternoon is not evidence by itself; storms ran ~20:30-05:00 (plus a light
11-12h tail). The test is a storm-prone window. Pass = dup-source-MAC lines ~0
per node and labwatch <~5 transitions/hour through 20:30 -> 06:00; fail = the
signature returns, which exonerates the pod and leaves Nest-main bridging and
the SG105E/trunk. Open, no programmatic readout: both pods' `/api/v1/status`
read lan0Link/ethernetLink = false despite wired-fast RTT, so the Google Home
app's Connection type is the only authority on wired-vs-wireless backhaul. GS108
loop prevention is still OFF (table above); second pod .39 placement unverified.

### INCIDENT CLASS B: recurring simultaneous 3-node hard resets (2026-09-28 analysis)

Separate from the pod/SPOF outages above. Five events, all three pve nodes
dead within seconds of each other, unclean (no shutdown sequence, no panic
in pstore, no HA watchdog/fence log line), while house power stayed up on
every circuit:

| Boot time (UTC) | Notes |
| :--- | :--- |
| 2026-09-16 21:03 | journal stops mid-traffic, 68s gap before boot |
| 2026-09-18 17:36 | pve02/03 journals already vacant (rotation) |
| 2026-09-20 20:57 | 20+ min of silence before the boot on pve02/03 |
| 2026-09-22 00:12 | stagger 00:10:38 / 00:11:08 / 00:11:13 |
| 2026-09-25 19:53 | stagger 19:48:16 / 19:50:22 / 19:50:29 |
| 2026-09-30 02:34 | SINGLE-node (pve02 only) — see separate note below |
| 2026-09-30 13:01 | stagger 13:01:21 / :26 / :26 (CDT; boots 18:01:21Z/:26Z) — FIRST EVENT CAPTURED LIVE by all three witnesses |

**EVENT 2026-09-30 13:01 CDT (18:01Z) — captured live by the instrumentation.**
All three nodes' journals stop mid-flight between 13:00:27 (last line) and
13:01:21 (pve01 kernel first line); `last -x` = "crash" on all three; pve01
journald logged `File .../system.journal corrupted or uncleanly shut down,
renaming and replacing` at boot. No pstore entries on any node. No
HA/fence/watchdog log line before death (same signature as prior events).

Witness evidence (all three /root/lab_witness.log + both Studios'
/tmp/labwatch.log) shows the discriminating pattern for this occurrence:

- At 13:00:43 pve03's own last heartbeat: `nic0=up quorate=Yes`. At 13:01:00
  (first sample after) BOTH Studios' labwatch logged `netgear-gs108=DOWN`
  (tplink + nest-pod + gateway stayed UP) while pve01/02/03 were already
  DOWN — i.e. ALL THREE nodes + the Netgear GS108 went dark together, while
  the upstream TP-Link SG105E, Nest pod, gateway and both Studios rode it out.
- netwatch_persistent on both studios shows ZERO loss/latency anomaly in the
  ~3 minutes before 13:01 (last pre-event sample 12:59-13:00: `LOSS=0%`), so
  this was a hard cut, not a degrading link.
- Recovery stagger: pve01 up first (13:01:33), then sg105e/netgear (13:01:35-48),
  then pve03 (13:01:54) and pve02 (13:01:57); labwatch returns all-UP 13:01:25→13:02:07.
- House power: whole-house CT `sensor.edgewater_road_power_minute_average`
  stayed 2880-3766 W straight through 17:50-18:10Z (no dip <100 W). (Same
  caveat as before: a 1-min average cannot see a sub-second sag.)
- SMART: pve02 unsafe-shutdowns 119→120 and pve03 unchanged at 157 across
  this event (pve03 counter is stale/inconsistent — it did not increment even
  though the node hard-reset; treat per-event deltas as unreliable on pve03).
  All three nodes are still running their pre-event kernels/uptimes reset at
  13:01; no fsck errors surfaced at boot (`fsck` slice exists on all three).
- Blast radius that rode it out: all LXCs and VMs came back (both Studios
  never rebooted; HA host uptime unbroken; the Netgear switch answered :80
  immediately after; CT uptimes all 18:02-18:04Z = restarted with their nodes).

**This occurrence is the strongest discriminator yet, and it points AWAY from
the pure "three independent PSUs" framing:** pve03's witness heartbeat was
`quorate=Yes, nic0=up` at 13:00:43 and dead by ~13:01:00, and the Netgear
GS108's mgmt plane vanished in the SAME instant as the nodes (both studios
saw it), while the SG105E (upstream of the GS108) stayed up. That is
consistent with a power/feed event on the shared branch feeding the
Netgear+PVE corner (mechanism (a)), NOT with an HA self-fence (mechanism (b))
— a fence would not take the separate Netgear switch's own mgmt IP down, and
would leave the fence log line + softdog reason; neither exists. Next
occurrence: physically inspect the strip/branch feeding that corner, and
check whether the GS108's own uptime counter reset (its web UI at
192.168.86.51 now answers; a single read-only visit is allowed, do NOT loop
logins).

**EVENT 2026-10-01 13:23:57 CDT (18:23Z) — SECOND event captured live; first with a full node-side reconstruction.**

This is now the strongest evidence set in the series, and it refines the
mechanism to a SHORT DEEP POWER SAG on the lab corner. Captured entirely from
node-side instrumentation (the 1s TCP witnesses) + Loki + VictoriaMetrics:

- **Death order (per the survivors):** pve03's witness logged `pve01=down`
  at 13:24:00, `pve02=down` at 13:24:01 — BOTH dead within ~1-2s of each
  other. pve01's own last witness line was 13:23:41 and its journal ends
  mid-connection-traffic (sshd churn) at 13:23:41 with NO shutdown sequence,
  no kernel message, no panic. pve02's last Loki line: 13:23:56.207. Both
  died `crash` (wtmp), no pstore.
- **pve03 SURVIVED but its NIC carrier dropped for exactly 19s:**
  `e1000e nic0: NIC Link is Down` at 13:23:58 → `Link is Up 1000 Mbps Full
  Duplex` at 13:24:17. It stayed quorate, served through, and its HA lock
  blipped only briefly (watchdog closed 13:24:05, `watchdog active` again
  13:24:40 — no fire, margin never exhausted).
- **Power-return math from boot timers:** pve01 `Startup finished in 17.6s
  (firmware) + 9.792s (loader) + ...`, boot_time 13:24:27 ⇒ power-on ≈
  13:23:59.5; pve02 firmware 18.331s + loader 15.315s, boot_time 13:24:32
  ⇒ power-on ≈ 13:23:58.6. So the interruption was only ~2-13 seconds —
  a SAG, not an outage: power was back before the nodes' ATX supplies
  fully drained, and pve03's rail never dropped below its PS-ON threshold.
- **Blast radius, corrected reading (2026-10-01 20:40):** pve03's link partner
  port went down for the full 19s (its PHY logged carrier loss 13:23:58 →
  link back 13:24:17; the GS108 answered again 1s AFTER link return). The
  upstream SG105E's mgmt plane stayed unreachable ~15s LONGER than the
  survivor's own link recovery (down 13:24:03, up 13:24:32) — independent
  evidence the disturbance reached above the corner. CAVEAT: the netgear and
  router probe "down" windows (13:24:02→:18, 13:24:04→:19) overlap pve03's
  OWN link outage, so they are NOT independent evidence those devices
  rebooted this time — do not cite them as such. Everything recovered; none
  of the CTs/guests were corrupted.
- **House power CT:** 18:24 sample 3164 W (no dip; adjacent minutes
  2832-2905 W) — consistent with past events (1-min average cannot see a
  sub-second sag).
- **All other lab hosts** (the whole CT fleet on all three nodes) died and
  rebooted with their nodes at 18:24:27-32Z — 23 instances' boot_time
  reset in VictoriaMetrics at that second.
- **FREQUENCY IS INCREASING:** this is the 3rd occurrence in 35 hours
  (Sep30 02:34 pve02-solo, Sep30 13:01 all-three, Sep30 21:05 pve02-solo,
  Oct1 13:24 pve01+pve02), vs one every ~2-4 days before. pve02 died in
  ALL FOUR; it is the canary (lowest ride-through on the strip).

**Mechanism conclusion:** the pattern is a short (seconds-long) deep voltage
sag on the branch feeding the lab corner, with per-PSU ride-through
differences deciding who survives. What kills the alternatives: a clean
series break would take everything to power-on instantaneously with zero
recovery stagger AND no survivor; HA self-fence is excluded by timing (deaths
<25s after a healthy quorum heartbeat vs the 60s softdog margin, no fence
lines); and the load-bearing discriminator vs a NETWORK fault is physical —
two hosts hard-died instantly with zero pre-death signature AND the surviving
third host's NIC carrier dropped in the same second. No network fault
hard-kills a host, and none resets a live host's PHY carrier. Consult
(glm-5.3, 2026-10-01) independently read the same evidence and endorsed:
"strip-level power interruption; switch died and rebooted; pve01/pve02 died;
pve03's PSU rode through" and noted the stagger means a DECAYING/CHATTERING
voltage (arcing contact or thermal breaker near threshold), which matches the
increasing frequency and makes this a potential FIRE-RISK progression, not
just a reliability nuisance.

**Actions taken 2026-10-01:**
- `lab_witness.sh` v2 deployed to all three nodes (repo
  `scripts/network/lab_witness.sh`): added a `wan` probe (TCP 1.1.1.1:443)
  so the next event can separate house/WAN-side from lab-local, and the
  probe list now covers the corner switches + router.
- Incident record: this entry. Next-event protocol below.

**REFINEMENT (2026-10-01 evening, user input): the suspect is the OLD POWER
STRIP's contacts, not any grid/brownout condition.** The user confirmed the
strip is old. Key discriminator against a house-brownout reading: a real
brownout affects every circuit and would show in the Emporia data across the
house. It does not — Emporia shows the basement circuits calmly at 2-211W
during the events, whole-house never above ~20kW/30d peak, nothing anywhere
near overload, and the rest of the house rides every event cleanly. This is
NOT an overload or a house-wide sag.

What the data CANNOT see: the strip and its sockets/plugs are DOWNSTREAM of
every CT clamp. A failing contact (arcing, corrosion, spring gone weak) only
affects devices physically plugged into THAT strip, and draws no measurable
power — invisible to any CT. So "Emporia shows no problem" is fully
consistent with a strip-contact fault; it rules out overload/sag, not the
strip itself.

Also note the survivor nuance: pve03 shares the strip but survived with a 19s
PHY blip rather than dying. Two candidates: (a) per-device PSU hold-up
differences (same strip event, only the two most sensitive PSUs dropped), or
(b) pve02's own PSU/connector is degrading and its fault current is what
stresses the shared strip. pve02 died in ALL 4 recent events — canary or
instigator.

**The isolating experiment (free, no hardware):** move pve02 off the strip
onto a different circuit entirely, then wait.
- pve02 keeps dying alone -> its PSU/cord, replace that.
- the OTHER two start dying instead -> the strip (replace it).
- all quiet -> it was the strip contact, cured by moving.
An old strip with an escalating event frequency is a fire-risk item as well
as a reliability one: inspect for discoloration/warmth before trusting it.

**REMEDIATION (2026-10-01, decided):** user ordered a CyberPower GX1500U
(1500VA/900W pure sine wave, line-interactive, AVR, 12 outlets — 6
battery+surge / 6 surge-only, USB+serial monitoring, NUT-supported via
usbhid-ups — Best Buy open-box $197). The UPS will replace the old strip
ENTIRELY as the feed for the lab corner; the strip leaves the path entirely.
No circuit tester / no separate replacement strip needed.

> **SUPERSEDED by the INSTALLED entry below.** The plan here assumed the two
> Mac Studios would go on battery outlets (6 outlets = 6 devices). They did
> not — the actual device list is pve01-03, GS108, basement pod, and
> amd-workstation. Kept for the load-budget reasoning and the
> mitigate-and-discriminate logic, both of which still apply.
- LOAD BUDGET (resolved 2026-10-01, user-measured): total ≈705W worst case
  — 3 OptiPlex nodes (~300W combined worst case) + 2 Mac Studios (~200W
  each max, user has never seen them exceed this) + GS108 (~5W) — against
  the 900W rating, ~20% headroom. Comfortable fit; no need to relegate the
  studios to surge-only outlets.
- This simultaneously mitigates AND discriminates: no more events -> strip
  contacts were the fault; UPS logs a transfer/AVR event per incident ->
  upstream sag (timestamps close the case); pve02 dies alone on clean UPS
  power -> that machine's own PSU/cord.
- TO DO on arrival: wire NUT (usbhid-ups) on a host, export input.voltage +
  ups.status + load to VictoriaMetrics, add a Grafana alert for transfer
  events (OB/OL transitions) so the next occurrence timestamps itself.
  Update this entry with the outcome.
  **DONE 2026-10-01/02** — NUT live on pve01, metrics + alerts in place. See
  the INSTALLED and MONITORING entries below, plus the 2026-10-02 automation
  entries (guest autoshutdown, input-side alert, scheduled self-test).

**INSTALLED 2026-10-01 evening (~18:59-19:03 CDT; user).** CyberPower
**GX1500U** — the open-box unit from this day's research (Best Buy, $197;
model confirmed by the user 19:25). Specs: 1500VA/900W line-interactive
(single-boost AVR, 4 ms transfer, sine-wave on battery), 12 NEMA 5-15R =
6 battery+surge / 6 surge-only, HID-compliant USB data port (USB A-B cable
in box), RJ45 1-in/1-out surge passthrough, runtime 2 min full / 11 min
half load at rating. It now feeds the lab corner. User's device list: "the
homelab switch, the basement wifi pod, the 3 PVE nodes, and the
workstation" — i.e. GS108 (.51), basement pod (.40), pve01/02/03, and
amd-workstation. The old strip is OUT of the path entirely (user-confirmed)
— the decided remediation is fully applied on the powered side. NOT on the
UPS: both Mac Studios and the SG105E/trunk/under-desk switches. (This
device list supersedes the earlier load-budget plan, which had assumed the
two Studios on battery outlets.)

Rewire window, as captured by both studios' labwatch/netwatch:
- ~18:59:0x corner power cut — nodes + GS108 + pod all show DOWN by 18:59:20.
  All three nodes' `last -x` for the 13:24 session end in `crash` and pve01's
  journal stops 18:59:02 mid-connection (pve02/03 journals are volatile and
  lost that window) — i.e. power was pulled on running nodes as the strip
  came out. User-initiated; NOT a class-B event).
- GS108 back 19:00:38, pod 19:00:48, nodes booted 19:01:07 (pve01) /
  19:01:24 (pve03) / 19:01:30 (pve02); brief gateway blips 19:01:41 and
  19:03:00-08 during final cable moves; quiet since 19:03:13.
- Neither Mac Studio rebooted (up since Sep 22). Cluster quorate 3/3; all
  CTs/VMs back with their nodes (verified via `/cluster/resources` 19:19);
  Loki/VM/HA/frigate/GS108/SG105E all answering. SMART unsafe-shutdown
  counters ticked again from the pull: nvme0 = 121 (pve01) / 123 (pve02) /
  159 (pve03, known-stale) as of 19:16.

**MONITORING — DEPLOYED 2026-10-01 ~20:00 CDT (roles/nut_ups on pve01).**
The USB cable went into pve01 at ~19:25 CDT and the full NUT chain is now
live: `nut-driver@gx1500u` (usbhid-ups) + `nut-server` + `nut-monitor`
(monitor-only: MINSUPPLIES 0 / powervalue 0 / SHUTDOWNCMD /bin/true —
nothing ever auto-shuts down), with a 15s textfile dump
(`/var/lib/node_exporter/textfile_collector/nut_ups.prom`) read by
pve01's Alloy textfile collector (whose gate now ORs
`smartctl_exporter_enabled` with the new `nut_ups_enabled`, same dir) and
shipped to VictoriaMetrics as `nut_ups_*` series (scrape_success, info,
status_bit, input_voltage, output_voltage, battery_charge/runtime/voltage,
load, frequency, realpower). Two new Grafana rules provisioned and
evaluating clean: `ups_on_battery_transfer` (Loki, upsmon's syslog
"UPS %s on battery" string — the transfer timestamp) and
`ups_monitor_stale` (VM, scrape_success==0 for 15m). Deploy playbook:
`ansible/deploy_nut_ups.yml`; also wired into deploy_monitoring.yml as a
gated play. upsd stays loopback-only (no new open ports, no firewall
change); remote monitoring from the other nodes + any shutdown policy are
documented extensions in roles/nut_ups/README.md, NOT deployed.

Live readings at deployment (for the record): input 122V, status
`OL CHRG LB`, load 18-19%, battery CHARGE 16% — the open-box unit arrived
nearly flat and is charging (GX1500U manual: ~8h to full). **Until the
battery is charged, a transfer would NOT be ridden out** — the mitigation
is only complete once `ups.status` shows OL (CHRG cleared, LB gone) and
battery.charge is high. Watch `nut_ups_battery_charge` to confirm it
climbs; the UPS is still the measuring instrument meanwhile (upsmon logs
the transfer regardless).

> **RESOLVED (verified live 2026-10-02):** the battery has finished
> charging — `battery.charge: 100`, `ups.status: OL` (CHRG/LB cleared),
> `battery.runtime: 3200` (metric series ~2275s), self-test `Done and
> passed`. The "until charged" caveat above no longer applies: a transfer
> would now actually be ridden out. The 16%/31% figures in this and the
> autoshutdown entry are the deploy-day state, not current.

Two deploy-day pitfalls fixed in the role itself (both would recur on a
fresh host): (1) `maxretry` is an `[upsdrvctl]` global, NOT a per-driver
variable — usbhid-ups fatal-errors on it; (2) the UPS was plugged in
before nut-server landed, so the packaged 62-nut-usbups.rules never
applied to the existing usb node (owner stayed root:root → libusb "Access
denied" → endless driver restart loop); the role now runs
`udevadm trigger --subsystem-match=usb --action=change` to apply the rule
without a replug.

**AUTOSHUTDOWN — ARMED 2026-10-01 ~21:15 CDT (roles/ups_autoshutdown on
pve01).** Orderly guest stop + auto-recovery is now live: when the corner
is on battery ≥60s AND (charge ≤20% OR runtime ≤300s), the daemon stops
guests gracefully (phase 1 = disposable `tc-*` fleet, phase 2 =
everything else; HA guests via `ha-manager crm-command stop`, plain guests
via the status API), force-stopping only after per-guest and whole-
sequence deadlines. It never shuts down a NODE — nodes ride the battery,
and the AC-loss path they already auto-recover from is the backstop.

**BIOS AC-recovery: ALL THREE NODES ARE `On` (completed 2026-10-01 22:0x).**
pve02/pve03 were already `On`; pve01 was `Last` (would have stayed off after
a graceful power-off on battery). Flipped via
`/usr/local/bin/dell-set-ac-recovery-on.sh` (`scripts/hardware/` in the repo)
— the dell-wmi-sysman write path requires the BIOS admin password, which the
script prompts for silently and clears from the kernel buffer on exit.
Verified: `AcPwrRcvry=On` read back on pve01, no driver errors in dmesg.

**BIOS UNIFORMITY PASS: all three nodes now uniform on 12 attributes
(2026-10-01 ~12:0x).** Applied via `scripts/hardware/dell-bios-uniformity.sh`
(table-driven, dry-run by default, `--apply` prompts + readback-verifies per
attribute). 18 writes: pve01 9, pve02 5, pve03 4. Nothing rebooted (uptime
unbroken, quorum 3/3), no driver errors, credential buffers confirmed clear
(a post-run probe write is refused, values untouched).

What changed and why:
- `DeepSleepCtrl` S4AndS5 → **Disabled** (all 3). Deep sleep cuts NIC power
  in S4/S5 and breaks Wake-on-LAN — Dell KB 000146067 requires it off before
  WoL works at all.
- `WakeOnLan` Disabled → **LanOnly** (all 3). The only remote power-on path
  for a headless node.
- `SmartErrors` Enabled → **Disabled** (pve02/03). Dell's SMART reporting
  HALTS POST on a failing disk ("Strike F1 to continue") — on a headless
  basement box that is an unreachable node, and it would block the
  AC-Recovery boot. Disk health is covered by `smartctl_exporter` →
  VictoriaMetrics → Grafana instead. (pve02/03 shipped it enabled — the two
  nodes with the *aged* boot HDDs, i.e. configured backwards.)
- `Absolute` → **Disabled** (all 3) — corporate asset-tracking agent.
- `BIOSConnect`, `SupportAssistOSRecovery`, `AutoOSRecoveryThreshold`,
  `Microphone`, `InternalSpeaker`, `UsbPowerShare`, `PrimaryVideoSlot`
  (pve02) — uniformity on headless boxes.

Deliberately NOT changed: TPM attributes (pve01 exposes different names than
pve02/03; re-provisioning risks clearing keys), `SecureBoot`,
`Virtualization`, `PasswordLock`, `UefiBootPathSecurity` (already uniform),
and anything reflecting genuine hardware differences.

**WoL status: configured, NOT yet proven.** The OS side was already fine —
`nic0` on all three shows `Supports Wake-on: pumbg` / `Wake-on: g` and
`power/wakeup=enabled`, so no ethtool unit is needed. What's missing is an
actual end-to-end wake test, which requires powering a node off (needs
explicit go-ahead; don't do it on quorate nodes casually). Until then treat
WoL as configured-but-unverified — Dell KB + forum reports document this
OptiPlex generation being flaky about it even when set correctly. Any wake
test must use a TCP probe or the PVE UI, not ping (inter-node ICMP is
firewalled by design on this LAN).

**amd-workstation (Minisforum DRFXI / AMI BIOS): NOT settable from software.**
No `/sys/class/firmware-attributes` interface (the kernel has the
`firmware_attributes_class` module but no provider driver for this board), no
ACPI/WMI vendor hooks, and the settings live in opaque UEFI vars
(`AmdSetupRpl`, `AMD_PBS_SETUP`) with no decoder — blind-writing those is how
boards get bricked. This needs a keyboard+monitor BIOS session:
Advanced → APM Configuration → Restore AC Power Loss → Power On (may appear as
`State After G3` under Chipset, or under `Advanced → ACPI Configuration`).
Note the box also lost power Sep 25 14:50 → Oct 1 19:07 with no shutdown
sequence in its journal, so it has no demonstrated ride-through record.
Recovery restarts exactly what it stopped once mains is stable 5 min (10
if a recovery happened in the last 30 min). Safety: `state.json` on local
disk is the source of truth, `/var/lib/ups-autoshutdown/disabled` is the
kill switch, and 9 selftest scenarios run on every deploy.

Validated by a staged LIVE test before arming: `stop --only 302,105` stopped
tc-ubuntu24 (plain) + ntp-01 (HA) cleanly, `recover` brought both back
(ntp-01 relocated to pve03 via the HA rebalance, chrony healthy).
Thresholds are initial estimates — battery was still charging from the
open-box 16% at arm time (31% and climbing), so this has NOT yet been
through a real outage. (Charge has since completed — 100%/OL as of
2026-10-02, see the RESOLVED note above; the "not yet through a real
outage" caveat stands.) Watch `ups_autoshutdown_lab_stopped` /
`ups_autoshutdown_dryrun_would_stop`; the first genuine low-battery event
is the real acceptance test, and the stop/runtime numbers may want tuning
afterwards (record actuals here).

**CUTOVER NOTE (2026-10-02 00:01Z / Oct 1 19:01 CDT):** an all-three-node hard
reset occurred at 00:01Z — this one was **USER-INITIATED**: the user was
moving the lab corner's power onto the new UPS and cut the old feed. It is
NOT a spontaneous occurrence and must NOT be counted in the event frequency
(do not let it skew the "is it fixed?" clock — the clean-clock starts at the
cutover, ~00:16Z). Two validations came out of it:
1. The `pve_node_rebooted` Grafana alert FIRED as designed (3 instances
   active by 00:04Z) — first live catch by the alerting pipeline.
2. The just-shipped spam_scan mid-run checkpoint saved the scan's progress
   through the reboot (749 OCR results + 120 candidates survived; the old
   code would have lost the whole slice). Gallery self-recovered: all
   services back, serve tmpfs reseeded from Drive in ~70s, manifest serving
   0.12s.
Post-cutover state (corrected 19:12 from the user + live-verified): pve01/02/03
+ GS108 + basement pod + amd-workstation are on UPS outlets; the two Mac
Studios were NOT moved onto it (an earlier claim in this note that they were
is superseded). Clean-clock for the strip-vs-upstream verdict: starts 00:16Z.
UPS USB monitoring: WIRED AND LIVE 2026-10-01 ~20:00 CDT — USB went into
pve01, roles/nut_ups deployed (monitor-only), transfer-event alert armed.
See the "MONITORING — DEPLOYED" block below for the details.

Evidence gathered 2026-09-28 (VictoriaMetrics `node_boot_time_seconds`
steps + Loki journals + HA per-circuit power):

- **Whole-house CT shows no outage** at any of the five instants
  (2-3 kW continuous, 1-min data) — but note a 1-min average cannot see a
  sub-second mains sag, which is exactly the class that resets desktop PSUs
  while smaller supplies ride through. So this is weak evidence, not proof.
- **Circuit-level sensors stay live** through the events (checked all 20
  power sensors; the only zeros are always-zero circuits like pool pump).
- **No UPS/NUT on any pve node** — nothing on these nodes can ride out even
  a brief interruption.
- **softdog is active with a 10s timeout** on all three, but softdog's
  timeout handler calls `emergency_restart()` which writes NO journal and
  NO pstore entry by design — so the absence of a logged reason is the
  EXPECTED signature of either a power event OR a softdog fire, and cannot
  distinguish them. `efi_pstore` IS registered on pve02/pve03.
- Simultaneity is the strongest signal: three independent hosts dying within
  ~10s of each other with no shared software path (no shared storage stall,
  no quorum loss, no lock-timeout) points at their common substrate — the
  physical feed.
- Not yet measured: the NETGEAR GS108Ev4's own uptime counter (would prove
  whether it rode the events out). The switch's dashboard exposes no uptime
  field via the CGI pages we can read; a scripted login burned the session
  slots on 2026-09-28, so this needs either a browser visit to the UI or a
  later attempt after slots expire. Do NOT retry logins in a loop — the
  switch wedges (see the lan-device-identification skill).
- **The three nodes share ONE power strip (user, 2026-09-28).** This is the
  first confirmed common physical substrate on the lab side, and it collapses
  the "three independent hosts" framing above: they are not independent at the
  feed. It is equally consistent with BOTH surviving hypotheses — a strip/branch
  fault kills all three at once (mechanism a), and HA self-fencing reboots all
  three at once after a shared connectivity loss (mechanism b). It does NOT by
  itself prove power. Note the strip holds only the three nodes, not the
  Netgear switch or the Mac Studios, so "did the switch ride it out?" remains a
  valid discriminator.
- **SMART power-loss counters are high on all three (read 2026-09-28):**
  `Unsafe Shutdowns` = 117 (pve01, 174 power cycles), 119 (pve02, 135),
  156 (pve03, 173). These are cumulative since the disks were installed and
  include every earlier crash, so they corroborate that abrupt power removal is
  this cluster's normal failure mode but do not date individual events.
  They are the one counter that survives the event on the powered-off node.
  The SMART textfile exporter (`roles/smartctl_exporter`, added 2026-09-16)
  exposes `smartctl_device_attribute`, but as of 2026-09-28 only the
  ata-*subset* attributes are exported — `unsafe_shutdowns` is not among them,
  so it is not yet trendable in VictoriaMetrics. Extending that exporter to
  include the nvme attributes is the cheap next step for dating each event.

**Timeline note (2026-09-28):** all five events are *reboots*, and three land
within seconds of a quarter-hour (Sep16 21:03, Sep18 17:36, Sep25 19:53 ≈
:53:5x; Sep22 00:12). pve01 additionally shows an in-place journald restart at
02:00:54 on 2026-09-28 with no boot, and pve02 at 22:53:03 the previous
evening — so something also restarts userspace/journald without a reboot.
Worth checking against cron/timer schedules on the branch before attributing
every event to hardware.

**Hardware note:** all three nodes are Dell OptiPlex desktops (pve01 7090,
pve02/pve03 5080). pve01 carries stale Dell `BsodForensicDump` EFI vars from
2025-04-18 (pre-dates this cluster's use) — not related to these events.

**Instrumentation armed 2026-09-28** so the next occurrence is captured
automatically:

- `/tmp/netwatch_persistent.log` on both Mac Studios — loss/counter-reset
  watcher (5s cadence, rotates at 5MB). Launcher `~/bin/start_netwatch.sh`;
  re-run after a reboot (launchd's GUI domain is not reachable over plain
  SSH on these Macs, so it is a nohup daemon, not a LaunchAgent).
- `/tmp/labwatch.log` on both Mac Studios — per-host reachability TRANSITION
  logger (TCP probes, correct for this LAN; see the ICMP note below).
  Logs a line only on a state change, so the next event yields precise
  per-host drop ordering: nodes-only vs switch+everything vs staggered.
- netconsole is NOT usable on these nodes: the only NIC is a bridge slave
  (`nic0` -> `vmbr0`) and netpoll refuses slave devices ("is a slave
  device, aborting"); naming the bridge picks a random veth port that
  netpoll also rejects. Confirmed and reverted 2026-09-28.

**LAN gotcha (verified 2026-09-28):** ICMP is filtered/deprioritized on this
LAN — the pve nodes, the TP-Link SG105E and even the gateway show 100% ping
loss from both a studio and hermes-gw-01 while their TCP ports are open
(pve01-03: icmp DOWN, tcp/8006 OPEN). Any future reachability watcher must
probe TCP, not ping; a ping-based version of labwatch produced a wall of
false DOWN lines before this was caught.

**Next occurrence, first moves:** read `/tmp/labwatch.log` on both studios
for the drop ordering, then `/tmp/netwatch_persistent.log` for packet-level
detail, then `last -x` + `journalctl -b -1` on each node, and grab the
Netgear's uptime from its UI by hand.

> **PARTIALLY AUTOMATED as of 2026-10-02** — much of this is now push-alerted
> rather than post-mortem: `pve_node_rebooted` (VM, node boot-time change),
> `ups_on_battery_transfer` (Loki, the transfer timestamp),
> `ups_input_sag_or_transfer` (VM, input voltage < 115 or AVR/OB bits), and
> `ups_autoshutdown_lab_stopped` (critical). The witness logs are still the
> authority for DROP ORDERING — read them for sequencing, not for detection.
> Also note `/root/lab_witness.log` on each node (1s TCP witnesses, deployed
> 2026-09-29) is now usually faster to read than the studios' copies.
> Caveat that has NOT changed: the 15s metric cadence can miss a sub-second
> sag, so a negative on the input-side rule is weaker evidence than a
> positive.

**THIRD occurrence, live during this same day's later session (~19:07-19:26+
CDT), observed by a Hermes session responding to a "network still running
like shit" report — NOT caused by that session's pod-removal action, since
this fingerprint predates it by hours (same as the two blackouts above).**
Timeline: ~19:07-19:18 pve01/02/03, both Mac Studios (.47=m4-2, .48=m4-1),
HA (.2), frigate (.85), lb-01 (.86), and even the SG105E (.15) all went dark
(ICMP 100% loss, TCP timeouts) simultaneously; tailscale's WireGuard reached
macstudio-m4-2 mid-window only after 1.8-5s (vs normal <50ms) — severe loss,
not a clean media disconnect for that host. ~19:20: SG105E, Netgear (.51),
HA, frigate, lb-01, and tailscale-gw all recovered to clean 0% loss, but
pve01/02/03 and both Studios stayed dark. ~19:24-19:26: the Netgear switch's
OWN management IP (.51) went dark again too — the blast radius widened back
out rather than narrowing to "just the downstream hosts". No SSH access was
obtained to any pve node or Studio during the whole window, so no
dmesg/`last`/pvecm read for this occurrence (unlike the ~14:50 event's clean
"crash"+fsck evidence). The Nest main unit's own uptime counter ticked
monotonically the entire time (two API reads ~9 min apart) — the Nest itself
never rebooted, ruling it out as the origin. **Leading candidates, still
unconfirmed:** (a) a shared power source (strip/UPS) for the
Netgear+PVE+Studios corner browning out/cycling — consistent with the
switch's OWN mgmt plane going dark, which a pure switch-port/NIC fault
wouldn't explain; (b) the already-flagged Netgear port 5 / pve01 100M-vs-
1000Mb negotiation mismatch, if it's actually flapping the whole port group
under some trigger. Next occurrence: physically check that corner's power
strip/UPS indicator and the switch's link LEDs, and grab host telemetry the
moment SSH access returns.

**LEADING THEORY as of ~19:31, user-supplied, NOT yet physically confirmed:**
the basement pod may be wired INLINE (WAN-in from the trunk switch, LAN-out
continuing to the under-work-desk switch branch) rather than as a leaf —
contradicting this doc's "pods hang off the trunk switch as leaves" diagram
above, which may be wrong for this specific pod. If so, a pod pulled from
the mesh via the Google Home app (not power-cycled) very plausibly stops
bridging its WAN<->LAN ports entirely, which would explain the sustained
(25+ min, non-recovering) blackout of everything behind it as a clean
single-point-of-failure — matches the documented "never place a pod inline"
pitfall exactly. Gap in this theory: at ~19:31 the SG105E (.15) itself — the
first hop directly off the Nest, upstream of where the basement pod is
believed to sit — also went dark, which a pod inline only between the trunk
and under-desk switches should NOT cause. Either the pod is physically
positioned closer to the Nest than believed (between the Nest and the
SG105E), or the Nest's own wired LAN port is separately flapping since the
topology change. Verification step (physical, cheap): count the ethernet
cables plugged into the basement pod — 2 (both WAN and LAN populated) all
but confirms inline-bridge; 1 means it's a normal leaf and not the cause.
Fix if confirmed: unplug both cables from the dead pod and run one cable
directly between whatever was upstream and whatever was downstream of it,
removing the pod from the physical path entirely (leave it unplugged/idle
afterward, don't re-add as a leaf without deciding on backhaul first).

| Device | Model | LAN IP | Notes |
| :--- | :--- | :--- | :--- |
| `netgear-switch-01` | GS108Ev4 (GS108E-400NAS) | `192.168.86.51` (verified live 2026-09-25; resolves as `gs108ev4.lan`) | 8-port "Easy Smart" managed switch. No SSH/SNMP/API — CGI web-form config only. MAC `28:94:01:77:1d:80` confirmed on-device. Find it by hostname/MAC — older notes listed `.62` and `.14`, both STALE. Managed via `ansible/roles/netgear_gs108ev4/` + `ansible/manage_netgear_switch.yml`. |

**Password state (2026-09-25):** the factory-default label password is
REJECTED — the user rotated it. The 1Password item `Netgear GS108Ev4`
holds the CURRENT password (verified working for a scripted read-only
login 2026-09-25). Caveat from experience: this switch allows only a few
concurrent HTTP sessions, each held until timeout — keep scripted logins
to ONE per investigation, and check `/login.cgi` for "maximum number of
sessions" BEFORE attempting a login.

**Loop prevention: OFF (user, 2026-09-25; re-verified OFF via the API).**
It had been reporting what the manual documents as a loop detect ("both
LEDs of a port blink at a constant speed"). Disabling it produced no
storm — verified host-side from macstudio-m4-1 (normal packet rates, 0%
loss, ~2 ms to gateway) and at the BGW (0 Tx/Rx errors, only port 2
live). Re-enable from DIAGNOSTICS → LOOP PREVENTION only if loop reports
recur.

**Status (2026-08-04, IP corrected 2026-10-15):** switch reachable at `192.168.86.51` via a DHCP
reservation (added directly in AdGuard, not yet mirrored into the Ansible
role). Port mapping confirmed via live link-toggle tests (bring interface
down/up on each host, watch for the corresponding port's traffic counters
on `/portStatistics.cgi` to freeze — NOT via UP/DOWN status labels, which
are unreliable on macOS since `ifconfig down` only sets an administrative
flag and doesn't reliably drop the physical PHY link; Linux's
`ip link set down` / `networksetup -setnetworkserviceenabled ... off` do
drop the real link and are trustworthy for this test):

| Port | Device | Confirmed via |
| :--- | :--- | :--- |
| 8 | **Uplink toward the under-desk switch** (i.e. every host on this switch's other branches reaches the house through here) | Traffic test 2026-09-25: downloads to BOTH Mac Studios in turn (served from the MacBook on the desk branch) both produced by far the largest counter deltas on port 8, while no single other port carried a studio's whole flow. Matches user's recollection that 8 is the upstream to the under-work-desk switch. Also the port whose LEDs were seen blinking — a loop report landing on the uplink is the expected place for it. |
| 3 | `pve03` (192.168.86.13) | `ip link set nic0 down`, kernel dmesg `NIC Link is Down`, 2x clean repeat |
| 4 | `pve02` (192.168.86.12) | same method, 1x clean |
| 5 | `pve01` (192.168.86.11) | same method, 2x clean (1st attempt had a false negative from too-coarse SSH polling — use ≥1.5s poll interval and a ≥10s down window) |
| — | **Ports 6 and 7 are DARK (no link) as of 2026-09-25.** Port 7 previously held a Mac Studio; no studio is directly attached there now — the studios' traffic reaches this switch via port 8 / the desk branch. Do not assume the older 7/8 = two-studios mapping still holds. | dashboard + counter sampling 2026-09-25 |

**IMPORTANT CORRECTION:** an earlier version of this doc (same day) claimed
both Mac Studios were confirmed NOT on this switch, based on
`networksetup -setnetworkserviceenabled Ethernet off/on` toggle tests
showing zero effect on any port counter. That conclusion was **wrong** —
a physical cable-unplug test immediately afterward showed both Mac Studios
ARE on this switch (ports 7 and 8). Lesson: `networksetup ... off` is
**not reliable enough for this test either** — like `ifconfig down`, it
does not reliably drop the physical PHY link on these Mac Studios (Apple
Silicon / Thunderbolt-adjacent NIC hardware may power-manage the PHY
differently than the e1000e-based Proxmox NICs, where the same class of
test DID correlate correctly via kernel dmesg `NIC Link is Down`). For
Mac hardware, only a genuine physical unplug is trustworthy for this kind
of port-mapping test — do not trust `ifconfig down` or `networksetup off`
as a proxy for "physical link down" on macOS, on any NIC.

QoS mode note: the switch's QoS page defaults to **802.1P/DSCP** mode,
which reads priority from tags already inside packets — useless here since
Proxmox/replication traffic isn't tagged that way. **Port-based** mode is
the correct choice for prioritizing ports 3/4/5 directly regardless of
packet contents; switching QoS Mode to Port-based should expose a Priority
tab. As of 2026-08-04 this hasn't been applied — see "Root cause found and
fixed" below; QoS is now considered a secondary belt-and-suspenders step,
not the primary fix. Login password was changed by the user and stored in
1Password (no longer the factory default) — I no longer have programmatic
access to this switch.

### Root cause found and fixed (2026-08-04): synchronized replication bursts

The original throughput-dip investigation (2026-08-03) suspected shared-
uplink contention between Proxmox sync traffic and other LAN traffic.
Confirmed via VictoriaMetrics `node_network_transmit_bytes_total{device=
"vmbr0"}` query_range across pve01/02/03: multiple daily events where
**all 3 nodes simultaneously spike to a combined 100+ MB/s (800+ Mbps)**
on their LAN-facing interface for 4-5 minutes at a stretch (e.g. observed
20-46 MB/s per node, all 3 nodes, at the same timestamps).

Root cause: `/etc/pve/replication.cfg` had 20 replication jobs on a
`schedule *:N/15` pattern (offsets 0-14) — but 20 jobs into only 15 minute
slots meant 5 collisions where two jobs fire in the same minute, each
already rate-limited to 15 MB/s but stacking when combined. This is a
pmxcfs-managed live cluster file, NOT Ansible-templated — no repo drift
risk, but also nothing to update in `ansible/` for this fix.

**Fix applied:** rewrote the schedule to `*:N/20` with N assigned 0-19
sequentially per job (one job per unique minute in a 20-minute cycle
instead of a 15-minute one) — zero collisions, verified
`sort(schedules) == [0..19]` before applying. Backup saved on pve03 at
`/etc/pve/replication.cfg.bak-<timestamp>`. Applied by writing the new
config directly (no `pvesr` CLI edit-by-edit needed since it's one file);
`pvescheduler.service` re-reads `replication.cfg` from pmxcfs each cycle,
no restart required.

**Verified:** post-fix, max single-node vmbr0 throughput over a 15-minute
window was ~15 MB/s (down from a confirmed 50 MB/s pre-fix peak), with
zero timestamps where 2+ nodes simultaneously exceeded 20 MB/s (versus
multiple confirmed multi-node collision windows pre-fix). Root cause
resolved without touching the switch at all.

- `172.16.0.1` is `tailscale-gw` — both the SDN VNet gateway and the Tailscale subnet router advertising `172.16.0.0/24` over Tailscale. CTs on `private` use it as their default route only when they need outbound to non-LAN destinations.
- `10.99.0.3` is `tailscale-gw` eth2 on the `bwt` bridge — same CT (101) carries the BWT-lab subnet router, advertising `10.99.0.0/24` over Tailscale.
- MTU on `private` and `bwt` is 1450 (1500 minus VXLAN overhead — `net_private_mtu` / `net_bwt_mtu` in `ansible/group_vars/all/vars.yml`).

## PVE Sync network (VLAN 20, 172.20.0.0/24) — isolated corosync + replication

Built 2026-08-04 alongside the replication-schedule root-cause fix, as a
belt-and-suspenders layer: corosync/replication traffic is now on its own
L2 segment, physically confined to switch ports 3/4/5, invisible to every
other device on the LAN (no gateway, not routed, Google Home/Nest Wifi
Pro never sees it exist). Same physical wire as the LAN (each pve node has
only one NIC) so this does NOT add bandwidth capacity — the replication-
schedule fix already solved the bandwidth-contention problem; this adds
isolation on top.

**Switch side:** Advanced 802.1Q VLAN mode, VLAN 20 "pve-sync" created,
ports 3/4/5 set Tagged (T) for VLAN 20 while staying Untagged/PVID=1 for
the default LAN VLAN (confirmed via PVID Table: ports 3/4/5 show `1*, 20`,
all other ports show `1*` only). Every other port is Excluded (E) from
VLAN 20 entirely.

**Proxmox side (`/etc/network/interfaces` on each node):**
```
auto vmbr0
iface vmbr0 inet static
	address 192.168.86.1X/24
	gateway 192.168.86.1
	bridge-ports nic0
	bridge-stp off
	bridge-fd 0
	bridge-vlan-aware yes
	bridge-vids 20          # REQUIRED -- without this, vmbr0.20 exists but nic0
	                        # never egresses tagged VLAN 20 frames; symptom is
	                        # `bridge vlan show dev nic0` listing only vlan 1,
	                        # ping/ssh across the VLAN just times out silently.

auto vmbr0.20
iface vmbr0.20 inet static
	address 172.20.0.1X/24   # .11=pve01, .12=pve02, .13=pve03, no gateway
```

**Firewall (`/etc/pve/firewall/cluster.fw`):** Proxmox's cluster firewall
is enabled with default-deny-style rules gated on trusted IPSETs — adding
the VLAN alone isn't enough, traffic gets silently dropped unless
explicitly allowed. Added:
```
[IPSET pve_sync_vlan]
172.20.0.11
172.20.0.12
172.20.0.13

IN ACCEPT -source +pve_sync_vlan -p udp -dport 5405 -log nolog # corosync
IN ACCEPT -source +pve_sync_vlan -p tcp -dport 22 -log nolog   # ZFS replication (SSH transport)
```
Scoped narrowly (just corosync + SSH, not a broad subnet-wide ACCEPT) per
user preference, since isolation is the whole point of this network.

**Replication traffic redirect (`/etc/pve/datacenter.cfg`):**
```
replication: secure,network=172.20.0.0/24
```
This is the actual Proxmox-native mechanism (`man pvesr`, NETWORK section)
for repointing replication traffic onto a dedicated network — no per-job
config needed, applies cluster-wide immediately.

> **SUPERSEDED (verified live 2026-10-02):** an earlier draft here claimed
> "NOT yet added as a second ring (`link1`) on this network — still
> single-ring on the LAN (`link0`)." That was true only momentarily during
> the 2026-08-04 build; `link1` was added the same day (block immediately
> below). Current state on all three nodes: `corosync.conf` carries
> `ring1_addr` 172.20.0.11/12/13, `config_version: 4`, `link1` preferred
> (`knet_link_priority: 10`) over `link0` (`: 5`).

**Corosync: added as a second ring, DONE and verified (2026-08-04).**
`link1` added on the isolated VLAN with `knet_link_priority` set so it's
preferred over the LAN (`link0`) — corosync actively uses the isolated
link, LAN stays configured as automatic failover only.

`/etc/pve/corosync.conf` changes (config_version bumped 3→4):
```
nodelist {
  node {
    name: pve01
    ...
    ring0_addr: 192.168.86.11
    ring1_addr: 172.20.0.11     # added
  }
  ... (same pattern for pve02/pve03)
}

totem {
  ...
  interface {
    linknumber: 0
    knet_link_priority: 5      # LAN — lower priority, failover only
  }
  interface {
    linknumber: 1
    knet_link_priority: 10     # VLAN 20 — higher priority, preferred
  }
  ...
}
```

**Apply mechanism note (corrected from an earlier wrong assumption):**
the documented Proxmox pattern is NOT "write to `corosync.conf.new` and
pmxcfs auto-swaps it" — that file sitting on disk does nothing on its own.
The actual mechanism (per `man pvecm`) is: copy to `.new`, edit `.new`,
then explicitly `mv corosync.conf.new corosync.conf` yourself. That `mv`
is what pmxcfs picks up and hot-applies to the running corosync cluster-
wide, no restart needed. Backup the working config first regardless
(`cp corosync.conf corosync.conf.bak`).

**Verified priority actually works (not just configured):** raw packet
counts from a short tcpdump window were NOT a reliable signal (passive-
mode keepalives on the non-primary link created noise). The real proof:
`corosync-cmapctl -m stats` per-link byte counters, diffed over a ~60s
window post-change — `link0.tx_data_bytes` delta was exactly 0 (fully
idle) while `link1.tx_data_bytes` grew by ~2.75MB in the same window.
`corosync-cfgtool -s` / `-n` on all 3 nodes confirmed both links enabled
+ connected to every peer. `pvecm status` confirmed `Quorate: Yes, Nodes: 3`
before, during, and after the corosync.conf swap — zero disruption.

## PVE Migrate network (VLAN 21, 172.21.0.0/24) — live migration, 2026-09-28

Second isolated VLAN on the **same physical ports 3/4/5** as the sync network
above, for live-migration traffic + its node-to-node SSH transport. Referenced
by `/etc/pve/datacenter.cfg` (`migration: secure,network=172.21.0.0/24`) and
allowed by the `pve_migrate_vlan` IPSET in `cluster.fw` (TCP 22 only).

**History — a codification gap that silently broke HA for 17 days.** This was
hand-configured on the nodes in Aug 2026 (memory fact 1174: "VLAN 21 … ALREADY
configured and live on all 3 PVE nodes' vmbr0.21"), but unlike VLAN 20 it was
never added to `roles/proxmox_network/templates/interfaces.j2` — `vmbr0.21`
appears in **no** git commit. The datacenter.cfg + firewall half was codified
(`73e52fb`), the interface half was not.

On **2026-09-11 13:39:23** a `deploy_proxmox.yml` run re-rendered
`/etc/network/interfaces` from that template on all three nodes (sub-second
apart = one run; its stated purpose was the vzdump backup-job fix). Nothing
warns on a template that omits a hand-added block, so `vmbr0.21` was deleted
with no error. The Aug-4 backup file is byte-identical to the post-Sep-11
file — that is the proof.

**Symptom:** every HA auto-rebalance migration aborted in ~1s with
`could not get migration ip: no IP address configured on local node for network
'172.21.0.0/24'`. HA's fallback is **stop → failed migrate → start**, i.e. it
restarts the guest on the same node anyway. Migrations succeeded through
Sep 10 (last OK: `qmigrate:200` 2026-09-07 21:33, `vzmigrate:104` 2026-09-10
18:10); from Sep 11 on, all failed — 24 on pve03, 16 on pve02. Guests bounced
with no node failure involved: authentik 20×, vm-01 4×, plus 101/102/103/105/108.
Confirmed live on 2026-09-28 21:41 for ct:106 (`auto rebalance - relocate ct:106
to pve01` → `migration failed (exit code 1)` → `vzshutdown` → `vzstart`).

**Fix (2026-09-28, deployed + verified):** codified the migrate VLAN in the
repo so no future playbook run can drop it again —
`net_pve_migrate_vlan_id: 21` + `net_pve_migrate_vlan_range` in
`group_vars/all/vars.yml`, `pve_migrate_vlan_ip` per-node in
`inventory/proxmox.yml`, and a `vmbr0.21` block (plus `21` on the required
`bridge-vids` line) in `interfaces.j2`. Applied via `update_network.yml`;
`vmbr0.21` up on all 3 nodes, `bridge vlan show dev nic0` lists 20 **and** 21,
and the exact previously-failing `pvecm mtunnel … -get_migration_ip` call now
returns the correct IP on all six node pairs.

**Switch side — VERIFIED 2026-09-28.** VLAN 21 is present and ports 3/4/5 pass
it: an SSH test bound to each node's `vmbr0.21` address reached both peers over
`172.21.0.x` from all six node pairs, which is only possible if the switch is
forwarding tagged VLAN 21 frames between ports 3/4/5. (The switch UI's VLAN page
(`/vlan.cgi`) exposes no config in its HTML — it loads the PVID table over
JS/XHR — so the CLI cannot read the VLAN mode; the traffic test is the stronger
evidence anyway. `vlanMod value="0"` in the page source is the *uncommitted
form default*, not the running mode: with `noVlan` actually active, no tagged
VLAN would pass at all.)

Note that VLAN 21 shares the **same** physical wires as VLAN 20 on ports 3/4/5,
so a migration cannot add LAN-visible load — which is also why the failure above
never disturbed VLAN 1 / the rest of the LAN.

## Proxmox nodes (dual-homed)

pve hosts are on the LAN by default; `roles/pve_private_ip/` adds a static
IP on the `private` SDN bridge so they have a private-subnet source IP for
Alloy push to vm-01:8428. Inbound on `private` is dropped via the
`PRIVATE-MONITORING-IN` iptables user chain — pve management stays
LAN-only despite the L3 endpoint on the SDN.

| Host    | LAN IP          | Private IP    | Notes                           |
| :------ | :-------------- | :------------ | :------------------------------ |
| `pve01` | `192.168.86.11` | `172.16.0.2`  | Proxmox cluster member          |
| `pve02` | `192.168.86.12` | `172.16.0.3`  | Proxmox cluster member          |
| `pve03` | `192.168.86.13` | `172.16.0.4`  | Proxmox cluster member          |

Source: `ansible/inventory/proxmox.yml` + `roles/pve_private_ip/defaults/main.yml`.

## Service CTs (private subnet)

| Hostname        | VMID | Private IP       | LAN IP (if any)    | Role                                        |
| :-------------- | :--- | :--------------- | :----------------- | :------------------------------------------ |
| `authentik`     | 100  | `172.16.0.20`    | -                  | SSO / OIDC provider                         |
| `tailscale-gw`  | 101  | `172.16.0.1`     | `192.168.86.16` (static) | SDN VNet gateway + Tailscale subnet router  |
| `dns-01`        | 102  | `172.16.0.10`    | -                  | Bind9 authority for `chi.lab.amd-e.com`     |
| `lb-01`         | 103  | `172.16.0.30`    | DHCP (`192.168.86.x`) | Nginx L7 reverse proxy                  |
| `mail-01`       | 104  | `172.16.0.40`    | -                  | Postfix → iCloud SMTP relay                 |
| `ntp-01`        | 105  | `172.16.0.11`    | -                  | Chrony, syncs against `time.nist.gov`       |
| `vm-01`         | 106  | `172.16.0.42`    | DHCP (`192.168.86.x`) | VictoriaMetrics + blackbox + Loki + Alloy   |
| `graf-01`       | 107  | `172.16.0.41`    | -                  | Grafana + image renderer                    |
| `proxy-01`      | 108  | `172.16.0.12`    | -                  | Squid caching proxy (listens `:3129` ssl-bump / `:3130`) |
| `hermes-gw-01`  | 113  | `172.16.0.50`    | - (Tailscale: `hermes-gw-01.tail19c543.ts.net`) | Hermes gateway; joins the tailnet directly, reached by tailnet name |
| `gallery-01`    | 115  | `172.16.0.46`    | - (Tailscale: `100.83.114.12`) | Media gallery platform (OS/tailnet hostname kept as `tg-harvester-01`); joins the tailnet directly |
| `media-ingest-01` | 116 | `172.16.0.47`   | -                  | Media collector (outbound-only)             |
| `media-ingest-02` | 117 | `172.16.0.48`   | -                  | Secondary-source gallery collector (outbound-only) |
| `adblock-proxy-01` | 118 | `172.16.0.49`  | DHCP (`192.168.86.x`) | mitmproxy explicit HTTPS proxy for personal-device Discord ad-stripping (Tailscale-only ingress, joins tailnet directly like hermes-gw-01) |
| `frigate-01`    | 170  | `172.16.0.45`    | `192.168.86.17` (static) | Frigate NVR (Docker-in-LXC); eth0 on vmbr0 for RTSP/HA + eth1 on `private` |

`172.16.0.40` was previously assigned to **both** `mail-01` and `vm-01` (ARP race). Resolved 2026-05-01 — moved `vm-01` to `.42`. See commit `12bb4c2`.

## Monitoring & metrics ingestion into VictoriaMetrics (vm-01)

Three independent paths feed vm-01, covering different layers:

- **Alloy (pull-replaced push agent)** — runs on every managed host
  (LXCs, VMs, the pve nodes themselves). Ships generic Debian/RHEL
  node_exporter-shape host metrics + journal logs via
  `prometheus.remote_write` / `loki.write` to vm-01/Loki. See
  `ansible/roles/alloy/`.
- **Direct Prometheus scrape** — `prometheus.yml.j2` on vm-01 itself
  scrapes a handful of targets that don't run Alloy: Home Assistant
  (`/api/prometheus`), the exo inference cluster (both Mac Studios,
  `:52415/metrics`), Tanium appliances (dedicated hardened
  `tanium_node_exporter` role), and blackbox-driven HTTPS/TCP probes.
  See `ansible/roles/victoriametrics/templates/prometheus.yml.j2`.
- **Proxmox native metric export (added 2026-08-04)** — pvestatd (the
  daemon that already feeds the Proxmox GUI's RRD graphs every 10s) is
  registered as an InfluxDB v2 client pointed at vm-01's native
  `/api/v2/write` endpoint. Gets node + per-guest (VM/CT) CPU/mem/disk/net
  that Alloy's generic host metrics don't cover (Alloy on a pve node only
  sees the pve host's own OS, not neighboring guests). Config lives in
  `/etc/pve/status.cfg` (pmxcfs, cluster-wide, write-once) via
  `ansible/roles/pve_metrics_export/` (id `vm-01-influx`), invoked from
  `deploy_monitoring.yml`'s "Register Proxmox's native metric export"
  play. Series land prefixed by VictoriaMetrics' Influx line-protocol
  mapping (`system_cpu`, `ballooninfo_free_mem`, `cpustat_avg1`, etc.),
  labeled `object` (`node`/`qemu`/`lxc`), `vmid`, `host`, `nodename`.
  Verify: `curl http://172.16.0.42:8428/api/v1/series?match[]=system_cpu`.
  Deliberately does NOT cover storage-pool usage, HA resource state,
  replication job status/duration, or backup job status — pvestatd's
  native export doesn't expose those.
- **prometheus-pve-exporter (added 2026-08-04, same day)** — pulled the
  layer the native export above doesn't carry. Python venv service on
  vm-01 (`ansible/roles/pve_exporter/`, port 9221), scraping the Proxmox
  API via a dedicated read-only token (`pve-exporter@pve`, PVEAuditor
  role, vaulted as `vault_pve_exporter_token_id`/`_secret` — NOT the
  full-privilege `root@pam!hermes-automation` token used elsewhere).
  Scrape config in `roles/victoriametrics/templates/prometheus.yml.j2`
  (job `pve_exporter`), one target per pve node by its ACME FQDN (so
  `verify_ssl: true` actually validates). Gets
  `pve_replication_duration_seconds` /
  `pve_replication_last_sync_timestamp_seconds` /
  `pve_replication_failed_syncs` (replication job status/duration),
  `pve_ha_state` (HA resource state), `pve_not_backed_up_info` /
  `pve_not_backed_up_total` (backup job coverage), and
  `pve_disk_usage_bytes{id=~"storage/.*"}` / `pve_disk_size_bytes`
  (storage pool usage) — directly usable for alerting on the 2026-08-04
  replication-burst root-cause fix and the frigate HA node-affinity
  rule. Verify: `curl http://172.16.0.42:8428/api/v1/query?query=up{job="pve_exporter"}`.
- **windows_exporter (added 2026-08-04, same day) — BUILT, NOT YET
  DEPLOYED** — closes the remaining gap: the Windows VMs
  (`win-sql-01`/`win-ts-01`/`win-tms-01`/`win-tzs-01`, VMIDs 250-253,
  see "VMID conventions" below) run neither Alloy (its install role has
  no Windows package logic) nor anything else, so they had zero
  in-guest metrics — only the hypervisor-level view from
  `pve_metrics_export`/`pve_exporter` above. `ansible/roles/windows_exporter/`
  installs `prometheus-community/windows_exporter` via WinRM
  (`ansible/deploy_windows_exporter.yml`), baked into the golden
  Windows Server template build (`ansible/docs/windows_template_guide.md`
  step "E") so future clones ship with it pre-installed. Scrape config
  in `prometheus.yml.j2` (job `windows_exporter`) reads from
  `windows_exporter_scrape_targets` — currently empty, since all 4 VMs
  are powered off with no assigned static IP. **Next step once these
  VMs are turned back on:** assign static IPs (see "VMID conventions"
  below — none currently allocated), run `deploy_windows_exporter.yml`
  against each, populate `windows_exporter_scrape_targets` in
  `roles/victoriametrics/defaults/main.yml`, redeploy
  `deploy_monitoring.yml --limit victoriametrics`.
- **Alloy metrics-only mode for media_ingest/media_ingest_02/media_gallery
  (added 2026-08-05)** — closes the last real gap: these 3 CTs run a
  secondary-source scraper/gallery pipeline deliberately obfuscated in
  this public repo (`vault_media_ingest_02_scraper_pkg`,
  `_scrape_usernames`, telethon private-chat detail — see
  `roles/media_ingest_02_host` and the `git-history-identity-scrub`
  skill), so they were fully excluded from Alloy 2026-07-27 through
  2026-08-04 to keep that detail out of the shared Loki instance —
  meaning zero perf visibility on them the whole time. Fixed by adding
  `alloy_ship_logs: false` (per-host `vars:` in `inventory/proxmox.yml`,
  see `roles/alloy/README.md` "Metrics-only hosts") — the template
  conditionally drops the entire `loki.source.journal`/`loki.write`
  block when set, so ONLY the `prometheus.exporter.unix` block (CPU/
  mem/disk/net counters, no process names, no command-lines, no
  journal content) ships. Verified live 2026-08-05: `up{job=
  "node_exporter",instance=~"media-ingest.*|tg-harvester.*"}`==1 for
  all 3, AND `curl .../loki/api/v1/label/host/values` confirmed to
  carry zero entries for any of them before or after the change. Also
  fixed a real (pre-existing, unrelated) inventory bug found along the
  way: `gallery-01`'s `ansible_host` used the private-subnet IP with
  the default jump-host `ProxyCommand`, which times out for this CT
  specifically since it joined the tailnet directly (renamed from
  `tg-harvester-01`, see warm memory fact 397) — added a per-host
  override to reach it via its real tailnet IP (100.83.114.12)
  directly, no jump.
- **Upgraded to unit-allowlist log shipping (same day, 2026-08-05,
  later)** — user asked specifically about log shipping (not just
  metrics) for these 3 hosts. Audited actual `journalctl` output on all
  3 live boxes before deciding anything (not guessing from unit names):
  confirmed the scraper/collector/gallery service units genuinely log
  sensitive content on nearly every line (media-ingest-02.service logs
  the literal scrape-target username on every INFO line;
  media-ingest-collector.service logs chat IDs + person/folder names;
  media-gallery-*.service logs folder/person names + rclone remote
  paths) — `alloy_ship_logs: false` (all-or-nothing) stays correct for
  those units specifically. But ssh/cron/postfix/systemd-journald carry
  zero sensitive content and ARE useful signal (ssh brute-force
  attempts, cron failures, mail delivery issues) — so upgraded from the
  blunt `alloy_ship_logs: false` to `alloy_log_unit_allowlist` (see
  `roles/alloy/README.md` "Unit-allowlist log shipping"): a
  `loki.relabel` `action = "keep"` rule inside Alloy itself drops any
  journal entry whose unit doesn't match the allowlist regex, before it
  ever leaves the box — not a server-side Loki filter applied after the
  fact. Hit and fixed a real River (Alloy config language) syntax bug
  along the way: double-quoted strings need `\\.` for a literal
  backslash in a regex, easy to get wrong when templating from a plain
  Jinja var — switched to backtick-quoted raw strings (River's
  recommended pattern for regexes) so the value renders verbatim.
  Verified live per-host via direct Loki queries (not just "looks
  fine"): confirmed the 4 sensitive units
  (media-ingest-collector.service, media-ingest-02.service,
  media-gallery-gallery.service, media-gallery-upload.service) return
  `totalLinesProcessed: 0` in Loki — zero lines ever landed — while
  `ssh`/`ssh@*`/`cron` units ARE present with real, safe content (SSH
  session audit trail, no sensitive detail).

## Tanium cluster

| Hostname  | VMID | Private IP       | Role                  |
| :-------- | :--- | :--------------- | :-------------------- |
| `ts-01`   | 200  | `172.16.0.51`    | Tanium Server         |
| `ts-02`   | 201  | `172.16.0.52`    | Tanium Server         |
| `tms-01`  | 202  | `172.16.0.53`    | Tanium Module Server  |
| `tms-02`  | 203  | `172.16.0.54`    | Tanium Module Server  |
| `tzs-01`  | 204  | `172.16.0.55`    | Tanium Zone Server    |
| `tzs-02`  | 205  | `172.16.0.56`    | Tanium Zone Server    |

## BWT lab (bandwidth-throttle repro)

Separate from the existing `tanium_cluster` — uses TanOS appliance VMs on the
isolated `bwt` SDN VNet (`10.99.0.0/24`, VLAN 200). 1× TS + 4× ZS for the
server side; LXC clients for the load drivers. See
`inventory/proxmox.yml` under `bwt_lab` and the `tanium-bandwidth-throttle`
skill for context. Pre-staged Tanium RPMs land in `files/tanium-<version>/`
(gitignored) via `scripts/tanium/fetch_artifactory_bundle.sh`.

Network isolation: the `bwt` subnet is intentionally walled off from the
`private` subnet (172.16.0.0/24) by pve01's `PRIVATE-MONITORING-IN` firewall.
BWT hosts can reach the internet via SNAT through pve01 (10.99.0.1) but
cannot reach `dns-01`, `vm-01`, etc. — BWT uses Cloudflare/Google DNS pushed
by `bwt-dhcp`. Ansible reaches BWT VMs via ProxyJump through pve01.

| Hostname     | VMID | BWT IP                  | Role                              |
| :----------- | :--- | :---------------------- | :-------------------------------- |
| `bwt-dhcp`   | 114  | `10.99.0.2` (static)    | dnsmasq DHCP server (Debian LXC)  |
| `bwt-ts`     | 220  | `10.99.0.10` (static)   | Tanium Server (TanOS)             |
| `bwt-zs-01`  | 221  | `10.99.0.11` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-zs-02`  | 222  | `10.99.0.12` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-zs-03`  | 223  | `10.99.0.13` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-zs-04`  | 224  | `10.99.0.14` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-tc-01`  | 320  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-02`  | 321  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-03`  | 322  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-04`  | 323  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-05`  | 324  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-06`  | 325  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-07`  | 326  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-08`  | 327  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |

DHCP pool: 10.99.0.50–250 (12h lease). 10.99.0.1 is the gateway (pve01),
10.99.0.2 is `bwt-dhcp` (this server), 10.99.0.10–14 are reserved for the
five TanOS servers (excluded from DHCP because TanOS sets static IP at
install time via kickstart).

**Correction (verified live 2026-10-02):** the eight `bwt-tc-0N` client
rows above read `10.99.0.50-250 (DHCP)`, but `inventory/proxmox.yml`
(`bwt_lab` → `bwt_clients`) pins each to a static `ansible_host` in
10.99.0.100–107, and `roles/bwt_dhcp_host` supports MAC→IP reservations
(`bwt_dhcp_static_hosts`, currently `[]`). The pool *range* is correctly
stated; the per-client rows should be treated as **static 10.99.0.100–107
per the inventory**, with the reservation list still to be populated.
(Task-triage item, not yet reconciled in code.)

## Tanium clients (test endpoints)

VMIDs 300-313, IPs `172.16.0.60–73`. See `inventory/proxmox.yml` under `tanium_clients`.

## VMID conventions

- **100–113** — core service CTs (authentik, dns-01, ntp-01, etc.)
- **115–118** — personal/media service CTs (gallery-01, media-ingest-01/02, adblock-proxy-01)
- **114** — BWT lab service CTs (`bwt-dhcp`)
- **200–219** — existing `tanium_cluster` placeholders (ts-01/02, tms-01/02, tzs-01/02)
- **220–249** — BWT lab TanOS VMs (`bwt-ts`, `bwt-zs-01..04`)
- **250–253** — Windows test VMs (win-sql-01, win-ts-01, win-tms-01, win-tzs-01)
- **254–258** — Windows *case-1* test VMs (win-sql-case1-01, win-ts-case1-01, win-tms-case1-01, win-tzs-case1-01, win-dc-case1-01) — live on pve01, stopped (verified live 2026-10-02; same `onboot=0` by-design status as the 250-253 set)
- **300–319** — existing `tanium_clients` LXC endpoints (VMIDs 301-306, 307-310, 312-314; 300 and 311 unassigned)
- **320–339** — BWT lab LXC clients (`bwt-tc-01..08` = 320-327)
- **400+** — reserved / ad-hoc test VMs (e.g. 400 = Some-Other-ECF-Testing)
- **9000-9999** — Proxmox templates (9000=Windows Server 2022, 9001=TanOS 1.8.6 fresh-install, 9002=TanOS 1.8.6 BWT-ready)

## Where IPs are defined (in order of authority)

1. **`ansible/group_vars/all/vars.yml`** — `ip_*` vars are the canonical
   source for the 9 core service CTs:
   `ip_dns_primary`, `ip_ntp_server`, `ip_proxy`, `ip_authentik`,
   `ip_loadbalancer`, `ip_mail_server`, `ip_grafana`, `ip_vm`,
   `ip_tailscale_gw`. Plus `ip_homeassistant` (the off-cluster HA host
   on the LAN that hosts AdGuard for DoT upstream + iOS push). Same
   file also defines `net_private_*` (SDN: range/gw/bridge/mtu) and
   `net_lan_*` (range, gateway).
2. **`ansible/inventory/proxmox.yml`** — every host's `ansible_host:`.
   For the 9 core CTs, this is templated as `"{{ ip_<name> }}"`, so
   `vars.yml` and inventory can't drift. Tanium hosts (cluster +
   clients) and the pve LAN IPs are inlined here directly because
   nothing else needs to consume them as vars.
3. **`ansible/roles/pve_private_ip/defaults/main.yml`** — pve hosts'
   private-subnet IPs (`pve_private_ip_map`).

When the `ip_*` var doesn't match the inventory's `ansible_host` (as
happened with vm-01/mail-01 before the consolidation), bad things
happen silently. The current pattern keeps them in lockstep.

## Adding a new CT

1. Pick a free IP in the appropriate range (check this file).
2. Pick a free VMID (next sequential within the convention range).
3. Add an `ip_<name>` entry to `ansible/group_vars/all/vars.yml` — the
   private-subnet IP that templates the CT's eth0 (as `ip_frigate` /
   `ip_media_ingest` etc. do). A CT that joins the tailnet directly (e.g.
   `hermes-gw-01`, `adblock-proxy-01`, `gallery-01`) additionally gets its
   Tailscale hostname in the inventory (see step 4) while this var still
   templates its static LXC IP.
4. Add the host to `ansible/inventory/proxmox.yml` with
   `ansible_host: "{{ ip_<name> }}"`, plus `vmid` and `target_node`. If the
   CT is reached directly over Tailscale instead of the private subnet,
   `ansible_host` is its tailnet name/IP (with `ansible_ssh_common_args: ""`
   to bypass the jump host) — but `ip_<name>` still exists per step 3.
5. If the CT belongs to the private subnet, ensure it's a member of the
   `private_subnet` parent group in `proxmox.yml` (directly or via a
   child group) so it inherits the work-MacBook ProxyCommand.
6. Update this file with the new allocation.

## INCIDENT 2026-10-09/16: amd-workstation "zombie" (6 days dark, powered on)

The dev box vanished from the tailnet 2026-10-10 02:49:44 CDT and stayed
invisible for 6 days **while powered on the whole time**. Its last boot's
journal (Oct 1 19:07 -> Oct 9 20:56:07) shows two in-kernel page-fault oopses
on 2026-10-09: 09:51:21 (RIP `insn_get_prefixes+0x198`, reached via
`fixup_umip_exception` -- the kernel faulted while emulating a UMIP-trapped
userspace instruction for a python process) and 20:56:07 (the fatal one;
journald's last line IS that BUG and its trace was never flushed. Same
window: 12,078 `im-config` process spawns from the day's test-suite churn +
three python3.14 segfaults). Userland then decayed: tailscaled died 02:49,
DHCP/mDNS stopped, sshd accepted TCP but almost never spawned a child -- no
IPv4 anywhere, kernel-only life signs (TCP SYN-ACKs + IPv6 ND stayed up).
No power event (UPS stayed OL throughout), no disk/thermal/MCE errors.

Found via `ping6 ff02::1` + ssh-keyscan host-key match on IPv6 link-local
(fe80::5a47:caff:fe78:cff7 = MAC 58:47:ca:78:cf:f7). Fixed by owner
power-cycle 2026-10-16 11:41:27 (headless: hold power ~15 s, press once);
came back on kernel 7.0.0-38 (the crashing boot ran -34), all services +
RDP :3389 clean, no failed units.

Durability added 2026-10-16: blackbox probe `blackbox_amd_workstation`
(vm-01 -> 100.66.90.53:22 TCP) + Grafana rule `amd_workstation_unreachable`
(severity warning, 5m for) -- verified live (probe_success=1). If it recurs:
capture the full oops (serial/pstore) and consider a memtest86 pass; the
faulting code path is kernel-side, but a hardware cause is not fully
excluded.

### Deep-dive follow-up (2026-10-16, post-reboot forensics)

Symbol-resolving the fault IPs against the suite's PM-built python (3.14.7,
Clang/BOLT build with `--with-mimalloc`, `--with-tail-call-interp`) shows
EVERY Oct-9 interpreter crash landed inside CPython's cyclic GC
(`visit_decref` x3, `dict_traverse`, `meth_traverse`, `visit_reachable`,
`tuple_dealloc`, `gc_collect_main`) -- the code that walks the object graph.
That is the signature of a corrupted/dangling object in the process heap,
not of random hardware faults. Both kernel oopses happened while the kernel
was handling one of those crashing pythons (the 09:51 one faulted at
`visit_decref+4` and went through the #GP/UMIP path; the 20:56:07 one landed
2 s after three GC crashes and was fatal). NOTE: the suite ALSO deliberately
crashes interpreters by design (test_run_tests_parallel.py generates a probe
doing `os.kill(os.getpid(), signal.SIGSEGV)`; verified that signal-delivered
SIGSEGV produces NO kernel dump, so the 8 dumps above are genuinely real
faults). PRIME SUSPECTS ARE CO-EQUAL (reference-model review): the custom PM
python build (mimalloc/BOLT/tail-call are the nonstandard pieces; the PM
toolchain python was first installed 2026-10-09 09:31 -- no clean-run history)
vs marginal RAM/IMC instability flushed out by first heavy load (non-ECC
DDR5: no MCE reporting exists, so "no MCEs" says nothing about RAM). No
UMIP/insn-decoder fix identifiable in the 7.0.0-38 changelog, so the
kernel-side bug's fix status is unconfirmed. Package + fs integrity
verified clean (`dpkg -V`), no thermal/disk events. The stuck Oct-9
apport crash file (from the deliberate-crash test) was removed, which also
cleared the box's "degraded" systemd state.

Auto-recovery hardening deployed 2026-10-16 (all verified live):
- softdog made persistent (`/etc/modules-load.d/softdog.conf`) and systemd
  now runs `RuntimeWatchdogSec=60` (`/etc/systemd/system.conf.d/watchdog.conf`,
  applied via `daemon-reexec`; `wdctl` confirms /dev/watchdog0 armed, 60 s).
  A userland stall reboots the box instead of rotting for days.
- `/etc/sysctl.d/90-lockup-recovery.conf`: `kernel.panic_on_oops=1`,
  `kernel.panic=20`, `kernel.hardlockup_panic=1` -- the next oops panics and
  reboots, with an efi-pstore entry preserving the full trace.
- kdump RESOLVED same day: the crashkernel reservation had actually
  succeeded (1 GiB at 0x58000000) -- the tool was just shipped with
  USE_KDUMP=0; set to 1 + `kdump-config load` -> "ready to kdump" (UNTESTED -- a deliberate crash-test to validate the
  chain is pending owner go-ahead; until validated it is a small risk to
  auto-recovery). A future panic now ALSO yields a full vmcore in /var/crash on top of the pstore
  trace.
- smartmontools + nvme-cli installed. SMART: 0 media/data-integrity errors,
  100% spare, 1% used, 25 C; 53 unsafe shutdowns lifetime (Samsung 970 EVO
  500GB). The NVMe error log holds only benign "Invalid Field in Command"
  entries (userspace tools polling unsupported log pages) -- no I/O fault.
- RAM burn-in (stressapptest, 2 h / ~52 GB, memory+CPU only) scheduled as a
  one-shot systemd timer for 2026-10-17 02:00 CDT (self-disables after
  running; log -> /var/log/ramtest-*.log). Headless equivalent of a
  memtest86 pass; result pending.
Extended to 8 h (02:00-10:00) after the reference-model review.

Round-2 hardening same day (post reference-model review, 2026-10-16):
- The reachability probe now uses the `ssh_banner` blackbox module (expects
  the SSH version string) instead of a bare TCP connect -- a zombie PASSES
  tcp_connect (the kernel completes the handshake), so the original probe
  would have missed exactly this failure. The rule's NoData/Error states
  now alert too (a dead probe cannot be silent).
- New rules: `amd_workstation_rebooted` (boot-time change detector, so even
  WATCHDOG SELF-HEAL REBOOTS page) and `amd_workstation_prev_boot_oops`
  (kernel oops/segfault lines in the previous boot, fed by a boot oneshot
  writing a node_exporter textfile metric). `host_down` now excludes
  amd-workstation (dedicated rules instead). node_exporter installed on the
  box + pull-scraped from vm-01 by tailnet IP -- first full metric coverage
  for this host.
- Watchdog: hardware FCH TCO (`sp5100_tco`, binds on this board) preferred
  from next boot (`modules-load.d/10-sp5100_tco.conf`); softdog kept as
  fallback. `crash_kexec_post_notifiers` added to GRUB so the kdump handoff
  still runs kmsg_dump -> efi-pstore. `kernel.softlockup_panic=1` added.

Round-3 (same day, after a second review served on claude-fable-5-1):
- **Userland deadman deployed** (`/usr/local/bin/userland-deadman.sh` + 2-min
  timer): checks local sshd banner + systemd responsive + fork/exec; 3
  consecutive strikes -> `sysrq-c` so kdump captures a vmcore of the zombie
  state. Covers the class the systemd watchdog does NOT: during the 10-09
  zombie PID 1 was still being pinged while userland was dead. Inhibited
  during scheduled RAM burn-ins (`/run/ramtest-inhibit`).
- **TCO watchdog idea DROPPED** (`10-sp5100_tco.conf` removed): the hardware
  TCO timer survives into the kdump crash kernel where nothing kicks it ->
  it would reset the box mid-dump, truncating the vmcore. softdog is the
  kexec-compatible choice; panic_on_oops + hardlockup_panic cover the
  kernel-side classes.
- `prev_boot_oops` alert now fires only within 1 h of a boot that found oops
  lines (no stale re-fires); added a textfile-scrape-error alert.
- **Crash-test prechecks done**: `kexec_crash_loaded=1`, state "ready to
  kdump", /var/crash space fine. objdump of `visit_decref` shows ordinary
  encodings (no exotic build-specific decoder trap). The 8 crash cores are
  gone (only kdump's kexec_cmd remains) -- the single-bit-flip vs
  fill-pattern discriminator is no longer runnable.
- **PENDING OWNER GO**: deliberate `sysrq-c` crash test to validate
  panic -> kdump/pstore -> reboot -> alerts end-to-end (box down ~2-5 min;
  worst case needs a power-button press).

Round-4 (2026-10-16 evening): crash test VALIDATED + the original oops traces recovered.
- Deliberate `sysrq-c` test PASSED end-to-end: panic 13:23:12 -> kexec crash
  kernel 13:23:38 -> makedumpfile done 13:23:50 -> back online 13:24:17
  (~65 s total downtime). Artifacts: /var/crash/202610161323/
  (`dmesg.202610161323` ~116 KB, `dump.202610161323` vmcore ~356 MB); the
  crash-kernel's own log persisted to the journal (boot -1 = a 12-second
  kdump boot); kdump re-armed automatically after. The "amd-workstation
  rebooted" alert fired (caveat: it also fires once when the metric series
  first appears -- benign changes() artifact).
- The ORIGINAL Oct-9 oops traces were recovered from **efi-pstore** (archived
  by systemd-pstore at the 11:41 boot): `Oops#1` = kernel decoder fault in
  `fixup_umip_exception` (insn_get_prefixes+0x198; not tainted; userspace #GP
  from a dying python). `Oops#2` (fatal) = **`jbd2/dm-0-8`** (the ext4 journal
  thread) wild-pointer read in `folio_mapping+0x9` at 0xfffff0a3bd888f33,
  kernel TAINTED (G D) from Oops#1. Two DIFFERENT subsystems faulting on wild
  pointers + the python GC crashes = systemic-corruption signature =>
  RAM/IMC instability is now the PRIMARY suspect (custom python build
  secondary). The 8-hour RAM burn-in tonight is the key discriminator.

Round-5 (2026-10-17 morning): the burn-in ran — and within 11 minutes it caught the
machine corrupting memory; then the box hard-froze and stayed dead ~7 h until a
physical power-cycle.

- 02:00:00 `ramtest-overnight.service` started (`stressapptest -s 28800 -M 52000 -W
  --printsec 600`). The wrapper touches `/run/ramtest-inhibit` (deadman no-op during
  burn-ins) and only disarms the timer AFTER a completed run.
- 02:10:19 (619 s in), immediately after the deliberate power-spike phase (15 s
  thread pause, then resume): the first Hardware Errors — 11+ `miscompare`s within
  one second, sprayed across cores (16, 18, 29, 1, 13, 2, 13(<-19) ...), patterns
  `OneZero32` (e.g. read 0xffffffff00001000 vs expected 0xffffffff00000000 — one
  stuck bit), `walkingInvOnes~32`, `Checker8b10b32`. This is real data corruption
  in the memory path under load (non-ECC DDR5 — nothing else in the system can
  catch or correct it).
- Same second (02:10:19): the KERNEL began dumping crash records to firmware
  storage — systemd-pstore archived 41 part-files (~20 chained dumps, incl.
  002/dmesg.txt) this boot to `/var/lib/systemd/pstore/1792221019/{001,002}`.
  Root-only; NOT yet read. Working hypothesis: the kernel panicked (panic_on_oops=1)
  and then recursively faulted inside its own crash-handling path.
- Then silence, everywhere: kern.log's last kernel line is 02:08:48, journald flush
  stops 02:09:38, no oops/panic/MCE in any readable log, no kdump vmcore in
  /var/crash, no reboot, no console output. The NMI hardlockup detector was enabled
  (hardlockup_panic=1) and never fired either — the freeze was below every
  software/NMI recovery layer. Box dead until the 09:28:16 power-cycle boot.
- 09:28 recovery (owner power-cycle): box up 09:28:16; kdump re-armed
  (kexec_crash_loaded=1), userland-deadman timer active (2-min), node_exporter +
  blackbox probe green, `amd-workstation unreachable` alert resolved.
- FINDING — the watchdog is NOT armed; the Round-2 "wdctl confirms /dev/watchdog0
  armed, 60 s" claim is WRONG. softdog is blacklisted by the kernel package's own
  kmod deny-list (`/lib/modprobe.d/blacklist_linux_7.0.0-38-generic.conf:61`
  `blacklist softdog`, same in the -34 file): every boot logs `Module 'softdog' is
  deny-listed (by kmod)` and `Failed to open any watchdog device before the initial
  transaction completed`; `/dev/watchdog0` does not exist. RuntimeWatchdogSec=60
  has therefore never actually been armed. Fix path (pending): /etc/modprobe.d
  override with `install softdog /sbin/modprobe --ignore-install softdog`
  (install-lines beat blacklists), keep /etc/modules-load.d/softdog.conf, then
  `systemctl daemon-reexec` and verify `wdctl` shows /dev/watchdog0 armed.
- FINDING — the burn-in timer is not one-shot in practice: `ramtest-overnight.timer`
  is `OnCalendar=*-*-* 02:00:00` with `Persistent=no`; the wrapper self-disarms only
  at the END of a completed run, so a mid-run death leaves it armed. It is NOW armed
  for 2026-10-18 02:00 (would re-kill the box). Disarm pending owner:
  `sudo systemctl disable --now ramtest-overnight.timer` (this box's sudo is
  interactive-only).
- Pending: copy `/var/lib/systemd/pstore/1792221019/` to a user-readable dir (needs
  root) and mine the ~20 chained crash dumps for the actual panic trace.

Round-6 (2026-10-17, later morning): crash records recovered and READ; root access path
established; the burn-in's outcome is now fully explained.

- ACCESS (cost an hour to pin down): key-based sudo works on this box via
  pam_ssh_agent_auth + a forwarded agent (`ssh -A`). GOTCHA: `sudo -n` BYPASSES the PAM
  key auth entirely — "a password is required", the pam module never even runs (no
  logs). Use plain `sudo cmd </dev/null` over `ssh -A`. Verified live: unauthenticated
  `sudo -k; sudo true` succeeds via the Mac's RSA key, with and without a tty.
- Done via that path: ramtest timer disarmed; crash records published to
  ~/pstore-crash-20261017 (41 parts = two record groups, plain text, ~96 KB total).
- Crash log content (uptime 45973.6s = 02:10:19):
  * Oops#1: `BUG: unable to handle page fault for address: ffff9b5e997761c8` in
    `remove_wait_queue` (poll_freewait <- do_sys_poll <- ppoll) — the faulting pointer
    differs from its sibling (RAX ffff9b5e997761c8 vs RDX ffff8b5e997761c8) by ONE BIT
    (bit 36): the same single-bit signature, now in KERNEL memory (a corrupted wait-queue
    pointer in a ppoll wait).
  * Panic#2: repeated `BUG: Bad page map in process stressapptest
    pte:800020002523d867` / `pte:80002009d4d2d867` during /proc/self/pagemap reads —
    corrupted PTEs; panic_on_oops -> panic -> kdump handoff never completed -> freeze.
- Hardware (dmidecode -t 17): 2x32GB Corsair CMSX32GX5M1A4800C40 SO-DIMM; Speed 4800
  MT/s, Configured 4800 MT/s at 1.1 V => STOCK JEDEC, no EXPO/XMP enabled. The
  "turn off the memory overclock" branch is therefore moot. Next: reseat both
  SO-DIMMs, then single-stick bisection with the short stressapptest repro (errors
  appeared at 619 s in the burned run).
- BIOS-from-Linux: uefisettings v0.1.5 built on the box (~/.cargo/bin), Hii backend
  detected (AMI 1.17); root now reachable for it via the sudo path above.
- Safety net: softdog was kmod-deny-listed (never armed). Fixed via
  /etc/modprobe.d/55-softdog-unblacklist.conf (install-line override) + module load +
  daemon-reexec; verified with wdctl.

Round-7 (2026-10-17): BIOS-settings-from-Linux — fully investigated: READ yes, WRITE no.

- Read path SOLVED without /dev/mem: the official firmware image
  (https://pc-file.s3.us-west-1.amazonaws.com/895D7/BIOS/DRFXI_1.17_260828A.7z — the exact
  version this box runs) was extracted with UEFIExtract (A75) + IFRExtractor-RS 1.6.1.
  The AMD CBS catalog (module CbsSetupDxeRPL) declares its target store outright:
  VarStore Guid 3A997502-647A-4C82-998E-52EF9486A247, Size 0x6D5 — byte-for-byte the live
  "AmdSetupRPL" efivar (1749 B payload). Full question->offset map for the memory menu,
  e.g. Memory Context Restore @0x263 and Power Down Enable @0x16F (each 0=Disabled,
  1=Enabled, 255=Auto), plus memory interleaving @0x36/0x37, map inversion @0x38,
  Chipselect Interleaving @0x174, BankSwapMode @0x177, PDA Enumerate @0x261.
- Live decode today: Memory Context Restore = Auto, Power Down Enable = Auto.
- WRITES: firmware-blocked. All three setup stores (AMD_PBS_SETUP, AmdSetupRPL,
  AodSetupRpl) return EROFS (EFI_WRITE_PROTECTED) on OS writes even with the efivarfs
  immutable flag cleared; only non-setup vars (e.g. BootOrder) accept writes. The earlier
  "AmdSetupRPL: WRITE-OK" reading was an artifact — its backup step silently wrote an
  EMPTY file (cp(1) can't lseek efivarfs; see pitfall) and the 0-byte write was
  meaningless. uefisettings' `set` would hit the same wall; disabling Secure Boot would
  only unblock /dev/mem READS, never writes. => any real BIOS change still needs the
  BIOS screen (combine with the RAM reseat visit).
- PITFALL: cp(1) cannot read efivars (lseek -> "Illegal seek", EMPTY destination). Use
  cat/dd/python/tar for efivar reads. For writes: chattr -i + one single write
  (python/tee) + chattr +i; only works on firmware-writable vars.
- Useful consequence: BIOS settings can be READ, dumped, diffed and POST-VISIT VERIFIED
  from Linux anytime (no monitor) — including whether a manual BIOS change actually took.

Round-8 (2026-10-17): Fable consult #2 on next-step options + remote survivability step done.

- Fable's reframing (new evidence): the flipped-bit LANES VARY across events — bit 12 (user
  data), bit 36 (waitqueue pointer), bit 45 (in the bad PTE) — so NOT a single bad DQ
  pin/trace; it is read-path marginality collapsing under the idle->load transient. Two
  shared-rail candidates fit: the DDR5 on-module PMIC (per stick; VDD/VDDQ load-step
  response) and board/SoC VDDIO/VSOC droop (shared). The bisection is designed to split
  those two.
- STEP 0 EXECUTED (remote, today): survivability first — sp5100_tco (hardware FCH
  watchdog) replaces softdog as the systemd watchdog from next boot
  (/etc/modules-load.d/{sp5100_tco,softdog}); tco verified binding on this kernel
  (MMIO 0xfeb00000, heartbeat 60 s, /dev/watchdog1 now, will be watchdog0 after reboot);
  kernel.panic=15 set; kdump now unloaded ONLY during stress runs via ~/stress-run.sh
  (availability > extra vmcores; the old TCO-vs-kdump objection is thereby retired for
  test runs).
- PLAN (Fable-ranked): (1) attended baseline repro at stock AS-IS:
  `stressapptest -s 1500 -M 52000 -W --pause_delay 120 --pause_duration 15` (~11
  transients, first one warm; reproduced = >=1 miscompare). Reseat-first and suite-first
  both rejected as information-destroying/weaker detectors. (2) Remote discriminator:
  cpuidle capped to C1 + performance governor, same recipe — flips vanish => the
  idle->load transient is the trigger (and a software workaround exists); persist =>
  DRAM power-down exit suspect. (3) ONE physical visit, in order: single-stick/slot
  bisection (-M 26000, --pause_delay 90, >=30 min per config; configs S1-in-A, S2-in-A,
  failed-stick-in-B) -> PSU brick swap ONLY if bisection points shared-rail -> BIOS
  session: Power Down Enable=Disabled + Memory Context Restore=Disabled first, then
  DRAM 4000 as margin PROBE, then VDDIO_MEM/VSOC +50 mV if the CBS map exposes them.
- RMA: fault follows a stick => Corsair (lifetime; attach dmidecode JEDEC proof +
  miscompare logs + slot-swap evidence; keep the kernel-oops story out). Follows the slot
  / both-pass-alone / dual-fails => Minisforum (expect friction). Fastest discriminator:
  a known-good 2x32 GB kit.
- EXTRA found + available: the DIMM SPD hubs are visible on SMBus (spd5118 hwmon4/5,
  /dev/i2c-0..3 after i2c-piix4) — PMIC under-voltage/status flags are readable if they
  latch during a repro (near-conclusive, free). memtest86+ = RMA paperwork only (no
  idle->load transient).
- Acceptance (post-reproduction): >=3 strong-trigger runs totalling >=100 transients
  (cold-start AND after 1 h hot), zero miscompares; original 8 h recipe clean; 24 h of the
  real test suite with zero kernel warnings; then two weeks production with the hardware
  WDT armed and no resets. Anything only achievable with a downclock or C1-cap is recorded
  as a MITIGATED BOARD FAULT, not a fix.

Round-9 (2026-10-17): remote-BIOS-management options + the two requested settings.

- WATCHDOG (owner ask #1): DONE. Hardware FCH watchdog (sp5100_tco) configured as the
  systemd watchdog from the next reboot (verified binding now: MMIO 0xfeb00000,
  heartbeat 60 s); panic=15 + panic_on_oops give automatic reboots for kernel panics;
  hard freezes reset via the TCO; userland deadman covers zombie states. (Verify after
  next reboot: wdctl should show "SP5100/SB800 TCO" on /dev/watchdog0.)
- AC-LOSS (owner ask #2): the setting EXISTS — AMD CBS -> FCH Common Options ->
  "Ac Power Loss Options" -> question "Ac Loss Control", AmdSetupRPL VarOffset 0x61,
  options 0="Always Off" (factory default), 1="Always On" (+1 more). LIVE value decoded
  today = 0 ("Always Off"): after a power cut the box stays OFF. Changing it needs the
  BIOS screen (writes blocked) or a KVM-over-IP.
- REMOTE BIOS MANAGEMENT (owner ask #3): (a) Serial/SOL: NOT possible on this board — no
  BMC/IPMI, no exposed UART. (b) fwupd DOES expose a "System Firmware" capsule device
  (ESRT present) but Minisforum publishes no Linux capsules -> no remote BIOS update
  today; the official flasher package (DRFXI_x.xx .7z with AfuEfix64.efi) runs from a UEFI
  shell -> needs a local screen or a KVM. (c) The real solution for a headless board with
  no BMC = a KVM-over-IP device (JetKVM / NanoKVM / GL.iNet Comet / PiKVM): HDMI + USB-HID
  + optional ATX power header control; gives remote BIOS menus, remote BIOS flashing
  (virtual USB), and remote power cycles. Pair with a smart plug for hard power cycling
  (needs "Ac Loss Control: Always On" set once). Physical install = one 10-minute session.
  Until then, all BIOS changes = the single monitor+keyboard visit (fold into the RAM
  reseat): reseat SO-DIMMs + Ac Loss Control=Always On + (optional) Power Down off/MCR off.

Round-10 (2026-10-17): free remote-BIOS toolkit BUILT and staged (nothing activated).

- ~/bios-remote on the box: src/bios-set.c + Makefile -> build/bios-set.efi (gnu-efi;
  PE32+ EFI app, ~178 KB). Behavior: reads \bios-cmd.txt from the ESP ("EXTRACT <guid>" or
  "ROUTE <config string>"), calls the firmware's HII Config Routing interface (the
  interface the OS-side write is NOT protected against), writes \bios-result.txt, then
  cold-resets back. apply-bios.sh stages a command + a one-shot BootNext (never reboots
  by itself). keys/MOK-bios.{priv,crt,der} generated for the enroll-a-key-at-the-visit
  option (backed up on the Mac). README.md has the runbook.
- Build gotchas fixed: Ubuntu binutils 2.46 requires explicit
  `objcopy -I elf64-x86-64 -O efi-app-x86_64 --subsystem=10` (format auto-detection
  fails); and the classic gnu-efi section list MUST include `-j .rodata` or every
  wide-string literal is silently dropped from the PE (caught before any boot use).
- NOTHING activated: no boot entries, nothing on the ESP, no reboots. First live use is
  gated on the visit (Secure Boot off OR MOK enrollment of our cert) plus an explicit go;
  the first test will be flipping "Ac Loss Control" to Always On via HII routing, then
  verifying byte 0x61 from Linux.
- UEFI Shell (for a future remote flash) not yet sourced — tianocore's recent release
  assets don't carry it; deferred until a flash is actually wanted.

Round-11 (2026-10-17): hardening pass on the remote-BIOS toolkit + access paths.

- bios-set.efi now ROUTE-allowlists this board's three settings stores (AmdSetupRPL /
  Setup / AMD_PBS_SETUP); anything else is refused ("denied-guid" in the result file).
  Rebuilt; allowlist strings verified present in the binary.
- MOK signing PRIVATE key custody: removed from the box (only MOK-bios.crt + .der remain
  there as import material). The private key now lives ONLY on the Mac, durably at
  ~/.ssh/bios-mok/ (0600, outside the scratch pruner); signing = copy in, sbsign, shred.
  README updated (Privileges & teardown section).
- Verified dormant: ESP has no staged files; boot entries remain Ubuntu-only; nothing is
  active until apply-bios.sh is invoked (one-shot BootNext; never self-reboots).
- Open items for the owner: (a) /etc/security/authorized_keys (sudo-via-key) holds 5 keys
  — key1 = the Mac's RSA (in use); keys 2-5 (1x RSA-2048 + 3x ed25519) look legacy; prune
  on request. (b) Agent forwarding to this box exposes the Mac's agent to a compromised
  box for the session's lifetime; a dedicated per-box key would bound that blast radius.

Round-12 (2026-10-17): signing key moved into 1Password; plaintext copies scrubbed.

- Stored as a Secure Note in the Personal vault: "amd-workstation BIOS signing key
  (bios-remote MOK)" (item id w2x7ixugvnfj3xw4xcynwgajly) — private key + certificate +
  usage/runbook text. Created via `op item create --template` with output suppressed; the
  stored copy verified by SHA-256 against the source before any deletion.
- Then scrubbed: the Mac's ~/.ssh/bios-mok/MOK-bios.priv, the scratch backup copy, and the
  build-window working files (overwrite-with-urandom + delete). Public material that
  remains: box keys/MOK-bios.crt|der (import material) + Mac ~/.ssh/bios-mok cert.
- Signing workflow is now: `op read "op://Personal/<id>/notesPlain"` -> extract key ->
  temp-sign-shred. Recorded in the box README (Option B section).

Round-13 (2026-10-17 midday): baseline repro CONFIRMED + first live self-recovery; watchdog fully armed.

- Baseline repro (stressapptest -s 1500 -M 52000 -W --pause_delay 120 --pause_duration 15):
  first miscompare at 258 s (~4.3 min, first load-spike cycles), then a burst until death at
  10:56:41 — 1,888 error lines in ~8 s ('walkingInvOnes~32', 'OneZero~256': whole 256-byte
  regions read as all-ones where zeros expected, reread ALSO wrong this time). Kernel oops
  10:56:35 (journal tail), panic, efi-pstore record written (archived this boot as
  /var/lib/systemd/pstore/1792252601). With kdump unloaded for the stress window, panic=20
  did its job: the box REBOOTED ITSELF — back up at 10:57:11, ~33 s after the oops, no human
  intervention. First live proof of the auto-recovery chain.
- Watchdog gap re-opened and CLOSED: the morning's modules-load.d/sp5100_tco.conf was
  silently EMPTY (casualty of the known heredoc-write mangling) and sp5100_tco is also
  kernel-package deny-listed (line 62, next to softdog's 61). Reinstalled byte-exact via
  scp+install, plus an install-line override in /etc/modprobe.d/55-sp5100-unblacklist.conf.
  Loaded + armed NOW without a reboot: /dev/watchdog0 = "SP5100 TCO timer", 60 s,
  KEEPALIVEPING=1 (systemd feeding it). kernel.panic=15 applied (the morning's 91-panic-15
  drop-in was empty for the same reason; re-installed from a byte-exact source).
- Posture: panic -> 15 s -> auto-reboot; hard freeze -> hardware TCO reset <= 60 s; stress
  runs unload/re-arm kdump via ~/stress-run.sh. Next: BIOS session (Ac Loss Control = Always
  On; Power Down Enable = Disabled; Memory Context Restore = Disabled; Secure Boot choice),
  then the SO-DIMM bisection.

Round-14 (2026-10-17 ~11:35): BIOS session done + verified; watchdog made boot-persistent.

- Owner BIOS session (monitor attached): "Ac Loss Control" = Always On; Secure Boot =
  Disabled. Verified from Linux, byte-level: AmdSetupRPL @0x61 = 1 (Always On) ✓;
  mokutil --sb-state = "SecureBoot disabled" ✓. NOTE: this firmware's UI HIDES "UMC Common
  Options" (owner walked the CBS menu: CPU/CBIO/FCH/SMU only) — the two DDR toggles
  (Power Down Enable, Memory Context Restore) are unreachable by hand; recorded as a
  candidate for the remote HII-routing toolkit instead of a console task.
- Watchdog boot persistence: the modules-load.d + install-line approach does NOT survive
  systemd-modules-load (its blacklist flag wins over install-lines). Replaced with an
  enabled unit /etc/systemd/system/sp5100-tco.service (ExecStart: modprobe
  --ignore-install sp5100_tco + systemctl daemon-reexec). Verified armed live (SP5100 TCO,
  60 s, KEEPALIVEPING) and enabled for future boots.
- The "long-running process" the owner spotted = unattended-upgrades.service
  (unattended-upgrade-shutdown --wait-for-signal) — an idle by-design Ubuntu waiter that
  lives from boot to shutdown; ~0% CPU; no action needed.

Round-15 (2026-10-17 ~11:50): remote-BIOS WRITE path live-tested — REFUSED by firmware; scaffolding removed.

- Boot 1 (EXPORT): tool ran, rc=0, wrote an 89 KB configuration dump; our store present in
  the firmware's own dialect (GUID=<memory-order-hex>&NAME=<utf16-hex>&PATH=<device-path>
  &OFFSET=0&WIDTH=6d5&VALUE=<full 1749-byte block>). QUIRK: the exported block carries
  DEFAULTS, not live values (952/1749 bytes differ from the live efivar) — efivar reads
  remain the source of truth for settings.
- Boot 2 (ROUTE, true no-op replaying the live bytes verbatim): rc=0x8 =
  EFI_WRITE_PROTECTED, progress = the full string (nothing applied); var hash-identical
  afterwards. CONCLUSION: this firmware locks its settings stores after the setup UI
  closes — the lock covers the HII Config Routing path too — so no post-boot software can
  write them. Remote BIOS setting changes on this board: impossible; the setup screen (or a
  KVM) is the only route. The toolkit remains a read/dump asset and is portable to boards
  that do not lock their stores.
- Cleanup: test boot entry removed, ESP payloads removed + archived to
  ~/bios-remote/records/, /tmp tidied; settings verified intact (Ac Loss Control=1,
  PowerDown=255, MCR=255). README carries the STATUS note.

Round-16 (2026-10-17 ~12:00): kill + substitute consult + RMA evidence bundle.

- Killed the owner-flagged process properly: unattended-upgrade-shutdown --wait-for-signal
  (the boot-time idle waiter) killed AND its unit disabled so it stays dead across boots;
  the actual update timers (apt-daily / apt-daily-upgrade) remain scheduled. Undo:
  systemctl enable unattended-upgrades.service.
- Fable's local consult route returned empty twice (unavailable; looks like the known
  Anthropic session/route issue). Per the fable-consult-remote skill's fallback order, one
  explicit-override retry through the consult tool was made with a strong substitute
  (deepseek-v4-pro @ ollama-cloud). SUBSTITUTE RULING (attribution: not Fable; re-surface at
  final sign-off): (A) remote-BIOS write question is CLOSED — EFI_WRITE_PROTECTED post-
  EndOfDxe is exactly the standard AMI/EDK2 VariableLock behavior; capsules are update-only
  transport; no supported settings path exists beyond the setup UI; the defaults-not-live
  export quirk further evidences intentional runtime closure. (B) The region-level
  corruption (whole 256-byte blocks, reread-wrong) is not a single-cell/data-line fault —
  it points to an undriven/deselected rank or a failed write/address path: SoC/UMC,
  board/DIMM interconnect, and PMIC/PDN rail move ABOVE DRAM cell/row. Bisection remains the
  right next step, refined: keep --pause_delay 120; 30 min/stick suffices (baseline fails
  at ~4 min); S1-in-A, S2-in-A; if both pass alone, ALSO run swapped dual-stick
  (S1-in-B/S2-in-A) because the original failure may require dual-DIMM load. Fails-follows-
  stick => Corsair RMA; follows-slot/board or dual-only => Minisforum unit RMA. (C) Evidence
  checklist before opening the case: dmidecode memory + DIMM labels/serials; full stressapptest
  log with command line; journalctl -k boot->panic incl. MCE/EDAC; both pstore records off-box;
  sensors log during a stress run; BIOS screenshots of stock JEDEC/1.1 V. (D) Same root cause
  escalating, not a second failure mode.
- Evidence bundle assembled at ~/rma-evidence (box + Mac): dmidecode memory/system/serials,
  SMART (unsafe shutdown count), lscpu, kernel log of the crash boot, MCE/EDAC scan, both
  pstore crash records, and the captured 1,888-error stress log.

Round-17 (2026-10-17 ~12:15): REAL Fable verdict obtained (remote route; local route down)
+ forensic refinements to the corruption analysis.

- Remote route fix: `claude-fable-5` 404s now on the work MacBook; the working id is
  `claude-fable-5-1` (skill patched accordingly).
- FABLE VERDICTS (binding): (A) Remote-BIOS writes CLOSED — standard AMI/EDK2 VariableLock;
  the "export returns defaults" quirk is NOT evidence of intent (common artifact). Two
  supported vendor paths remain, both "ask the vendor": (1) request a 1.17 build from
  Minisforum with the AMD CBS/UMC menus unhidden (done for other boards); (2) AMI's own
  AMISCE/SCEWIN tooling (SMI-based, so outside the DXE lock; OEM-licensed).
  (B) CORRECTION to the substitute ruling: don't carry "SoC/UMC + rails above DRAM" into the
  case narrative. Corruption bounded to <=256-B granules = a PER-CHANNEL fault (256 B is
  the DF interleave granule): stick PMIC/training margin ~ slot PHY/traces > a single UMC
  instance >> board rails/fabric. Cell/row stays down as a suspect. (D) One fault, "now
  reproducible on demand" — "escalating" is unproven (the pause recipe is simply a far more
  sensitive detector).
- OUR FORENSICS per Fable's test (raw 944 parsed errors): pattern-name suffixes are pattern
  VARIANTS (confirmed in pattern.cc), not region sizes — but the ADDRESS analysis shows
  real contiguous runs topping out at EXACTLY 256 B (32 qwords); classification: 419
  stale/other-pattern reads (dropped/misdirected writes — dominant), 218 whole-word
  inversions, 94 clean single-bit flips (the original bit-12 signature persists), 213 other
  (incl. split-word values like 0x55555555aaaaaaaa = two pattern generations in one qword).
- FABLE'S FINAL BISECTION DESIGN: full 2x2 (each stick in each slot, 30 min/config,
  ~2 h): `stressapptest -s 1800 -M 26000 -W --pause_delay 120 --pause_duration 15` AS ROOT,
  FULL AC-off cold boot (unplug 30 s) at every change (forces retrain; record
  dmidecode -t 17 speed), temp logging each run; a "passing" suspect stick needs a second
  cold-boot run; then dual-swapped, then original dual config (if original now passes =>
  reseating/contact is the finding). Decision: stick-fails-both-slots-and-other-passes =>
  Corsair RMA; both-fail-one-slot => Minisforum; both-fail-both => tiebreak on a known-good
  4800 SO-DIMM before blaming anyone; all-singles-pass + dual-fails => Minisforum.
- FABLE'S PRE-CASE LIST: (1) run a NO-PAUSE control (30 min steady, same -M) — passing
  steady while failing in 4 min with pauses is the single most persuasive line for either
  warranty desk; (2) confirm BIOS >1.17 exists (1.17 appears latest; verify), else bisect on
  1.17 then update + re-run the 4-min dual repro once; (3) optional C-state-capped run
  (mitigation probe, not a discriminator); (4) don't volunteer memtest86 (no load step, gives
  the desk an excuse); lead with the stressapptest log; (5) DIMM label photos + slot mapping
  at the visit.













