# pve01 network stall and HA fence — 2026-11-09 and 2026-11-15

Status: **cause identified, trigger not proven. Mitigation, full-fidelity capture and
alerts all in place 2026-11-15.** pve01's `e1000e` NIC driver logs `Detected Hardware
Unit Hang` and the NIC stops passing traffic until the HA watchdog reboots the node.
TSO/GSO is off on pve01's `nic0`; whether that prevents the hang is unknown until it
has gone a few weeks without one. All times CST.

## What happens, step by step (2026-11-15)

| time | what |
|---|---|
| 06:36:46 | pve01 witness: last good heartbeat (`HB nic0=up quorate=Yes`) |
| 06:37:01 | pve01 kernel: `e1000e 0000:00:1f.6 nic0: Detected Hardware Unit Hang`, repeated every 2 s from here on |
| 06:37:05 | corosync on pve02/pve03: both knet links to pve01 down in the same second |
| 06:37:06–06:37:11 | pve01 witness: every probe (pve02, pve03, SG105E, gateway, WAN) flips to down |
| 06:37:12 | pve02/pve03 re-form membership without node 1; quorum 2/3 holds |
| 06:37:22 | HA CRM: pve01 `online` → `unknown` |
| 06:38:02 | last line written by pve01's per-second progress witness (host still running) |
| 06:38:05 | last of 33 `Hardware Unit Hang` lines; the node resets |
| 06:38:12 | HA CRM: pve01 → `fence`; its services → `fence` |
| 06:38:49 | pve01 kernel boots; 06:38:59 corosync link up; 06:39:00 membership 3/3 |
| 06:41:13 | HA recovers `ct:102`→pve03, `ct:130`→pve03, `ct:141`→pve02, `ct:158`→pve02, `ct:170`→pve03, `vm:241`→pve03 |

Three facts pin it to pve01's own NIC:

- **The rest of the network was fine.** pve02 and pve03 logged exactly one
  transition, `pve01=down`. Their view of the SG105E, the gateway and the WAN never
  changed. pve01's own view had *everything* down, including pve02 and pve03.
- **No carrier drop was recorded.** The 1-second witness has no `nic0carrier=0`
  line, so the link did not go down; the NIC stopped moving frames with the link
  still up.
- **The host was alive.** `/root/progress_witness.log` kept writing an `uptime=`
  line every second until 06:38:02. It was not a kernel freeze; the reset came from
  the HA watchdog about 60 s after the hang began.

`nic_stall_watch` (`scripts/network/nic_stall_watch.sh`, `/root/nic_stall.log`)
caught the stall at 06:37:15 and recorded what the NIC itself was doing:

- `rx_packets` and `tx_packets` both **frozen** (delta 0 over 1 s), while
  `rx_missed_errors` rose by 186 in that second: frames were still arriving at the
  MAC and nothing was draining them. `tx_timeout_count` stayed 0, so the driver's
  own TX-timeout reset path never ran.
- 11-09 18:24:17 looked different at the instant it was caught: TX frozen (delta 0)
  but RX still climbing (38 packets). Same 10 `Hardware Unit Hang` lines either way.
  Whether RX stops a moment after TX is not settled by two samples.

The evidence is in `/root/kernel_witness.log` on pve01 (a persistent copy of the
kernel log; the journal itself is `Storage=volatile` and loses the previous boot)
and `/root/lab_witness.log` on all three nodes.

## Two proven hangs, one presumed

| when | kernel | evidence |
|---|---|---|
| 2026-10-27 09:12 | 7.0.14-25 | `docs/2026-10-27-pve01-nic-stall-and-kernel-revert.md`; same network signature (everything lost at once, carrier up, watchdog reset). **Presumed** the same fault: no kernel log exists, the kernel witness started 10-30 |
| 2026-11-09 18:24 | 7.0.14-26 | **Proven.** 33 `Hardware Unit Hang` lines 18:24–18:25, `watchdog did not stop!` at 18:24:56, node back 18:26:01. pve02/pve03 saw only `pve01=down`. No note about it existed until now |
| 2026-11-15 06:37 | 7.0.14-26 | **Proven.** Above |

Uptime at the hang was about 6 days on 11-09 (pve01 came back from the 11-03
crash at 13:45) and 5.5 days on 11-15, so it is not a fixed uptime. The "-25
kernel is the cause" theory from 10-27 is out: all three nodes run
`7.0.14-26-pve` and only pve01 hangs.

### Most "stall" records are not this

`nic_stall_watch` triggers on **gateway ICMP unreachable** and has written 135
blocks since 10-30. Reading every block's counters: **131 have `rx_packets` and
`tx_packets` still climbing** (hundreds of packets a second, peers on :22 up) --
the gateway stopped answering or the path to it blipped while the NIC was fine.
Two more frozen blocks are link-down events (10-30 13:43 and the 11-03 13:01
all-three-nodes crash). Only 11-09 18:24 and 11-15 06:37 carry the hang signature
(hang lines plus a stopped datapath). 11-08 alone has 54 gateway blips. That is a
separate, recurring upstream problem (router, switch or WAN side), not this fault,
and it is not investigated here.

**An alert must key on the hang lines, never on "gateway unreachable"**; the second
would page about once an hour.

## Why only pve01

All three nodes run the `e1000e` driver at 1000 Mb/s with identical offload and
EEE settings and the same kernel command line. The silicon differs:

| node | NIC |
|---|---|
| pve01 | Intel I219-LM (14) `8086:15f9` rev 11 |
| pve02, pve03 | Intel I219-LM (11) `8086:0d4c` |

That is a correlation across three nodes, not proof. pve02 and pve03 show no
`e1000e` lines in their current-boot kernel logs.

Also checked, all identical across nodes: EEE `enabled - inactive`, private flags
`s0ix-enabled: on` / `disable-k1: off`, no `pcie_aspm` option. `lspci -vv` shows no
`LnkCtl`/ASPM capability on `00:1f.6` (the MAC is PCH-integrated), so ASPM is not a
lever here. `tx_tcp_seg_good` (TSO use) is non-zero on both pve01 and pve02, so TSO
was genuinely in use on both -- which is why "TSO is the trigger" is a hypothesis,
not something the evidence shows.

## Mitigation (applied)

TSO and GSO off on pve01's `nic0`, which is the usual workaround for the `e1000e`
Tx Unit Hang on I219 parts:

- Live: `ethtool -K nic0 tso off gso off`. The witness recorded no carrier drop.
- Persistent: `post-up ethtool -K nic0 tso off gso off` under `iface nic0` in
  `/etc/network/interfaces` on pve01 (backup at
  `/root/interfaces.bak-20261115`).
- In the repo: `proxmox_network_tso_gso_off` in `roles/proxmox_network`, set only
  for pve01 in `inventory/proxmox.yml`. The template renders the same line as the
  hand edit, so the next role run changes nothing and restarts nothing.

- Second line, same place: `post-up ethtool -s nic0 msglvl 0x2087` (adds `tx_err` and
  `hw` to the driver's message level). With `hw` set, e1000e prints its register and
  TX-ring dump when it detects a hang. `proxmox_network_nic_msglvl` in the role.
  Applied live and by hand on pve01, like the TSO line: **never run the
  `proxmox_network` role on a live node**, its handler restarts networking.

Not changed: pve02 and pve03 (no hang on record), GRO, EEE, ASPM.

**Check it worked** — a clean month is the evidence, not a quiet week:

```bash
# on pve01: any hang line at all means the workaround did not hold
grep -a 'Hardware Unit Hang' /root/kernel_witness.log | cut -c1-20 | uniq -c
ethtool -k nic0 | grep -E '^(tcp-segmentation|generic-segmentation)'   # both: off
```

## Why both corosync links died together

`roles/proxmox_network` puts corosync link0 on the LAN (`vmbr0`) and link1 on the
sync VLAN 20 (`vmbr0.20`), both on `nic0`. They share one NIC, so a NIC hang is a
total loss; the second link adds no path diversity. A real second path means a
second physical NIC on a different switch port, which this lab does not have.

## What this is not

- **2026-11-04 06:37** (the `wan`/`sg105e`/`gw` flaps in pve01's witness) is a
  different thing: pve02 and pve03 logged the same probe losses, so it was
  upstream, not pve01's NIC. No `Hardware Unit Hang` exists for that day.
- **pve01's other carrier drops** (kernel log: link down 10-30 13:43:48, 11-03
  13:00:59 and 13:22:43, 11-04 14:49:19) have the opposite signature: the link
  really went down, and there are no hang lines. On 11-04 14:49 all three nodes
  lost carrier within 5 s while the Netgear flapped, so that one was switch-wide
  (see `docs/ipam.md`); 11-03 is the all-three-nodes crash in
  `docs/pve-crash-2026-11-03.md`. 10-30 was not compared with the other nodes.
- Not a kernel panic and not power. A switch or cable fault is unlikely for the
  hangs themselves, since the carrier stayed up and pve02/pve03 saw their own
  links normal.

## Second opinion (Fable, 2026-11-15)

Asked to sanity-check the mitigation and the capture plan with the evidence above.
Its answer, condensed:

- **TSO/GSO off is a reasonable first step, but nothing in the evidence implicates
  TSO.** pve02/pve03 run the same offloads without hanging. Keep it, do **not** stack
  more changes on top yet (that would confound the result), and fix the capture.
- **Why only pve01** is most likely platform: `15f9` is a newer-generation PCH MAC
  than `0d4c`, so a model-specific driver/ME/PHY bug or one bad unit fit equally well.
- **ASPM, EEE, SmartPowerDown, GRO, interrupt throttle, ring size, an out-of-tree
  driver:** not worth touching (EEE is inactive, ASPM does not apply, the rest have
  no evidence behind them).
- **If it hangs again, in this order:** `ethtool -A nic0 rx off tx off`; the
  `disable-k1` private flag (`ethtool --set-priv-flags nic0 disable-k1 on`);
  BIOS/ME update with AMT off; then TX checksum offload off.
- **Proof bar:** hangs are about 6 days apart, so 3-4 hang-free weeks before calling
  it fixed.
- **The HA watchdog is behaving correctly; do not touch it or its timeouts.** An
  in-place reset (`ip link down/up`, or unbind/bind, which also drops nic0 from the
  bridge and re-enables TSO) is HA-safe only if it runs once and early (by about
  15 s), after the capture, and it is unknown whether it would work: the driver
  already resets itself after a 5 s TX timeout, and the unbroken 2 s cadence with
  `tx_timeout_count 0` suggests that path never ran. Rehearse it on a healthy node
  before ever automating it. **Not done.**
- **Place critical guests on pve02/pve03** while pve01 is suspect (see decisions).

## What now watches for it

| layer | what | where |
|---|---|---|
| full kernel log | every line except audit/apparmor, fsynced per line, 4 MiB x2 rotation (was: a grep that kept only the first line of the hang report) | `/root/kernel_witness.log` on all three nodes; `roles/pve_stall_witness` |
| hang-time capture | on the first `Detected Hardware Unit Hang`: `ethtool -d/-S/-k/-a`, `ip -s`, `tc -s`, `/proc/interrupts`, `tx_timeout`, carrier, a pcap, `lspci -vvv`, one pass every 2 s for ~60 s (the watchdog resets at about that point) | `/root/nic-hang/<stamp>/` |
| driver dump | `msglvl 0x2087` so e1000e prints its own register and ring dump | pve01 `post-up` |
| metrics | `pve_nic_hang_last_timestamp_seconds`, `pve_nic_offload_enabled{feature}`, `pve_kernel_witness_active` published once a minute from the witness log | `pve_nic.prom` textfile, Alloy |
| alert, live | `pve_node_fenced` (critical): `pve_ha_state{id="node/..",state=~"fence|gone|unknown"}`, seen by the surviving nodes, fires ~1-2 min into a stall | Grafana, group `pve-platform` |
| alert, cause | `pve_nic_hang_recent` (critical): a hang line in the last 24 h. It can only appear **after** the node is back, because the network is dead during the hang | same |
| alert, drift | `pve_nic_mitigation_missing` (TSO on again on pve01), `pve_kernel_witness_down` | same |

Both critical alerts route to Discord and email. `pve_nic_hang_recent` fired
immediately after deployment, because today's hang is inside its 24 h window; that
was the end-to-end test of the path and it clears itself about 06:38 on 11-16.

Correction to an earlier version of this note: a generic `pve_node_rebooted`
(warning, `changes(node_boot_time_seconds[1h])`) already existed and would have
matched both hangs. Nothing says anyone read it, which is why the 11-09 event had no
note for six days; the new alerts are critical and name the cause.

## Second review (Fable, 2026-11-15 evening) and what testing it showed

Fable's headline inference was that the hangs are **load-triggered by the Saturday off-site
push** (11-15 is the day after a Sat 05:00 run, 11-09 is 61 h after one). It was tested against
VictoriaMetrics' own history of pve01's `nic0` and **rejected**: in the ten minutes before each
hang the NIC was nearly idle, about its baseline.

| hang | TX, last 10 min avg / max | RX, last 10 min avg / max | prior 24 h avg TX |
|---|---|---|---|
| 11-09 18:24 | 2.8 / 7.9 MiB/s | 2.5 / 2.6 MiB/s | 1.7 MiB/s |
| 11-15 06:37 | 1.9 / 3.5 MiB/s | 2.8 / 3.2 MiB/s | 9.3 MiB/s (the day's 400 GiB staging copy ended hours earlier) |

Idle-time failure is the signature of a **link power-state** problem, not of a transmit-path
bug that heavy traffic would provoke. The I219 has a K1 power state it enters when the link is
quiet; `ethtool --show-priv-flags nic0` showed `disable-k1: off` (K1 enabled) on all nodes.
Fable had ranked disabling K1 second, behind TSO, on the premise that nothing pointed at a
cause. This does, so on 2026-11-15 18:30 `disable-k1` was turned on at pve01 as well (live
and in `/etc/network/interfaces`; `proxmox_network_nic_disable_k1`). It re-initialised the
link for about a second: quorum, HA and both corosync links were unaffected.

Two changes are now in effect on pve01, so a hang-free month will not say *which* one fixed
it. That was the argument for waiting; it was judged worth giving up because every hang costs
a node fence and a ~3 minute failover of everything on pve01.

Other Fable points acted on: the capture/witness are unchanged; nothing was done about the
watchdog or in-place reset (still unrehearsed).

## Not established

- **What triggers the hang.** The load theory was tested and rejected (above); K1 is now the leading
  suspect but unproven. TSO off is a mitigation chosen from the pattern. The
  register/ring dump that would show it was discarded on both proven hangs (the old
  witness kept only the first line). The next hang will be the first with the full
  record.
- **Whether RX stops with TX or after it.** One sample each way (see above).
- **Whether the 10-27 stall was the same fault.** No kernel log survives.
- **Whether pve02/pve03 can hang.** No evidence either way beyond "has not".

## Open decisions

- **Guest placement.** pve01 is the node that hangs, yet the 11-15 failback put
  authentik, lan-dns-01, graf-02, lb-02, dns-02, ntp-02 and mail-02 back on it, as
  asked. Every pair still has its twin on another node, so one more hang is survivable;
  the cost is the ~3 minutes of failover per hang. An HA node-affinity rule
  (`pve02,pve03` preferred) would keep them off pve01. Not set.
- **Rehearse the in-place reset** on pve02/pve03 once, during a quiet window, to learn
  whether it recovers a NIC at all. Not done.
- **Untouched on purpose:** `nic_stall_watch` still triggers on gateway ICMP loss;
  its 131 non-hang blocks are noise for this investigation but real data about the
  upstream path.
