# BWT Lab — Phase 2: TanOS appliance provisioning

The hard part of this build. TanOS appliances don't play nicely with
standard automation tools (no cloud-init, no DHCP support out of the
box on the BWT-ready image, qemu-guest-agent is locked down too tight to
inject SSH keys). The solution: drive the VM's keyboard at the
hypervisor level via QMP `send-key`.

## Why this is hard

The TanOS appliance image enforces multiple security postures that block
the usual provisioning channels:

| Channel | Status on fresh TanOS |
|---|---|
| cloud-init / NoCloud / OEMDRV | Not supported. TanOS doesn't run cloud-init. |
| DHCP on first boot | Not supported. The initial-config wizard requires a STATIC IPv4 (rejected DHCP input). |
| qemu-guest-agent `guest-exec` | **Disabled.** STIG-hardened: returns `Command guest-exec has been disabled`. |
| qemu-guest-agent file write | **Permission denied.** qga runs as unprivileged `qemu-ga` user; can't even write to `/home/tandev/.ssh/`. |
| SSH password auth (sshpass) | **Doesn't work.** sshd advertises only `publickey,keyboard-interactive`; sshpass can't drive the keyboard-interactive PAM challenge cleanly. |
| Default `tandev` shell user | **Doesn't exist post-init.** The DEV-image kickstart creates `tandev` but a finished/initial-config-complete TanOS only has `tanadmin` (menu/CLI) and `tancopy` (SFTP). |
| Serial console (`qm set --serial0 socket`) | **Silent.** TanOS grub.cfg doesn't add `console=ttyS0`. socat to the serial socket gets zero output. |

So we're left with the VGA console + PS/2 keyboard. QEMU's QMP
`send-key` command injects keystrokes at that layer, regardless of the
guest OS's console config. Paired with `screendump` (saves the
framebuffer as a PPM) and an LLM with vision, you have a closed-loop
keyboard driver.

## The QMP keystroke driver

`scripts/proxmox/qmp_keystroke.py` — a small Python that talks to the
QMP UNIX socket at `/var/run/qemu-server/<vmid>.qmp`. Supports:

- `type "text\n"` — types a literal string (newline = Enter, tab = Tab)
- `key <qcode>` — single QEMU keycode (`ret`, `spc`, `backspace`, etc.)
- `combo <qcode>+<qcode>+...` — modifier+key combos (`shift+a`)
- `sleep <seconds>` — pause
- `screen /tmp/out.ppm` — screendump for verification

Lives in `scripts/proxmox/` because it's a Proxmox-host helper, not a
Tanium-side script. Ansible roles copy it to `/tmp/qmp_send.py` on the
target pve node before running.

### The verification loop

After each keystroke sequence, screendump + `sips -s format png` (macOS)
or `convert` (Linux) + `vision_analyze` to confirm the screen state.
This pattern is what makes the automation reliable — instead of guessing
whether a sequence worked, we verify.

## TanOS DEV-image default credentials

Extracted from the install ISO's kickstart (`/run/install/repo/ks/ks.cfg`
when ISO is mounted):

- `tandev` password: `Tanium1` — literally in `post.sh` (`echo "Tanium1"
  | passwd --stdin tandev`)
- `tanadmin` password: also `Tanium1` — cracked the kickstart's
  md5crypt hash `$1$ZVKYvk.7$fe6pq8vjN7Ugj8a2iS4zB1` with
  `openssl passwd -1 -salt ZVKYvk.7 Tanium1`

The initial-config wizard forces a password change on first login. We
generate a strong one (must have ≥1 lowercase, ≥1 uppercase, ≥1
numeric, ≥1 non-alphanumeric; ≥10 chars; not dictionary-based; not
containing the username) and store it in vault as
`vault_bwt_tanadmin_password`.

## The wizard navigation pattern

After boot, the VGA console shows a Linux login prompt. tanadmin login
+ Tanium1 password → "Press Enter to continue" → TanOS Initial
Configuration TUI.

Required steps (any order, but P must be first):

| Key | Step | Inputs |
|-----|------|--------|
| **P** | Password change | current_pw → new_pw → confirm_pw → press Enter to continue |
| **A** | Set IP Address | interface selection (1) → IPv4 addr/prefix → IPv4 gateway → "accept default IPv6 settings? [Y/n]" → confirm y |
| **N** | Set FQDN | hostname.domain → confirm y |
| **D** | Set DNS | nameserver 1 → nameserver 2 → blank line to end → confirm y → press Enter to continue |
| **T** | Set NTP | server 1 → blank line to end → confirm y → press Enter to continue |
| **E** | View+Accept EULA | press Enter to enter pager → q to quit pager → email address → confirm y |
| **F** | Finish Initial Configuration | (enabled once all above complete) |

After F: VM reboots automatically. Comes back at a normal TanOS login
with the wizard gone forever.

## What got baked into template 9002

Template `template-tanos-1.8.6-bwt` (VMID 9002):

- Password change: tanadmin pw set to `vault_bwt_tanadmin_password`
- IP: `10.99.0.99/24` (placeholder — every clone gets reconfigured)
- Gateway: `10.99.0.1`
- FQDN: `bwt-tanos-template.bwt.local` (placeholder)
- DNS: `1.1.1.1`, `8.8.8.8`
- NTP: `pool.ntp.org`
- EULA accepted (acknowledger: `adam.durham@tanium.com`)
- SSH pubkeys for `personal_macbook` + `tanium_macbook` injected into
  tanadmin's authorized_keys via `add pubkeys` (this happened after
  initial config finished; required logging in to a privileged shell
  via QMP console and using `add pubkeys` from stdin)

After bake: shutdown, then `qm template 9002`.

## Per-clone post-clone reconfiguration

Every clone of 9002 boots with the template's IP (10.99.0.99) and FQDN
(bwt-tanos-template.bwt.local). We need to override both per VM.

**FQDN — via SSH CLI command:**

```
ssh tanadmin@10.99.0.99 "set fqdn bwt-zs-01.bwt.local"
```

Works instantly because the template has our pubkeys baked in (Mac's
1Password agent forwarded through ProxyJump pve01).

**IP — via QMP keystrokes through the Appliance Configuration menu:**

TanOS has no CLI command to change IP. Only the menu path works:

```
Main Menu → A (Appliance Configuration)
         → 2 (Networking Configuration)
         → 1 (Network Interfaces)
         → 1 (eth0)
         → I (Manage IP address)
         → (clear pre-filled IP with 20 backspaces, type new IP/24)
         → (press Enter to accept pre-filled gateway)
         → Y (accept default IPv6)
         → y (confirm)
         → (wait ~10s for network restart)
```

Implemented in `ansible/roles/tanos_post_clone_config/tasks/main.yml`.

**The idempotency check:** if the VM is already responding to SSH at
its target IP, skip the entire reconfig. Lets re-runs of the playbook
be safe.

## Clone serialization (the .99 collision)

Every clone boots at 10.99.0.99. If two clones boot simultaneously,
they'll ARP-conflict on the template IP. Solution: `serial: 1` in the
play. One clone provisions completely (clone → boot → IP change →
moves off .99) before the next starts.

A 5-server build takes about 15-20 minutes serially. Acceptable.

## SSH key injection challenge (chicken-and-egg)

The TanOS template has SSH listening but with `publickey,keyboard-interactive`
auth only. We can't inject our key without already having a way in.

Three options that work:
1. **Bake the keys into the template before templating** (what we did).
   Use QMP keystroke automation to login as tanadmin, run `add pubkeys`
   from a pty-driven shell that types the keys. After template is
   converted, every clone has the keys baked in.
2. **Use the Proxmox web console once** (manual, doesn't scale to
   automation).
3. **Write a python-pty wrapper** that handles keyboard-interactive
   auth and pipes stdin into the `add pubkeys` command:
   ```
   cat /root/.ssh/id_rsa.pub | TANOS_PW=secret python3 tanos_ssh.py tanadmin@host "add pubkeys"
   ```

Once one valid pubkey is in tanadmin's authorized_keys, all subsequent
adds go via standard SSH.

## Files this phase produces

| File | Purpose |
|------|---------|
| `scripts/proxmox/qmp_keystroke.py` | The QMP keystroke driver |
| `ansible/roles/tanos_vm_clone/` | Clones template 9002 to per-host VMIDs, retargets to bwt bridge |
| `ansible/roles/tanos_post_clone_config/` | Per-clone IP + FQDN reconfig (SSH + QMP keystrokes) |
| `ansible/deploy_bwt_servers.yml` | Orchestrates clone + reconfig for all 5 BWT servers |

## Verification

```
# After deploy_bwt_servers.yml — all 5 should report their correct hostnames
for ip in 10.99.0.10 10.99.0.11 10.99.0.12 10.99.0.13 10.99.0.14; do
  ssh -o ProxyJump=root@192.168.86.11 -o StrictHostKeyChecking=accept-new \
    tanadmin@$ip "report info" 2>&1 < /dev/null | grep -E "Name:|FQDN:|TanOS Version"
done
```

Expected:
```
Name: bwt-ts, FQDN: bwt-ts.bwt.local, TanOS Version: 1.8.6.0134
Name: bwt-zs-01, ...
... etc.
```

## Pitfalls

- **TanOS rate-limits failed logins.** 10+ failed sshpass-via-keyboard-interactive
  attempts triggers pam_faillock with `unlock_time=600s`. If you suddenly
  can't login, wait 10 minutes (or destroy the clone and re-clone).
- **`qm guest cmd` accepts only positional args.** Can't pass
  `--username tandev` style. For commands that need args, talk to the
  qga socket directly: `(printf '...\n'; sleep 0.3) | timeout 3
  socat - UNIX-CONNECT:/var/run/qemu-server/<vmid>.qga`.
- **The `combo` action in qmp_keystroke.py is for multi-key combos
  (shift+a).** Single keys like backspace use `key`. Easy mistake.
- **The TanOS appliance ISO's kickstart references `/run/install/repo/`
  paths.** These are on the install media itself. Don't try to override
  the kickstart — anaconda boots from the ISO and the kickstart's
  pre/post scripts need that path resolution. Override only the network
  stanza via boot args if you need to (we didn't — we just drove the
  TUI).
- **Wrong template VMID after qm template.** If you accidentally
  template at a non-conventional vmid like 998, clean rename via
  `qm clone 998 9002 --full --target <node> --storage <s>` then
  `qm destroy 998 --purge`. There's no `qm renumber-template`.
- **Don't forget `qm template <vmid>` step.** Without it, the VM is
  just a stopped clone of itself, not a real template. Cloning works
  either way, but `qm clone --full` from a non-template is slower.
