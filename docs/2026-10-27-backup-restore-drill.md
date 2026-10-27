# Backup restore drill — 2026-10-27

**Question:** the nightly vzdump jobs have been green since 2026-09-10, but no
archive had ever been restored. Green logs only prove vzdump ran; they do not prove
the archive boots.

## What was checked

- Storage: `/nvme-pool/vzdump-backups` on pve01, 92 archives, 98 GB used of 351 GB.
- Three jobs (02:00 / 02:30 / 03:00) cover all 16 guests, `keep-daily=3`,
  `keep-weekly=2`; oldest archive on disk was 2026-10-25.
- Newest archive of three different guests: `zstd -dc … | tar -tf -` lists the VMA
  payload (`./etc/vzdump/pct.conf`, `./etc/vzdump/pct.fw`, …) and the matching
  `.log` files contain zero errors.

## The drill

Restored the newest adblock-proxy-01 archive (CT 118, 771 MB compressed,
2026-10-27 02:10) to a throwaway VMID on pve01:

```
pct restore 999 /nvme-pool/vzdump-backups/dump/vzdump-lxc-118-2026_10_27-02_10_53.tar.zst \
    --storage local-lvm --unique 1
sed -i '/^net[01]:/d' /etc/pve/lxc/999.conf    # strip both NICs -> no IP conflict
pct start 999
pct exec 999 -- systemctl is-system-running
pct exec 999 -- systemctl list-units --state=running
```

Result: restore took **12 s** (2.2 GiB read at 528 MiB/s). With no network at all,
systemd reported `running` (not degraded), and `adblock-proxy.service`,
`adblock-proxy-transparent.service` and `alloy.service` came up on their own.
`/opt/adguard-log-shipper/` and `/etc/adguard-log-shipper/` were intact, hostname
correct. Torn down with `pct stop 999 && pct destroy 999 --purge`; no leftover LV.

## Notes

- Always delete `net*:` from the restored config before starting. A restore keeps
  the original IPs, so an untouched copy of a live guest **will** fight it for the
  address.
- `--unique 1` gives fresh MACs but does not remove the static IP.
- `--storage local-lvm` was used because `vzdump-nvme` is a backup-only directory
  storage; any container-capable storage with room works.
- Restore cost is small: under a minute and ~2.3 GB for a 771 MB archive, so this is
  cheap enough to repeat quarterly — and after any change to the backup jobs.

## Follow-up

Repeat the drill for one *VM* (qemu), not just an LXC — the VM path uses a different
restore code path and has not been exercised. That needs a window because a VM
restore allocates more space and takes longer.
