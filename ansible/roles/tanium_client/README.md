# roles/tanium_client

Installs the Tanium client `.deb` package on supported Linux CTs
(`tc-ubuntu22`, `tc-ubuntu24`, `tc-debian11`, `tc-debian12`,
`tc-rocky*`, `tc-alma*`, `tc-rhel*`, `tc-oracle*`, `tc-suse15`). This
is the application-level installer — the underlying CT lifecycle is
handled by `roles/tanium_client_host`.

## What it does

- Pulls a `tanium-init.dat` (bound `ServerNameList`) from the Tanium
  server's API (`{{ tanium_client_server_url }}/api/v2/keys/315`) and
  installs it at `/opt/Tanium/TaniumClient/tanium-init.dat`.
- Downloads the Linux client bundle from the Tanium server, then finds
  a `taniumclient_*-<distro><major>_amd64.deb` in `/tmp` matching the
  target CT's distro/version, falling back to the `universal` package.
- Installs via `apt` (deb), `dnf` (rpm; a `dnf --nogpgcheck` shell
  override for EL8), or `zypper --no-gpg-checks` (SUSE).
- Restarts `taniumclient` so the just-installed `tanium-init.dat`
  (`ServerNameList`) takes effect.

## Where it's invoked

`deploy_tanium_clients.yml` (tags `install`), against the
`tanium_clients` inventory group, after the `tanium_client_host` play
(tags `provision`) has created the CTs.
