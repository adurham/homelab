# pve03 ZFS writeback deadlock + a duplicate tailscale-gw (2026-10-20 → 21)

Found during the 2026-10-21 morning sweep, 22 hours after it started. Nothing
alerted. Everything is recovered; the two root causes and the monitoring hole
are recorded here.

## Symptom

- `pve03` load average climbing monotonically 1.5 → 81 between 10-20 12:00 and
  10-21 10:30, with CPU 84 % idle and no disk activity.
- `node_procs_blocked = 71` and rising; `ps` showed one `kworker/u64:5+flush-zfs-75`
  plus 9 `systemd-journal` processes, all in `D` state, all belonging to LXC 101.
- `pve_exporter` for pve03 flapping up/down (the only visible monitoring
  symptom — and the ack bot deletes resolve messages, so nothing stuck).

## Root cause

`zpl_write_cache_pages` → `__folio_lock` in the ZFS writeback worker: one page
was locked and never released, so every `fsync`/writeback that touched it
blocked forever. `zpool status` healthy throughout (0 errors, clean scrub
10-15), txgs still closing every ~10 s — a kernel/filesystem deadlock, not
media failure.

What put the page there:

```
2026-10-20.11:26:06  zfs recv -F … nvme-pool/subvol-101-disk-0     (last replication into pve03)
2026-10-20.11:48:29  zfs destroy -r nvme-pool/subvol-101-disk-0    (stale replica removed)
2026-10-20.11:51:27  lxc-start -F -n 101 starts on pve03           (from a STALE config on this node)
2026-10-20.11:52:14  lxc-start -F -n 101 starts on pve01           (HA starts the real container)
2026-10-20.11:56:43  first hung_task report (blocked > 122 s)
2026-10-20.12:02:52  "Future hung task reports are suppressed"
```

HA had failed CT 101 (tailscale-gw) over to pve01 because the pve03 copy was
unhealthy, but the pve03 copy was never stopped — its process tree kept running
outside PVE's control (`pct list` on pve03 did not show 101) and kept writing to
a dataset that had just been destroyed underneath it. That write is the page
that never completed.

The duplicate also carried the live container's identity: same MACs
(`bc:24:11:56:e2:1a` eth0, `bc:24:11:b5:f8:70` eth1, `bc:24:11:89:e4:92` eth2)
and same four addresses (`192.168.86.16`, `172.16.0.1`, `10.99.0.3`,
`100.86.168.35`), with `tailscaled` and `dnsmasq` running inside it. Two bridges
claiming one MAC = traffic for the LAN address, the SDN gateway and the tailnet
identity flipping between nodes. That is what made the `blackbox_amd_workstation`
probe flap from 10-16 onward — it went solid the moment the duplicate died.

## Fix

1. Killed the duplicate's cgroup (`echo 1 > /sys/fs/cgroup/lxc/101/ns/cgroup.kill`),
   then the orphaned `lxc-start` monitor. The live CT 101 on pve01 was never
   touched. Immediately after: `pve_exporter` back to 3/3, amd-workstation probe
   solid, private subnet verified from the Mac.
2. The 10 `D`-state tasks could not be reaped (their page lock is held in the
   kernel), so the node needed a reboot to clear it. Owner approved;
   `systemctl reboot` on pve03 at 10:39:53, shutdown itself took ~5 min (the
   stuck writeback blocks the final sync), back at 10:44:59. Post-reboot:
   0 blocked processes, load normal, pool ONLINE, all 7 guests up, HA unfroze
   ct:100/102/105, DNS + authentik verified from outside.

Blast radius while pve03 was down: authentik (502), dns-01 and ntp-01 frozen by
HA for ~4 minutes.

## Monitoring hole (closed in this repo, not yet applied)

No rule covered "node has unkillable processes". Added `node_procs_blocked_high`
to `ansible/roles/grafana/templates/alerting_rules.yml.j2`
(`node_procs_blocked{instance=~"pve0[123]"} > 20` for 10m). Applying it needs the
Grafana service-account token from the vault.

## Prevention

- PVE will start a container from a stale per-node config even after its storage
  was destroyed. `pct list` is the authority: if `lxc-start -F -n <vmid>` exists
  on a node whose `pct list` does not contain that vmid, it is an orphan — look
  for it after any HA failover involving local ZFS storage.
- Same class as the 2026-09-19 `pmxcfs lost 101.conf` incident: CT 101's config
  has moved between nodes twice now. Its live disk is
  `nvme-data:subvol-101-disk-1`, replicating 101-0 → pve03 and 101-1 → pve02.
