# pve nodes: recurring silent stalls and self-fences — root cause and fix

**Resolved 2026-10-30.** pve01 and pve02 (and rarely pve03) had been going silent
for seconds-to-minutes several times a day. The HA manager then fenced the node
(~60 s lease) and the node reset itself (~110-130 s), taking its guests with it.

## Symptom, as measured

- Traffic to and from the victim stops **in both directions** while its link stays
  up: `carrier=1` throughout, zero `carrier_down_changes`, zero CRC/error counters
  on the switch port, no kernel messages at all.
- The victim's own journal shows nothing for the window — but its journal is
  volatile (RAM-only) on all three nodes, so **a gap proves neither a freeze nor a
  network fault**. Treat any "it froze" conclusion drawn from a log gap as unfounded.
- A real switch reboot looks completely different: the 2026-10-30 13:43:54-13:44:34
  power cycle dropped `carrier` to 0 on all three nodes. These stalls never do.

## Ruled out by measurement (not by argument)

| Suspect | Evidence against |
| :--- | :--- |
| Power / UPS | UPS metrics steady through every stall; no carrier event |
| Load | pve03 carries the most traffic and stalls least |
| Thermal | 61-73 °C at the stall moments, no spike, no fan anomaly worth the name |
| L2 loops | Zero frames with a node's own MAC as source on any node |
| Switch features | All 8 ports 1000M, no rate limits, loop prevention OFF, power saving OFF, storm/broadcast filtering OFF, IGMP/NSDP on, **zero CRC on every port** |
| NIC driver / config | pve02 and pve03 are identical twins (model, BIOS, NIC rev, kernel) and only pve02 stalls; pve01 is a different model and also stalls |
| Disks as the cause | pve02's SATA boot disk *is* marginal (1,097 End-to-End errors) but pve01's is clean and freezes identically |

## The evidence that cracked it

pve02's **firmware pstore** (`/var/lib/systemd/pstore/`) held two archived crash
records from its 2026-10-26 reboot. The newest chunk in them:

```
Oops: general protection fault, probably for non-canonical address 0x2000000000018
CPU: 8 UID: 0 PID: 653 Comm: arc_evict Tainted: P O 7.0.14-24-pve
RIP: arc_evictable_space_decrement+0xf2/0x190 [zfs]
Call Trace: arc_change_state -> arc_evict_state_impl -> arc_evict_state
            -> arc_evict_cb -> zthr_procedure
```

ZFS's ARC eviction path walking a corrupted buffer chain. Corruption there wedges
I/O and the network together, which is why the node looks like it "lost the
network" when it in fact fell over.

## Root cause

**PVE bug 8178** — a race in ZFS 2.4.4-pve1's ARC during `pvesr` replication. The
reporter's own summary of the failure mode: *"a silently frozen node, not a
reboot."* This cluster replicates every 20 minutes on all three nodes, sending and
receiving, i.e. exactly the exposed configuration. (Their repro used encrypted
zvols; ours are unencrypted and our recorded crash is in a neighbouring ARC
function — same class, same trigger profile.)

## Fix applied 2026-10-30

`proxmox-kernel-7.0` **7.0.14-26** (cherry-picks upstream `216de07` + `b0fff48`,
openzfs #19243). Rolling upgrade, pve02 → pve01 → pve03, each installed, hold
restored (`apt-mark hold proxmox-kernel-7.0`; the upgrade releases it), cleanly
rebooted, and verified: `uname -r` = `7.0.14-26-pve`, quorate, HA LRM active, zero
failed units. Note the kernel packages are held deliberately — use
`--allow-change-held-packages` and re-hold afterwards.

## Instrumentation armed at the same time

`/etc/sysctl.d/99-crash-capture.conf` (also in the `proxmox_common` role):

```
kernel.panic_on_oops = 1      # an Oops panics -> the record reaches efi_pstore
kernel.softlockup_panic = 1
kernel.hardlockup_panic = 1
kernel.panic = 20             # reboot 20 s after a panic (default 0 = hang forever)
```

Before this, a fault produced no logs and a ~2 minute hang. Now it produces a
pstore record and a 20-second recovery.

## Dead ends, recorded so nobody re-derives them

- **netconsole cannot work here.** `netpoll` refuses a bridge slave (`nic0 is a
  slave device, aborting`) and refuses devices without polling
  (`veth170i0 doesn't support polling`); every L3 interface on these nodes is a
  bridge over the single physical NIC. Verified live 2026-10-30; everything was
  removed again afterwards (module unloaded, receiver deleted).
- **No ERST** in the ACPI tables, so efi_pstore is the only firmware crash store.
- The nodes' journals are volatile — plan evidence around off-box witnesses
  (`lab_witness`, `mac-flow-witness`, `nic-stall-watch`, `kernel-witness`), and
  remember the fleet's own SSH churn (`Connection closed by <peer-ip>`) is a free
  per-second liveness witness readable retroactively from Loki.

## Repaired during the upgrade (fallout from the fences, not the upgrade)

- **ct:107** (`graf-01`): refused to start with `CT is locked (snapshot)` — a stale
  lock from a snapshot interrupted by a fence. `pct unlock 107`, then
  disable/re-enable in HA (PVE's documented ERROR RECOVERY path).
- **ct:105** (`ntp-01`): its rootfs is on pve03's local pool, but a fence had
  relocated the HA service to pve02, where the dataset does not exist. Parked HA,
  moved `/etc/pve/nodes/pve02/lxc/105.conf` back to `pve03`, re-enabled — running
  again on pve03.

## Open item for the owner

**ct:105 and ct:118 are the only HA-managed guests with no `pvesr` replication
job.** Their storage therefore exists on one node only, so any future relocation
lands them on a node without their disk — exactly how ct:105 broke. Either add
replication jobs for those two, or pin them to their node with an HA node-affinity
rule. (All other HA guests are replicated and relocate safely.)
