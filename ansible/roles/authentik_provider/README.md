# roles/authentik_provider

Provisions Authentik OAuth2/OIDC and SAML providers + applications
that map them to backend services (Proxmox, Grafana, Tanium).

## What it provisions

- **Proxmox** — OIDC provider + application; consumed by
  `configure_sso.yml` to wire up `pve-oauth` realm in Proxmox.
- **Grafana** — OAuth2 provider + application; consumed by the
  `[auth.generic_oauth]` block in `grafana.ini` (rendered by
  `roles/grafana/`).
- **Tanium** — SAML provider for Tanium console SSO.

## no_log

POST/PATCH tasks that include `client_secret` in their request bodies
have `no_log: true` so the secret doesn't leak even with `-v` runs.
The `Get Existing Providers (Grafana)` GET also has `no_log: true`
because Authentik returns the existing client_secret in the list
response.

## Vault-sourced secrets

- `grafana_client_secret` — must match the `client_secret` configured
  in grafana.ini.

## Where it's invoked

`manage_authentik.yml`, after `authentik_flow` and `authentik_user_group`
have set up the prerequisite flows and groups.
