# hermes_macbook

Keeps the **personal MacBook Pro M4**'s live Hermes checkout
(`~/.hermes/hermes-agent` — what the `~/.local/bin/hermes` shim execs)
current with `adurham/hermes-agent` `main`. The old LXC gateway half of the
fleet (hermes-gw-01, CT 113) was retired on 2026-11-08; the workstation now
runs the gateway natively, so this role only manages the MacBook install.

## Run

From the homelab `ansible/` directory:

    ansible-playbook update_hermes_macbook.yml

Via the 1Password-bridge wrappers (secrets never touch disk):

    ansible-playbook update_hermes_macbook.yml

One-shot without the wrapper (secrets on tmpfs, shredded after):

    ansible-playbook update_hermes_macbook.yml \
      -e ansible_ssh_private_key_file=/dev/shm/ans-keys/id_ansible \
      --vault-password-file=/dev/shm/ans-keys/vault-pass

Connection details (Tailscale netcat transport, fleet `id_ansible` key) live
in `inventory/group_vars/personal_macbook.yml`.

## What this role does NOT manage

- `~/.hermes/config.yaml` on the MacBook — a hand-maintained copy; routing is
  synced separately (`scripts/hermes_config_sync.py`), and per the routing
  distribution rules a whole-section sync must never be applied blindly (the
  MacBook can drift ahead of the repo).
- The `~/repos/hermes-agent` dev clone — separate workspace, untouched.
- No services to restart: the MacBook runs hermes interactively; new
  processes pick up the pulled code on their next launch.
