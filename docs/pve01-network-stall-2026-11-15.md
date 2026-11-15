# pve01 network stall and HA fence — 2026-11-09 and 2026-11-15

Status: **cause identified, trigger not proven, mitigation applied 2026-11-15
~11:30 CST.** pve01's `e1000e` NIC driver logs `Detected Hardware Unit Hang` and the
NIC stops passing traffic until the HA watchdog reboots the node. TSO/GSO is now
off on pve01's `nic0`; whether that prevents the hang is unknown until it has gone
a few weeks without one. All times CST.

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

The evidence is in `/root/kernel_witness.log` on pve01 (a persistent copy of the
kernel log; the journal itself is `Storage=volatile` and loses the previous boot)
and `/root/lab_witness.log` on all three nodes.

## It has happened three times

| when | kernel | evidence |
|---|---|---|
| 2026-10-27 09:12 | 7.0.14-25 | `docs/2026-10-27-pve01-nic-stall-and-kernel-revert.md`; same signature. No kernel log exists (the kernel witness started 10-30) |
| 2026-11-09 18:24 | 7.0.14-26 | 33 `Hardware Unit Hang` lines 18:24–18:25, `watchdog: watchdog0: watchdog did not stop!` at 18:24:56, node back 18:26:01. pve02/pve03 saw only `pve01=down`. No note about it existed until now |
| 2026-11-15 06:37 | 7.0.14-26 | above |

Uptime at the hang was about 6 days on 11-09 (pve01 came back from the 11-03
crash at 13:45) and 5.5 days on 11-15, so it is not a fixed uptime. The "-25
kernel is the cause" theory from 10-27 is out: all three nodes run
`7.0.14-26-pve` and only pve01 hangs.

## Why only pve01

All three nodes run the `e1000e` driver at 1000 Mb/s with identical offload and
EEE settings and the same kernel command line. The silicon differs:

| node | NIC |
|---|---|
| pve01 | Intel I219-LM (14) `8086:15f9` rev 11 |
| pve02, pve03 | Intel I219-LM (11) `8086:0d4c` |

That is a correlation across three nodes, not proof. pve02 and pve03 show no
`e1000e` lines in their current-boot kernel logs.

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

## Not established

- **What triggers the hang.** The kernel witness kept only the first line of each
  hang report, not the TDH/TDT and status registers, so the detail that would show
  whether TSO is the trigger was not captured. TSO off is a mitigation chosen from
  the pattern, not a proven fix. If it hangs again with TSO off, capture the whole
  report before anything else.
- **Whether pve02/pve03 can hang.** No evidence either way beyond "has not".

## Follow-ups

- Widen `kernel_witness` on pve01 to keep the lines after
  `Detected Hardware Unit Hang` (the register dump).
- Nothing alerts on this. `Hardware Unit Hang` in the kernel log, or a node
  entering `fence`, should page.
- The HA guests the 11-15 fence displaced were put back on pve01 the same day; see
  `docs/ha-inventory.md`.
