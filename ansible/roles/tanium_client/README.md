# roles/tanium_client

Installs the Tanium client `.deb` package on supported Linux CTs
(`tc-ubuntu22`, `tc-ubuntu24`, `tc-debian11`, `tc-debian12`,
`tc-rocky*`, `tc-alma*`, `tc-rhel*`, `tc-oracle*`, `tc-suse15`). This
is the application-level installer — the underlying CT lifecycle is
handled by `roles/tanium_client_host`.

## What it does

- Looks in `/tmp` for a `taniumclient_*-<distro><major>_amd64.deb`
  matching the target CT's distro and version, falling back to the
  universal package if a distro-specific build isn't present.
- Installs via `apt-get install -f` (deb format) or `dnf install` (rpm)
  to pick up dependencies automatically.
- Restarts `taniumclient` so the bound `ServerNameList` from
  `roles/tanium_client_host`'s ks.dat takes effect.

## Where it's invoked

`deploy_tanium_clients.yml`, after `tanium_client_host` has staged the
matching package into the CT's `/tmp`.
