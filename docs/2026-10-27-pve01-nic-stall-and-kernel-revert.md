# pve01 NIC stall and kernel revert — 2026-10-27

## What happened

At **09:12:17 CDT** pve01 lost all network connectivity. The node stayed alive
locally for at least another 40 seconds, then Proxmox's HA watchdog reset it
(by design: a node that cannot keep the manager lock must not keep running
guests). It booted again at 09:14:02 and HA recovered eight containers plus one
VM onto pve03 and frigate onto pve02.

This was **not** a crash and **not** a kernel panic.

## Evidence

- pve01's own 1-second witness (`/root/lab_witness.log`, `sync -f`'d per line)
  said `HB nic0=up quorate=Yes` at 09:12:02, then at 09:12:18-23 flipped
  **every** probe — pve02, pve03, the SG105E switch, the gateway and the WAN —
  to down within five seconds. Its next heartbeat never happened.
- pve02 and pve03 witnesses recorded exactly one transition: `pve01=down`
  (09:12:17-19). The switch, gateway and WAN stayed up for them.
- `sysctl kernel.panic = 0` on pve01, and no pstore record (`dump-type0` count
  0): a real panic would have hung the box until someone touched it. It came
  back on its own ~1 minute later — the watchdog path.
- watchdog0 = Software Watchdog, timeout 10s; watchdog-mux client timeout 60s.
  Network loss 09:12:17 → reset ≈09:13:30 → POST → kernel 09:14:06. Fits.
- Ruled out: power (UPS on line throughout, 0s on battery, input steady at
  120-121 V), memory (102 GB free), disk (idle, SMART pass, 0 media errors),
  thermal/MCE (no records), split-brain (survivors kept quorum 2/3).

## The one unique variable: the kernel

pve01 was the only node running **7.0.14-25**. It booted that kernel for the
first time at 00:21 (after the planned rolling reboot) and lost its NIC 8h51m
later. pve02 and pve03 run **7.0.14-24** on the same e1000e NIC family and were
unaffected.

Why the split: on 2026-10-19 a rolling `dist-upgrade` ran on all three nodes
minutes apart — pve01 14:56:20, pve02 14:58:31, pve03 15:06:53 — **without
refreshing the package lists on each node first**. pve01's index knew about
-25; pve02/pve03 were still on an older index and installed -24. Same command,
three nodes, two kernels.

## Action taken (2026-10-27 ~11:16 CDT)

- pve01 downgraded to `proxmox-kernel-7.0.14-24-pve` (meta package + signed
  kernel installed, -25 package purged so GRUB's first entry is -24), then
  rebooted. Boot entry verified before the reboot; -15 remains as a fallback.
- All three nodes now run and have installed **7.0.14-24**, with identical
  `/boot` kernel sets: 7.0.0-3, 7.0.14-15, 7.0.14-24, 7.0.2-6, 7.0.2-7.
- Cluster verified after the reboot: quorate 3/3, all HA services started,
  replication OK, pve01's guests back up.

## Guard added

`scripts/proxmox/kernel-parity.sh` — refreshes the apt indexes on every PVE
node and compares running kernel, installed meta version and upgrade candidate.
Exits non-zero on drift. **Run it before any rolling upgrade**, then confirm all
three see the same candidate before starting.

## Observation window

One week, until **2026-11-03**. What to check:

1. `scripts/proxmox/kernel-parity.sh` — all three still on -24.
2. `/root/lab_witness.log` on all three for `STATE nic0carrier=` lines (added
   2026-10-27): a carrier drop is logged separately from the probe set dying,
   which is the link-down vs stack-hang discriminator this event could not answer.
3. If pve01 stays up for a week on -24 with nothing else changed, -25 is
   implicated. The repo already carries **7.0.14-26** as the candidate on all
   three nodes; the next move would be a guarded rolling upgrade of all three
   together to -26, in the order pve03 → pve01 → pve02 (see the cluster's
   rolling-reboot rule), never one node alone.

Proving the mechanism (link down vs driver hang) needs a deliberate one-node test:
see `docs/proxmox-nic-failover-test.md` for the runbook, preconditions and the
timings to record. Do not run it blind.

Structural note: a single-NIC HA node self-fences on any NIC stall. If this
recurs on a node after the kernel is equalised, the fix is a second corosync
link on a separate path, not another post-mortem.
