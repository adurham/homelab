# roles/mail_forwarder

Postfix relay on mail-01 that forwards alert email through iCloud SMTP
with SASL auth. The receive-side for Grafana's email contact point
fallback when the Home Assistant webhook is unavailable.

## What it does

- apt-installs `postfix` + `libsasl2-modules`.
- Templates `main.cf`, `sasl_passwd` (SASL credentials for
  `smtp.mail.me.com:587`), sender canonical map, header checks,
  virtual aliases.
- Restricts which CTs are allowed to relay via
  `mynetworks` in main.cf (currently authentik, pve nodes, lb-01,
  graf-01).

## Why no DKIM / SPF / DMARC on our side

Postfix here is a *relay* — outbound mail authenticates to iCloud SMTP
via SASL, then iCloud signs with its own DKIM and is the SPF source.
DMARC for `icloud.com` is published by Apple. The sender canonical map
rewrites our headers to `amdnative@icloud.com` (the SASL user), which
iCloud accepts.

## Vault-sourced secrets

- `icloud_sasl_password` — populates `/etc/postfix/sasl_passwd`.

## Where it's invoked

`deploy_mail.yml`. The role has a sister role `mail_host` that handles
CT provisioning.
