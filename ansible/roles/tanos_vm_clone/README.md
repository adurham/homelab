# tanos_vm_clone

Clones a TanOS appliance VM from the BWT-ready template (VMID 9002,
`template-tanos-1.8.6-bwt`), retargets to the `bwt` SDN bridge, customizes
per-VM resources, and waits for SSH.

## Template 9002 — what's baked in

The template is a fully-finished TanOS 1.8.6 appliance:

| Property | Value |
|---|---|
| Hostname | `bwt-tanos-template` |
| FQDN | `bwt-tanos-template.bwt.local` |
| IP | `10.99.0.99/24` (placeholder — must be overridden post-clone) |
| Gateway | `10.99.0.1` |
| DNS | `1.1.1.1`, `8.8.8.8` |
| NTP | `pool.ntp.org` |
| EULA | accepted (acknowledger: `adam.durham@tanium.com`) |
| `tanadmin` password | in vault as `vault_bwt_tanadmin_password` |
| `tanadmin` SSH keys | `personal_macbook.pub` + `tanium_macbook.pub` |

## How the template was originally baked

Fully automated via `scripts/proxmox/qmp_keystroke.py` driving the TanOS
TUI initial-config wizard over QMP keystrokes. The procedure is captured
in skill `tanium-bwt-lab` (TODO: add). Key insight: QEMU's `send-key`
QMP command can drive any VM's keyboard regardless of console config, so
we can automate first-boot TanOS even without a working serial console
or pre-existing SSH access.

## Per-clone post-boot reconfiguration

Clones inherit the template's IP (10.99.0.99) and FQDN, which collide.
After clone+boot, the `tanos_initial_config` role (TODO: build) uses
`qmp_keystroke.py` again to navigate Appliance Configuration → Networking
and change the IP to the inventory-defined value, then `set fqdn` via SSH
to set the hostname.

## Role variables

| Var | Default | Purpose |
|-----|---------|---------|
| `tanos_template_vmid` | `9002` | Source template VMID |
| `tanos_clone_vmid` | `{{ vmid }}` | Target VMID (from inventory) |
| `tanos_clone_name` | `{{ inventory_hostname }}` | New VM name |
| `tanos_clone_storage` | `{{ vm_storage }}` | Proxmox storage backend |
| `tanos_clone_target_node` | `{{ target_node }}` | Which pve node to clone on |

## What the role does

1. Checks if VMID already exists (idempotent).
2. `qm clone --full --target {{ target_node }} --storage {{ vm_storage }}`.
3. `qm set` to adjust CPU/memory + move to `bwt` bridge + enable serial0.
4. `qm start`.
5. Waits up to 5 minutes for SSH on the expected IP.

Note: clones come up at `10.99.0.99` initially (template's IP). The
expected IP from inventory (`ansible_host: 10.99.0.10` etc.) is only
reachable after `tanos_initial_config` runs.
