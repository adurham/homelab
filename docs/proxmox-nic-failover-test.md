# Controlled NIC-failure test on a PVE node — runbook

> **STATUS: HELD (2026-10-27).** The owner chose not to take any further
> service impact right now. Do NOT run this test without an explicit go in
> the session where it is to be executed — it reboots pve01 and forces an
> HA failover round.

**Why:** on 2026-10-27 pve01 lost its whole network path at 09:12:17, stayed alive
for at least ~40 s, then reset itself. The evidence (witness probes all failing at
once while survivors saw only pve01 down, `kernel.panic=0`, 10 s watchdog0,
60 s watchdog-mux) says this was the HA watchdog self-fencing a node that lost the
manager lock. That is inference, not a demonstration. This run proves it, measures
the timings, and tells us whether a repeat needs a second network path.

**Cost:** one pve01 reboot and one HA failover round (~2 min of service churn).
Same blast radius as the 2026-10-27 event, which the cluster handled cleanly.

## Preconditions (all must be true)

- `pvecm status` → Quorate, 3/3; `ha-manager status` → fencing armed, all services started.
- `pvesr status` → no failed jobs; last sync recent.
- No backup job running (check `vzdump` tasks; window outside 02:00-03:30).
- pve01's kernel is the one under test (`uname -r` = 7.0.14-24-pve during the
  observation week), and all three nodes are in kernel parity
  (`scripts/proxmox/kernel-parity.sh`).
- `lab-witness` active on all three, and the deployed script contains the
  `nic0carrier` probe (`grep -c nic0carrier /root/lab_witness.sh` = 1).
- Physical access to the box is available if the reboot does not come back.

## Procedure

1. **Baseline** (from pve03, not pve01):
   ```
   pvecm status | egrep "Nodes|Quorate"
   ha-manager status
   pvesr status
   ```
   Save output. Note which guests run on pve01 (`pct list`, `qm list`).

2. **Arm the watcher** on pve02 and pve03 so the transition is captured live:
   ```
   sudo sh -c 'tail -F /root/lab_witness.log' | tee /tmp/nictest-$(hostname).log
   ```
   (run in a second terminal, or `nohup` it)

3. **Break the link** on pve01 from a delayed unit, so the SSH session survives long
   enough to return:
   ```
   ssh -A amd@192.168.86.11 'sudo systemd-run --on-active=5 --unit=nicfail-$(date +%s) \
       ip link set nic0 down'
   ```
   This is the closest match to the 09:12 failure mode: carrier drops, the box stays
   alive and healthy otherwise.

4. **Watch**, do not intervene. Expected sequence:
   - witness on pve01: `STATE nic0carrier=0`, then every peer target going down;
   - pve02/pve03 witnesses: only `pve01=down`;
   - corosync: pve01 leaves, quorum stays 2/3;
   - HA: `unknown` → `fence` → reboot;
   - reboot: kernel comes back, link up, cluster rejoins within ~2 min.

5. **Recovery check** (same as any node reboot):
   ```
   pvecm status | egrep "Nodes|Quorate"
   ha-manager status          # all services started, fencing armed
   pvesr status               # no failures
   ```
   plus guest counts per node and one Frigate API check.

6. **Record** the measured timings below (link down → last witness line →
   fence → boot → quorate). They are the numbers that matter if this ever happens
   unplanned.

## What the two outcomes mean

- **Carrier goes 0 and the node self-fences:** confirmed. The node's own link died;
  the reboot was the watchdog doing its job. Next step is either a second physical
  path for corosync (not free) or accepting the self-fence as designed behaviour.
- **Carrier stays 1 while all probes die:** the driver/stack wedged with the link up
  (e1000e hang, ME reset). Then the kernel/driver is implicated, and the -24 vs -25
  comparison becomes the deciding experiment.

## Abort criteria

- Quorum drops below 2 (a second node unhealthy) → bring the link back up immediately
  (`ip link set nic0 up` via console or the delayed unit).
- Guests on pve02/pve03 fail to start after failover → restore link, investigate before
  repeating.
- Anything unexpected in ZFS/replication → restore link and stop.

## Results (fill in when run)

| field | value |
|---|---|
| date/time | |
| link down at | |
| last pve01 witness line | |
| pve02/03 saw pve01 down at | |
| HA fence logged at | |
| kernel back at | |
| quorate again at | |
| carrier seen | 0 / 1 |
| notes | |
