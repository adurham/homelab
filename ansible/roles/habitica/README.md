# Habitica self-host deployment

Deploys `adurham/habitica-homelab` (fork of `awinterstein/habitica`) as an
LXC container on the Proxmox cluster. The container ingress is
Tailscale-only — there is no LAN HTTPS surface.

For the **code changes** in the fork (Web Push, mobile/PWA fixes, CI),
see [`SELF_HOST.md` in the fork repo](https://github.com/adurham/habitica-homelab/blob/self-host-local/SELF_HOST.md).

## Topology

| | |
| --- | --- |
| LXC | `habitica-01` — VMID `112`, target node `pve03` (**UNVERIFIED** — not present on the live cluster as of 2026-10-02) |
| Private IP | `172.16.0.44` (`ip_habitica` in `group_vars/all/vars.yml`) |
| Public URL | `https://habitica-01.tail19c543.ts.net` (Tailscale Serve) |
| Container image | `ghcr.io/adurham/habitica-server:latest` (built by the fork's `build.yml` GH Action) |
| Database | MongoDB 7 sidecar (`docker.io/mongo:7`), replica set `rs`, volume on LXC local disk |
| HA / replication | Intended: registered in `manage_ha.yml` (VMID 112) — **UNVERIFIED**, current `ha_containers` list has no 112 and no such CT exists on the cluster |

The container binds **only to `127.0.0.1:3000`**. Tailscale Serve on the LXC
terminates HTTPS with a Let's Encrypt cert and proxies to localhost:3000.
No Caddy / nginx in the LXC, no `172.16.0.44:3000` cleartext surface.

Tailscale runs in **userspace-networking mode** (`--tun=userspace-networking`)
because unprivileged LXCs don't have `/dev/net/tun`. Inbound TCP to the
Tailscale interface still works, which is all we need.

## Files

Deployment tooling lives in **this homelab repo** (the fork repo carries only
the app code patches — its own `SELF_HOST.md` states deployment/Ansible/env
wiring lives in the consumer's infra repo):

```
ansible/roles/habitica/
└── README.md                        # this file
    # tasks/create_lxc.yml, tasks/configure.yml and
    # templates/docker-compose.yml.j2 are referenced below but are NOT
    # present in the current tree — UNVERIFIED. Treat the bootstrap flow
    # below as documentation of intent until the role tasks are restored.
```

Secrets (vault-encrypted) referenced by the role:
- `vault_habitica_vapid_public_key`
- `vault_habitica_vapid_private_key`

Generate once with `npx web-push generate-vapid-keys` and commit the
**encrypted** vault file. Rotating the keypair invalidates all existing
Web Push subscriptions (users re-opt-in from settings).

## Running it

> **UNVERIFIED (2026-10-02):** `ansible/deploy_habitica.yml` does **not**
> exist in the current tree, and CT 112 is not present on the cluster
> (`pvesh get /cluster/resources` returns no vmid 112) or in
> `manage_ha.yml`'s `ha_containers` list. The commands below are kept as
> the intended procedure; verify the playbook/role actually exist before
> relying on them.

From the Mac (off-LAN), override `ansible_host` to the Tailscale MagicDNS
name — the LAN jumphost isn't routed to off-LAN clients:

```bash
ansible-playbook -i ansible/inventory/proxmox.yml ansible/deploy_habitica.yml \
  -e ansible_host=habitica-01.tail19c543.ts.net
```

Then pick up HA + replication config:

```bash
ansible-playbook -i ansible/inventory/proxmox.yml ansible/manage_ha.yml
```

## Bootstrap flow

`INVITE_ONLY` defaults to `false` for first-run admin registration.

1. **First apply:** `INVITE_ONLY=false`. Register the admin account — it
   auto-gets admin rights. Do NOT use this account for gameplay.
2. As admin, create a throwaway guild and copy its invite link.
3. **Re-run with `-e habitica_invite_only=true`** to close public registration.
4. Use the invite link in a private window to register the real player account.

## Mobile access

Official Habitica iOS/Android apps are hardcoded to `habitica.com` and do
**not** support a custom server URL. Mobile access for a self-hosted
instance is the Safari PWA — Add to Home Screen from
`https://habitica-01.tail19c543.ts.net`.

Web Push **works** on the installed PWA (iOS 16.4+) via the VAPID path
added in the fork. Toggle it from Settings → Notifications → "Browser
push notifications" on each device.

## Upgrades

The fork's GH Action rebuilds `ghcr.io/adurham/habitica-server:latest` on
every push to `self-host-local`. To deploy a new build, re-run
`deploy_habitica.yml` (see the UNVERIFIED note above — this playbook is
not currently in the tree) — the Ansible role pulls the new image and
`docker compose up -d` picks it up. The nightly `rebase-upstream.yml`
workflow at 02:38 UTC keeps us current with `awinterstein/habitica` →
`HabitRPG/habitica`.
