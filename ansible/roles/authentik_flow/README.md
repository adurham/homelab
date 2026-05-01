# roles/authentik_flow

Provisions Authentik flows, stages, and bindings via the Authentik REST
API. Idempotent on re-runs — handles the "this resource already exists"
response shape correctly.

## What it provisions

- Recovery flow (password reset) with identification, email, prompt,
  and user-write stages.
- MFA setup flow (TOTP + WebAuthn + backup codes).
- Backup codes flow.
- MFA validation stage on the default authentication flow.
- Invitation/enrollment flow.
- Branding (default brand) and the default-authentication-flow title.

## Conflict-handling pattern

Two patterns appear in the role:

1. **GET-then-conditional-CREATE** (preferred): list-query first, then
   `when: list.results | length == 0` on the POST. No error tolerance
   needed.
2. **POST-then-conflict-tolerant** (for tasks that can't easily list):
   `status_code: [200, 201, 400]` on the POST. Authentik (DRF) returns
   400 with `{"name": ["...already exists."]}` for stage conflicts and
   `{"non_field_errors": ["The fields target, stage, order must make a
   unique set."]}` for binding conflicts. The 400 acceptance keeps
   re-runs clean while still surfacing genuine 5xx as failures.

The conflict shapes are documented in the role's header comment;
they were captured against a live Authentik on 2026-05-01.

## Where it's invoked

`manage_authentik.yml`, alongside `authentik_user_group` and
`authentik_provider`.
