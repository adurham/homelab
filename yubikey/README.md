# YubiKey-backed sudo, SSH and git signing (personal MacBook)

Everything here runs on the MacBook that drives the homelab. The token is the
unattended identity; 1Password is the human fallback. Nothing here gates
privilege on the Linux boxes yet — those are still reached as root over SSH
(see "Gap" at the bottom).

## Components

| Path | What it does |
| --- | --- |
| `pam_yk/pam_yk.c` | PAM module for `sudo`: PC/SC challenge-response against PIV slot 9A, verified against a compiled-in P-256 public key (`PINNED_KEY`). Slot policy is PIN `never` / touch `never`, so it is silent. |
| `pam_yk/install.sh` | Builds with `clang -bundle` (never codesign — AMFI rejects adhoc bundles), refuses to install unless the harness authenticates the card in front of it, installs to `/usr/local/lib/pam/pam_yk.so`, then proves `sudo -k; sudo true`. |
| `pam_yk/yk-sudo-setup.sh` | Writes `/etc/pam.d/sudo_local` (`auth sufficient pam_yk.so`, then `pam_tid.so`) and takes rollback copies in `/var/db/ykrollback/`. |
| `bin/yk-agent-proxy` | One ssh-agent socket (`~/.hermes/run/yk-agent.sock`) that lists the YubiKey ed25519-sk key first and the 1Password RSA second, routing sign requests by key blob. OpenSSH always tries agent keys before on-disk identity files, so this is the only way to get token-first with a same-connection fallback. |
| `bin/yk-git-sign.sh` | `gpg.ssh.program` replacement: token first, 1Password on failure, never an unsigned commit. |
| `launchd/com.adam.yk-agent-proxy.plist` | Runs the proxy at login, keeps it alive, logs to `~/Library/Logs/yk-agent-proxy.log`. |

## Install on a fresh Mac

```
brew install --cask yubikey-manager          # ykman
# 1. sudo gate
cd pam_yk && bash install.sh                  # pam_yk.so + sudo_local + rollback copies
# 2. ssh agent proxy
cp bin/yk-agent-proxy ~/bin/ && chmod +x ~/bin/yk-agent-proxy
cp launchd/com.adam.yk-agent-proxy.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.adam.yk-agent-proxy.plist
# 3. git signing (global: token, fallback 1P)
git config --global user.signingkey ~/.ssh/id_ed25519_sk_yk.pub
git config --global gpg.ssh.program ~/.hermes/yk-git-sign.sh
```

`~/.ssh/config`: `IdentityAgent ~/.hermes/run/yk-agent.sock` (the token is also
named as an `IdentityFile` so it survives the proxy being down), except
`Host github.com`, which is pinned to the 1Password key with
`PubkeyAcceptedAlgorithms rsa-sha2-512,rsa-sha2-256`.

## What the evidence settled

- **GitHub pushes use the gh OAuth token over HTTPS.** GitHub accepts a
  touch-required sk key but goes silent (hangs, no `USERAUTH_FAILURE`) on a
  no-touch-required one, so a silent sk key can never authenticate there.
  Owner decision 2026-10-19: leave it on the gh token.
- **PIV-backed SSH is not viable unattended.** libykcs11 needs a PKCS#11 login
  to enumerate keys, so an agent started by launchd cannot add the card.
- **A blocked PIV PIN does not affect this setup.** Slot 9A's policy does not
  require the PIN, so `pam_yk` keeps authenticating; the PIN is only needed for
  PIV administration.
- Rebuilding `pam_yk.so` after a PIV reset: generate a new 9A key
  (`ykman piv keys generate --algorithm ECCP256 --pin-policy never
  --touch-policy never 9a /tmp/9a.pem`), replace `PINNED_KEY` with the 65-byte
  X9.63 point, then run `install.sh`.

## Gap: the Linux fleet is root over SSH

`ssh root@<box>` gives root with no sudo in the path, so the token is the only
control. Closing that means a non-root login user plus a sudo gate (the
`amd-workstation` pattern: forwarded agent + `pam_ssh_agent_auth`, plain
`sudo`, never `sudo -n`), then `PermitRootLogin no` once proven.
