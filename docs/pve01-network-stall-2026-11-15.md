# pve01 network stall and HA fence — 2026-11-15

Status: **cause not established.** Written from the surviving nodes' logs and pve01's
own witness log; pve01's kernel log for the event is gone (see "Not established").
All times CST.

## Timeline

| time | what |
|---|---|
| 06:36:46 | pve01 witness: last good heartbeat (`HB nic0=up quorate=Yes`) |
| 06:37:05 | corosync on pve02 and pve03: both knet links to host 1 (pve01) down in the same second |
| 06:37:06–06:37:11 | pve01 witness: every probe flips to down within 5 s — pve02, pve03, the SG105E, the gateway, the WAN. No `nic0carrier=0` line, so the carrier did not drop |
| 06:37:12 | pve02/pve03 re-form membership without node 1; quorum 2/3 holds |
| 06:37:22 | HA CRM: pve01 `online` → `unknown` |
| 06:38:12 | HA CRM: pve01 → `fence`; its services go to `fence` |
| 06:38:56 | pve01 witness restarts (`uptime_s=6.7`): the node rebooted |
| 06:38:59–06:39:00 | corosync link up, membership back to 3/3 |
| 06:41:13 | HA recovers the fenced services: `ct:102`→pve03, `ct:130`→pve03, `ct:141`→pve02, `ct:158`→pve02, `ct:170`→pve03, `vm:241`→pve03 |

`ct:170` (frigate) returned to pve01 by itself because of the
`frigate-prefer-pve01` node-affinity rule. Nothing else has a rule that pulls it
back, so the rest stayed where recovery put them — see
`docs/ha-inventory.md` ("Placement drift").

## Same signature as 2026-10-27

`docs/2026-10-27-pve01-nic-stall-and-kernel-revert.md` describes the same pattern:
pve01 loses everything at once, the carrier does not drop, and the HA watchdog
resets it about 110 s later. What differs is the kernel:

- On 10-27 pve01 alone was on 7.0.14-25 and that was the working suspect.
- Today all three nodes report `7.0.14-26-pve`. The parity guard (`scripts/proxmox/kernel-parity.sh`) is doing its job, and the
  stall recurred anyway. That weakens the "-25 is the cause" theory; it does not
  say what the cause is.

pve01's witness also logged a short `wan`/`sg105e`/`gw` flap at **06:37:03–06:37:25
on 2026-11-04**, the same minute of the day as today's event. No cron entry or
systemd unit on pve01 mentions 06:37 (`/etc/cron*`, `/etc/systemd/system`
searched). Whether the 11-04 flap was pve01-only was not checked.

## Both corosync links share the failed path

The 10-27 note said the structural fix for a recurrence is a second corosync link
on a separate path. Both links went down in the same second today, so whatever
they are, they do not fail independently of this. pve01 has one physical NIC
(`nic0`) carrying `vmbr0` and the VLAN interfaces `vmbr0.20` and `vmbr0.21`, and
the inventory puts the sync (`172.20.0.x`) and migrate (`172.21.0.x`) addresses on
VLANs. If the links are VLANs on that one NIC, a NIC stall takes out both. This
is a reading of the config, not something the logs prove.

## Not established

- **Cause.** Driver/NIC hang versus something upstream. The 10-27 write-up used the
  survivors' witness logs to show the switch and gateway stayed up for them; that
  comparison was not repeated for today.
- **Kernel log.** pve01's journal is `Storage=volatile`, 300M
  (`/etc/systemd/journald.conf.d/99-volatile-hdd-wear.conf`, set to spare the boot
  HDD). The previous-boot journal on pve01 ends in October, so nothing from the
  06:37 event survives the reboot. `pstore` and `kernel.panic` were not looked at.
- **Why `ct:100`, `ct:147`, `ct:149`, `ct:157` are off pve01.** They are not in
  today's recovery log.

## Open

- Put the pair members back on pve01 (`ha-manager migrate ct:<id> pve01`), or
  leave them while the cause is unknown. pve01 currently carries no pair member.
- Capture the next event: persistent journald on pve01, or a netconsole/serial
  target, since the witness log shows *that* it stalled but not *why*.
- Decide whether a second NIC on a different switch path is worth buying, per the
  10-27 note's conclusion for a recurrence on an equalised kernel.
