# lan_dns — the house's resolver pair (CT 130 / CT 131)

Provisioned by `deploy_lan_dns.yml` from the `lan_dns` inventory group.

Two roles, deliberately split:

| role | owns |
|---|---|
| `lan_dns_host` | the containers: `pct create`, ansible key, HA resource, `pvesr` job, memory ceiling, onboot |
| `lan_dns` | the resolver: AdGuard Home under `/opt`, its systemd unit, `systemd-resolved` out of the way, `resolv.conf` |

## Why this exists

The 2026-11-09 outage was DNS **and** DHCP living on the single HA Green
appliance with no second copy. These two containers are the answer, but they
were hand-built — and on 2026-11-10 both failed in ways that only exist because
nothing declared them:

* **lan-dns-02 lost its resolver entirely** after a container restart: the
  AdGuard binary and config lived in `/tmp`, which Proxmox clears on boot, so
  the unit's `ConditionFileIsExecutable` skipped the service and `:53` refused
  connections. A second copy of a resolver that cannot survive a restart is not
  a second copy.
* **The house lost DHCP**: `dnsmasq` and `kea-dhcp4-server` were both installed
  and both enabled, raced for `:67` at boot, and neither ended up serving.

## DHCP is NOT here

The owner rejected independent lease databases, so DHCP must be served by both
containers with **shared leases** — Kea hot-standby (`libdhcp_ha`,
`dhcp-socket-type raw`), not dnsmasq. That lives in `roles/lan_dhcp_kea` /
`deploy_lan_dhcp.yml`, owned by a separate lane.

This role used to do dnsmasq DHCP and purge Kea. That combination is what broke
DHCP, so the old block is gated behind `lan_dns_manage_dhcp` (default **false**)
and must stay off once Kea HA is in place. The `assert` at the end of the role
fails loudly if both daemons are ever enabled at once, whichever role did it.

## Rebuild a container from nothing

```bash
# remove it from HA first, or the CRM will fight the destroy
pvesh delete /cluster/ha/resources/ct:131
pvesr delete 131-0 --force 1
pct stop 131 && pct destroy 131 --force

cd ~/repos/homelab/ansible
ansible-playbook deploy_lan_dns.yml -e '{"ansible_ssh_private_key_file":"/home/adam.durham/.ssh/id_ansible"}'
```

That is the tested path: CT 131 was destroyed and rebuilt this way, came back
resolving, and a second run reported `changed=0`.

## Things that bite when rebuilding

* The release tarball unpacks `AdGuardHome/AdGuardHome` — unarchiving into the
  install root leaves a *directory* of that name, the unit's condition fails, and
  the service is skipped without an error anyone sees.
* `AdGuardHome.yaml` must carry `schema_version` (34). Without it AdGuard parses
  with schema 31, where `upstream_dns` is a scalar, rejects the lists, rewrites
  the file as 34 anyway and exits.
* `systemd-resolved` holds `127.0.0.53:53`; AdGuard cannot bind `0.0.0.0:53`
  until it is stopped and disabled.
* The config template is written with `force: false`: it seeds a rebuilt
  container and never touches a live one (which would reset filters and the
  admin session).
* A rebuilt container has a fresh host key — the inventory uses
  `StrictHostKeyChecking=accept-new` for exactly this reason.
