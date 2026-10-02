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
`ip_hermes_gateway`, `ip_vm`, `lb_lan_ingress_ip`, `net_lan_range`,
`net_private_range`, `net_private_gw`.

## Usage

Dependencies: `loadbalancer_host`.
