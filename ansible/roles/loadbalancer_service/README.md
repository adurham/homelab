# Loadbalancer Service Role

## Overview

Deploys Nginx Reverse Proxy with automated ACME (Let's Encrypt) certificate management.

## Variables

- `acme_dedyn_token_proxmox`: Token for deSEC DNS API (vaulted).
- `ip_loadbalancer`: Static IP address.

## Usage

Dependencies: `loadbalancer_host`.
