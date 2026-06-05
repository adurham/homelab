# Media-Ingest Collector — Authentik OAuth client

The collector authenticates to the gallery ingest API via OAuth2
client_credentials against Authentik.

- **client_id:** `media-ingest-collector`
- **Authentik provider:** "Media Ingest Collector Provider"
- **Authentik application slug:** `media-ingest-collector`
- **Gallery validates** JWTs against:
  - JWKS:   `https://auth.chi.lab.amd-e.com/application/o/media-ingest-collector/jwks/`
  - issuer: `https://auth.chi.lab.amd-e.com/application/o/media-ingest-collector/`
  - audience: `media-ingest-collector`

## History / gotcha (2026-06-05)
During the `tg-* -> media-*` rename, the env/vault/gallery were updated to
client_id `media-ingest-collector`, but the Authentik provider + application
were NOT renamed — they were still `media-ingest-collector`. Result: the collector got
`invalid_client` (400) on every token request, so it could not push captures
or seed folder_meta. The secret matched all along; only the client_id/app-slug
were stale.

Fix applied (via `ak shell` in the authentik-server container): renamed the
provider's `client_id` and the application `slug` to `media-ingest-collector`.
If Authentik is ever rebuilt from blueprints, ensure the OAuth2 provider for the
collector uses client_id/slug `media-ingest-collector`, NOT `media-ingest-collector`.

## Re-login (session revoked / "SESSION NOT AUTHORIZED")
The source session can be re-authorized two ways (run in CT 116):
- Interactive: `files/tg_login.py` (prompts phone/code/2FA on a TTY)
- Assisted:    `files/tg_login_assisted.py` (phone+2FA via env, code via a polled
  file TG_CODE_FILE) — for driving over SSH without a TTY.
Then `systemctl start media-ingest-collector`.
