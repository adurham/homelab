# Fleet patch run — 2026-10-27

## What was patched

All 13 service containers, in blast-radius order (least critical first). PVE nodes
were deliberately NOT touched: they run `roles/pve_unattended_upgrades` (security
only, kernel/cluster packages blacklisted) and their kernels are being held at
7.0.14-24 for the observation week — see
`docs/2026-10-27-pve01-nic-stall-and-kernel-revert.md`.

| host | packages | result |
|---|---|---|
| ntp-01 | 4 | chrony active, synced |
| media-ingest-01 | 4 | collector active, 0 restarts |
| proxy-01 | 10 | squid active, config parses |
| lb-01 | 4 | nginx active, `nginx -t` OK |
| mail-01 | 9 | postfix active |
| tg-harvester-01 (CT 115) | 6 | 7 gallery units running |
| authentik | 21 | 4 docker containers healthy, `/-/health/live/` 200 |
| frigate-01 | 7 | container healthy, API 0.17.2 |
| dns-01 | 5 | resolving from localhost |
| adblock-proxy-01 | **77** | mitmproxy + alloy + adblock-proxy active |
| tailscale-gw | 5 | tailscaled active, private subnet still reachable |
| graf-01 | 4 | grafana active, `/api/health` 200 |
| vm-01 | 0 | nothing pending |

Post-run sweep: every container reports `pending=0`, `reboot-required` absent,
and 0 failed units. Fleet probes: all up except the two Tanium standby boxes
(`ts-02`, `tms-02`) which fail by design when their peers are idle.

## The adblock outlier

adblock-proxy-01 had **77** pending packages because it had no
`unattended-upgrades` at all — the package was never installed and neither
`20auto-upgrades` nor the service existed. It was simply never included in a
`deploy_unattended_upgrades.yml` run. Fixed by running that playbook against it:

```
ansible-playbook -i inventory/proxmox.yml deploy_unattended_upgrades.yml --limit adblock-proxy-01
```

Applied (3 changes) and verified idempotent (`--check` → 0 changed).

## Rollback

A ZFS snapshot named `pre-patch-20261027` was taken on every CT before patching:

```
pct rollback <vmid> pre-patch-20261027      # from the node hosting the CT
pct delsnapshot <vmid> pre-patch-20261027   # once the run looks clean (after ~48h)
```

## Lesson worth keeping

authentik and frigate run their apps in **docker**, not as systemd units.
Verifying a patch run with `systemctl is-active <app>` reports "inactive" and
looks like a failed service when nothing is wrong — check `docker ps` / the app's
own HTTP endpoint on those hosts instead.
