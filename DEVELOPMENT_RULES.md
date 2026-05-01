# Development Rules

## Git Operations

- When the user has set scope (e.g. "do all 4", "fix X then commit"),
  routine commits at logical task boundaries are fine without re-asking.
  The scope IS the authorization.
- **Always ask before destructive ops**: force-push, `git reset --hard`,
  branch deletion, amending pushed commits, force-overwriting another
  machine's repo state.
- **Always ask before push** when the work crosses a meaningful boundary
  (end of a feature, before stopping for the night). One commit per task
  in the middle of a flow doesn't need confirmation; "we're done with
  this set, push?" does.
- Never skip hooks (`--no-verify`) or bypass signing without an explicit
  ask.
- Pre-commit and ansible-lint must pass before any commit. If they fail,
  fix the underlying issue rather than disabling the check.

## Secrets

- All ansible secrets live in vault: inline `!vault |` blocks in
  `ansible/inventory/group_vars/all.yml`, plus the fully-encrypted
  `ansible/group_vars/all/vault.yml`. Don't introduce new
  `lookup('file', 'credentials/...')` patterns — vault them.
- Never log a decrypted secret. `ansible.log` is disabled for this
  reason; don't re-enable it without a sanitization pipeline.
- Never commit `.vault_pass`, `*.env`, `credentials/*`, or anything
  matching `.gitignore`'s sensitive patterns. Verify with
  `git check-ignore` if unsure.
- When rotating a secret, update vault → run the relevant role → verify
  the live system reflects the new value before considering it done.

## Workflow & cross-machine

- The work MacBook can't reach the homelab cluster directly. SSH and
  ansible go through the personal MacBook (Tailscale 100.66.19.20)
  via the inventory's `private_subnet` group ProxyCommand.
- 1Password git signing on the work MacBook is unreliable. When
  `git commit` fails with "1Password: failed to fill whole buffer",
  fall back to committing on the personal MacBook (rsync the diff +
  commit there + push). Don't bypass signing.
- HA SSH addon needs `ssh -A` agent forwarding from the work MacBook
  to authenticate; the personal MacBook's `id_ansible` is not in HA's
  authorized_keys.

## Style

- Explain what changes are being made before making them, especially
  for cross-cutting refactors.
- Default to small, reviewable commits scoped to one logical change.
- Keep the inventory and roles authoritative — don't make manual
  changes to a CT and forget to backport. If you do something by hand,
  encode it in the role or note it in a follow-up.
