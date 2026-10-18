# Home Assistant security pass — 2026-10-18

State changes made after auditing the live instance (HA Green, core 2026.10.2).

## 1. Login rate limiting

`login_attempts_threshold` was `-1` (disabled) while `ip_ban_enabled` was on, so
brute force was never blocked. Now `5`.

Note on how it was applied: `http/config/configure` accepted the change and
returned `restart: true`, but after a Supervisor restart the value stayed
`pending` instead of promoting to `stable`. Fixed by stopping-and-editing
`/config/.storage/http` (stable block set to 5, pending cleared) and restarting
core through `POST /api/services/homeassistant/restart`. Old file kept at
`/config/.storage/http.bak.20261018`.

## 2. Long-lived access tokens

Two stale tokens existed:

| name   | created    | action  |
|--------|------------|---------|
| Claude | 2026-03-07 | revoked |
| Hermes | 2026-05-10 | revoked |

Replaced by a single token created 2026-10-18 named
`hermes+ansible (2026-10-18 rotation)`, lifespan 3650 days. It is stored in:

- the ansible vault var `homeassistant_token` (`ansible/inventory/group_vars/all.yml`)
- `homeassistant/ha_config.env` (gitignored)

Remaining refresh tokens are per-device sessions (iOS app + browsers), left
alone.

## 3. OIDC / break-glass split

The Authentik OIDC user (`Adam Durham`, id `f16a85006353405ab9d6aff393ec0898`)
was in `system-users`; promoted to `system-admin` so day-to-day admin work can
use the SSO path (and whatever policy/MFA Authentik enforces). The local owner
account stays owner + `system-admin` as break-glass.

## 4. Google Assistant exposure

`homeassistant.expose_new_entities` is `false` for `cloud.google_assistant`, and
402 entities are explicitly exposed. That is already an allow-list model: a new
entity is not exposed until someone flips it on. No change needed.

## 5. Offsite backups

HA keeps ~16 backups locally in `/backup` (automatic full backups are ~1.4 GB
each, plain tar — not encrypted by HA). They are now mirrored offsite:

- script: `~/bin/ha-backup-offsite.sh`
- schedule: launchd `com.adam.ha-backup-offsite`, daily 07:30
- destination: rclone remote `tgcrypt:ha-backups` (crypt over the `tgdrive`
  Google shared drive), newest 3 kept
- restore: needs `rclone.conf` (crypt password) — store a copy of it somewhere
  safe; without it the uploaded blobs cannot be decrypted

## 6. SSO hardening (2026-10-18)

The Authentik OIDC provider for Home Assistant only accepted the LAN IP and
`homeassistant.local` as redirect URIs — logging in through
`https://homeassistant.chi.lab.amd-e.com` or the Nabu Casa remote URL failed
with `Redirect URI Error` (400). All four callbacks are now registered:

- `http://192.168.86.2:8123/auth/oidc/callback`
- `http://homeassistant.local:8123/auth/oidc/callback`
- `https://homeassistant.chi.lab.amd-e.com/auth/oidc/callback`
- `https://<nabu-casa-remote-host>/auth/oidc/callback`

The provider also had **no policy binding**, so SSO was password-only (the
stock `default-authentication-flow` only asks for a second factor when the user
happens to have a device). The shared **Require MFA** expression policy is now
bound to the `home-assistant` application (order 10, not negated). Verified with
Authentik's policy tester: `adam.durham` passes, `test.user` (no devices) is
denied.

Codified in `ansible/roles/authentik_provider/tasks/home_assistant.yml`:
- `ha_oidc_redirect_uris` fact holds all four callbacks (create + update tasks)
- new tasks look up the app id, find the Require MFA policy and bind it if it
  is not already bound

## 7. Still open

- **TOTP: enabled 2026-10-18** on the owner account (`auth_module.totp` holds the
  user's secret; the 1Password item "HA root user" carries the same secret —
  verified by recomputing the 6-digit code for the moment it was added).
- Nabu Casa remote UI is enabled and **Nabu Casa does not offer MFA** (their
  support page: feature "currently not available"). Mitigations: long unique
  password, HA's own TOTP still gates the remote login page, and the cloud
  backup copy is encrypted (`protected: true`).
- HA login page is LAN/tailnet only (`homeassistant.chi.lab.amd-e.com` is not in
  public DNS).
