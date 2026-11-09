# Loadbalancer Service Role

## Overview

Deploys Nginx Reverse Proxy with automated ACME (Let's Encrypt) certificate management.

## Variables

Set as play vars by `deploy_loadbalancer.yml` /
`deploy_loadbalancer_service_only.yml`:

- `acme_dedyn_token_proxmox`: Token for deSEC DNS API (vaulted; the play
  sets it from `vault_desec_token_proxmox`).
- `noip_username` / `noip_password` / `noip_hostname`: No-IP DDNS creds
  for the `ddclient` task.

Referenced from `group_vars/all/vars.yml` (not role defaults):
`ip_authentik`, `ip_grafana`, `ip_homeassistant`, `ip_media_gallery`,
`ip_vm`, `lb_lan_ingress_ip`, `net_lan_range`,
`net_private_range`, `net_private_gw`.

## Usage

Dependencies: `loadbalancer_host`.

## Operational gotchas (learned the hard way)

**`/etc/nginx/sites-enabled/proxmox` must be a SYMLINK to
`/etc/nginx/sites-available/proxmox`.** The role ends with
`Enable Nginx Site` (`state=link`), which refuses to clobber a regular file
("refusing to convert from file to symlink"). On lb-01 the path had drifted to
a regular file, so that task failed EVERY run — and because the validate +
`Restart Nginx` handlers only flush at the end of the play, **the new config
was written to sites-available but never validated or reloaded**. Symptom:
vhost changes deploy "successfully" and nothing changes in production.
Fix (done 2026-11-05, drift backed up as `proxmox.regular-file-bak.*`):

```bash
ln -sf /etc/nginx/sites-available/proxmox /etc/nginx/sites-enabled/proxmox
nginx -t && systemctl reload nginx
```

**`listen` options must match across vhosts for the same address:port.**
Adding `fastopen=3` to a second `listen 443` block fails `nginx -t` with
`[emerg] duplicate listen options for 0.0.0.0:443` — the first listener (the
catch-all `default_server`) defines the option set. Copy an existing TLS block
verbatim rather than from memory.

**Trailing ddclient task fails with "Incorrect sudo password"** on lb-01
(`Configure DDNS (No-IP)` → `service` module). Everything before it — including
the nginx deploy — succeeds, so it is a cosmetic failure *only* as long as the
validate/reload handlers are not behind it. They are removed from the failure
path by the dedicated validate+reload step above; investigate the sudo policy
for that module's invocation shape when convenient.
