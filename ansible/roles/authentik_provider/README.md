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
- **Hermes Dashboard** (tasks/hermes.yml) — public PKCE OIDC provider +
  application, consumed directly by Hermes's own bundled
  `dashboard_auth/self_hosted` plugin (native OIDC login, NOT a
  forward-auth wrapper — same category as Grafana above). Gates the
  browser/Desktop GUI leg of the always-on `hermes serve` backend on
  hermes-gw-01.
- **Hermes API** (tasks/hermes.yml) — forward_single proxy provider
  (same shape as VictoriaMetrics/TG Gallery) with
  `intercept_header_auth: true`, used for OAuth2 M2M
  (`client_credentials`) Bearer-JWT auth instead of a browser login.
  Gates the CLI leg (`hermes submit` / api_server's `/v1/runs`) via
  nginx `auth_request` on lb-01; the validated request is then
  forwarded to api_server with its own separate `API_SERVER_KEY`
  bearer token as a second, independent gate. NO group-policy binding
  on this application (unlike Hermes Dashboard above) — the M2M grant's
  auto-generated service account isn't a member of any human group, so
  a group binding here always 400s with "User not authenticated for
  application". Access control is "possession of the client_secret",
  same as the Media Ingest Collector M2M provider above.

## no_log

POST/PATCH tasks that include `client_secret` in their request bodies
have `no_log: true` so the secret doesn't leak even with `-v` runs.
The `Get Existing Providers (Grafana)` GET also has `no_log: true`
because Authentik returns the existing client_secret in the list
response.

## Vault-sourced secrets

- `grafana_client_secret` — must match the `client_secret` configured
  in grafana.ini.
- `vault_hermes_gw_api_m2m_client_secret` — the Hermes API M2M proxy
  provider's client_secret. Pinned via `ak shell` post-create because
  the Proxy Provider API silently drops `client_secret` on write (see
  the gotcha note in tasks/hermes.yml). CLI clients present this value
  in a `client_credentials` grant to `/application/o/token/` to obtain
  a Bearer JWT for `hermes-api.chi.lab.amd-e.com`.

## Where it's invoked

`manage_authentik.yml`, after `authentik_flow` and `authentik_user_group`
have set up the prerequisite flows and groups.
