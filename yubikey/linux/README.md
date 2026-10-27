# Token-gated sudo on the Linux fleet

The containers used to be `ssh root@host` with the YubiKey (or the 1Password
RSA) in root's `authorized_keys`, so possession of either key WAS root. They now
follow the MacBook's model: log in as a normal user, escalate with sudo, and the
sudo prompt is answered by a signature from the forwarded agent — token first,
password as the human fallback. Root SSH is off.

## Why not the Debian module

`libpam-ssh-agent-auth` (upstream 0.10.4, 2019) vendors OpenSSH code from before
8.2, so it cannot parse `sk-ssh-ed25519@openssh.com` at all. With the token key
first in the agent list it either skips it or stops enumerating, and the gate
silently degrades to "the 1Password key is root". Dead end.

`pam-ssh-agent` (nresare, Rust, ssh-key crate) verifies sk signatures including
the flags byte. That is what runs here.

## What is installed on each host

- `/lib/x86_64-linux-gnu/security/pam_ssh_agent.so` — built from
  https://github.com/nresare/pam-ssh-agent at 6158b51 (`cargo build --release`,
  needs rustup, not the distro's 1.75).
- `/etc/security/sudo_keys/amd` — the TOKEN key only, root:root 0644. Never a
  user-writable path: that would be self-escalation.
- `/etc/sudoers.d/10-agent` — `Defaults env_keep += "SSH_AUTH_SOCK"` and
  `%sudo ALL=(ALL:ALL) ALL`. No NOPASSWD anywhere.
- `/etc/pam.d/sudo` — see `pam.d-sudo`: `sufficient pam_ssh_agent` first, then
  the normal password stack. No `pam_deny`, so no lockouts.
- `/home/amd/.ssh/authorized_keys` — token + 1Password + the ansible key, so
  login works with and without the token.
- `/etc/ssh/sshd_config.d/00-no-root.conf` — `PermitRootLogin no`. Named 00- so
  it wins over a distro `99-harden.conf` (first obtained wins).
- `/root/.ssh/authorized_keys` — emptied; copy kept at
  `/root/authorized_keys.bak-<date>`.

## Rollout

`rollout.sh` is the idempotent per-host step (run as root). Default run = phase 1:
module, `amd`, login keys, token-only sudo key file, PAM stack, amd's password
locked. Root's keys and sshd are untouched — that is phase 2 (`--finish`), taken
only after `ssh -A amd@<host> 'sudo id'` has returned root from a fresh login.

Phase 2 also inserts `Include /etc/ssh/sshd_config.d/*.conf` when the distro's
`sshd_config` has no such line. **Some containers built from Ubuntu images ship
without it** (adblock-proxy-01 had none), so a drop-in there is silently ignored
and `sshd -T` still reports `passwordauthentication yes`. Always confirm with
`sshd -T` after writing the drop-ins; never assume the file was read.

`--finish` empties `/root/.ssh/authorized_keys` (backup at
`/root/authorized_keys.bak-<date>`), matching the rest of the fleet.

### Completion ledger

- 2026-10-19 — 12 containers + 3 PVE nodes.
- 2026-10-27 — **adblock-proxy-01** (the 13th) finished. It had been added to
  `yd_gated_hosts` on 10-19 but the conversion never landed: no `amd` user, no
  PAM module, `PasswordAuthentication yes`, and root key-only with the ansible
  key. Rolled out phase 1 (module copied from proxy-01, same sha256
  `dc87d9dfdabbff7013ae2cb397c7a6ceb0e6bdeeae3cd57fed5276079c5f04a9`), proved
  `ssh -A amd@… 'sudo id'`, then phase 2. Verified: amd key login OK, sudo via
  the token OK, root SSH denied, password auth off, `sshd -T` clean.

## Ansible

`inventory/group_vars/all.yml` maps `yd_gated_hosts` to `ansible_user: amd` +
`ansible_become: true` (the file outranks inventory-file group vars).
`ansible.cfg` adds `-o ForwardAgent=yes` to `ssh_args` so sudo can reach the
agent through the persistent master.

Two traps:

- sudo 1.9.13+ appends `-n` to the become command when no become password is
  set, and on those builds the module does not satisfy `-n`. Setting
  `ansible_become_password` makes ansible drop `-n`; the value is never used
  because pam_ssh_agent authenticates first.
- Hosts that use ssh socket activation (`ssh.socket`, no `ssh.service`) need no
  reload: each connection starts a fresh sshd and reads the new config.

## PVE nodes — converted 2026-10-19

The three Proxmox nodes follow the same model, with one cluster-safe difference:

```
# /etc/ssh/sshd_config.d/00-no-root.conf on pve01-03
PermitRootLogin no
Match Address 192.168.86.11,192.168.86.12,192.168.86.13
    PermitRootLogin prohibit-password
```

The cluster's corosync ring0 and pvecm/migration SSH both run over the node LAN
addresses, so root@peer keeps working while root from anywhere else is refused.
`/root/.ssh/authorized_keys` on these nodes is a plain per-node file (not the
`/etc/pve/priv/` symlink some PVE versions use) and was reduced to the three
inter-node keys only; the personal keys now live in `/home/amd/.ssh/`.

Peer known_hosts (fixed 2026-10-19, pre-existing gap): pve02 and pve03 had no
known_hosts entries for their peers, so `ssh root@pve03` *from* pve02 hit "Host
key verification failed" even though root auth was fine. Seeded with
`ssh-keyscan -t ed25519,rsa,ecdsa pve01 pve02 pve03 <the three node IPs>` run as
root on each node (backups: `/root/.ssh/known_hosts.bak-*`). All six inter-node
directions now resolve; `pvecm status` stays quorate.
