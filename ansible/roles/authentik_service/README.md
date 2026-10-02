# Authentik Service Role

## Overview

Deploys Authentik Identity Provider using Docker Compose.

## Variables

This role needs no container password of its own — container provisioning
(and the vaulted root password, passed to `authentik_host` as
`authentik_host_lxc_password`, aliased from `lxc_password`) is handled by
the `authentik_host` role.

Consumed by this role (`defaults/main.yml` + vault):

- `authentik_image` / `authentik_tag`, `authentik_postgres_image` /
  `authentik_postgres_tag`, `authentik_redis_image` / `authentik_redis_tag`
  — image pins (Renovate-tracked).
- `authentik_secret_key`, `authentik_pg_user` / `_db` / `_password`,
  `acme_dedyn_token` — secrets.
- `ip_mail_server` — `extra_hosts` entry for the mail relay.

## Usage

Dependencies: `authentik_host` (Container must exist).
