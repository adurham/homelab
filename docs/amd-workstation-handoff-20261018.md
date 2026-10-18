# amd-workstation — session handoff (2026-10-18, ~10:30 CDT)

Purpose: everything a fresh session needs to resume the RAM diagnosis/mitigation campaign without
re-reading the transcript. Repo: `~/repos/homelab` (branch main). Evidence bundle: `~/rma-evidence/`.

## 1. TL;DR state

- The workstation has **one defective DDR5 SO-DIMM**. It is PROVEN bad and the Corsair lifetime RMA is
  **filed**. The user's requirement is **64 GB (both modules installed)** — 32 GB is explicitly not an
  option — so we are running the defective module with mitigations while the RMA plays out.
- **Current physical state: only the defective module (`A534T4312CDC8M`) is installed.** The good
  module (`A534T4312CD0JC`) is on the bench and must be installed (user is doing the swap).
- **Next action (user's hands): install BOTH modules, then reboot.** The reboot applies the staged GRUB
  params and clears a duplicate `dbus-daemon` left from the overnight crash.
- Then: run the stability ladder (section 5) and record results.

## 2. Hardware / firmware facts

- Minisforum BD790i (Meigao DRFXI), Ryzen 9 7945HX, AMI BIOS **1.17 (2026-08-28) = latest published**.
- 2 x Corsair `CMSX32GX5M1A4800C40` 32 GB SO-DIMM DDR5, JEDEC **4800 MT/s @ 1.10 V**, no EXPO, 1 DIMM
  per channel, non-ECC. Module serials are ONLY on the physical labels (SPD serial fields are zero on
  this SKU — verified by dumping both SPDs; they are byte-identical).
  - **Defective: S/N A534T4312CDC8M** (fails alone / corrupts in the pair).
  - **Good: S/N A534T4312CD0JC** (25-minute full-load run, 0 errors).
- BIOS settings currently in effect (verified by decoding the live `AmdSetupRPL` efivar against the
  firmware IFR map): Ac Loss Control = **Always On** (0x61=1); Global C-state Control = **Disabled**
  (0x29=0); Power Down Enable reported as Auto in the CBS store (the UI toggle lives in the AMD
  Overclocking store — unconfirmed); VDDIO last set to 1000 mV by hand during the sweep (should be
  returned to **Auto/1100 mV**); iGPU `UMA Frame buffer Size` = 1G; Secure Boot disabled (may have
  reverted to Enabled after "Optimized Defaults" — check).
- **Hidden firmware menus**: `UMC Common Options`, `DF Common Options`, `SMU Common Options` (PPT,
  MBIST, DDR data-eye) are suppressed by an internal **"Combo CBS"** value (QuestionId 0x9 @ offset
  0x20; live = 0x03; 0xFF would unhide). The setup stores are write-protected post-boot
  (`EFI_WRITE_PROTECTED`), so those menus are unreachable from software and invisible in the UI.
  Reachable knobs live under **AMD Overclocking** (VDDIO, DDR frequency/timings, DDR power options).

## 3. Diagnosis + evidence (all verified)

- Failure signature: single-bit flips concentrated in **data bit 12** (one weak DQ lane) plus
  multi-word / stale / dropped-write corruption; confined to ONE **256 B interleave channel**
  (827/915 repro addresses on even granules, all odd granules >=3 zero hits; independent burn-in run
  7/7 even).
- The 256 B granule was proven to be the channel unit, bit 8 = channel, no hashing, by a
  bandwidth-contention probe (`~/rma-evidence/chanprobe.c`, results in `chanprobe-results.txt`).
- Timing signature: errors start **~18-19 s after each load-dip resume**; a no-pause steady-load run
  had **zero** errors in 17 min. => triggered by power-state transitions.
- Kernel deaths: oopses from single corrupted pointers (waitqueue / kmalloc / kernfs; bits 44/45),
  plus a **stack-protector panic inside `acpi_idle_enter_bm`** (the CPU idle path) with the bad module.
- Overnight (Oct 17->18) on the defective module: **dbus-daemon SIGSEGV**, wireplumber crashed twice,
  whoopsie crashed, a pytest run crashed — userspace carnage, nothing caught it until D-Bus died.
  Artifacts: `~/rma-evidence/crash-artifacts-20261018/`, plus efi-pstore crash records pulled earlier.
- Power: the Shelly plug recorded a true **0.0 W rail dropout** during one panic boot; one earlier death
  could not be recovered by panic=15 OR the armed 60 s TCO (effectively unpowered). Treat board/PSU as a
  possible SECOND problem — watch for recurrence now that the good module is going in.

## 4. What is already installed / configured

Box (all reversible):
- `/usr/local/bin/memcanary.py` + `memcanary.service` — 1.5 GiB resident pattern, per-chunk blake2b
  verified every 300 s, logs `/var/log/memcanary.log` (+ journal warning on flips). Verified clean at
  1.44 s per pass.
- `/usr/local/bin/git-fsck-all.sh` + `git-fsck.service` + `git-fsck.timer` — nightly 03:30 fsck of all
  `~/repos/*`, PROBLEM lines to `/var/log/git-fsck.log`.
- `thp-madvise.service` (THP=madvise), `/etc/sysctl.d/95-integrity.conf` (panic_on_oops=1,
  dirty_expire_centisecs=300, dirty_background_bytes=64M, swappiness=10), sleep/suspend/hibernate
  targets masked, **GRUB cmdline staged with `processor.max_cstate=1 idle=halt`** (applies on reboot).
- `sp5100-tco.service` (hardware watchdog, 60 s; proven in the field 2026-10-17: kernel reported
  "Previous system reset reason: hardware watchdog timer expired"), panic=15, efi-pstore, kdump.
- Deliberately NOT installed: **zram** (a flipped bit in a compressed page destroys the whole page).
- Shelly **Plug US Gen4** (`S4PL-00116US`, 192.168.86.57, name `amd-workstation`): power-on default ON,
  cloud disabled, relay controllable over RPC (`/rpc/Switch.Set`, `/rpc/Switch.GetStatus`).
  NOTE: it can only KILL the box until "Ac Loss Control = Always On" is confirmed in the BIOS.

Repo (deployed to HA when possible):
- `homeassistant/command_line.yaml` — `switch.amd_workstation_power`, power sensor, and
  `binary_sensor.amd_workstation_reachable` (SSH-port liveness; a zombie reads DOWN).
- `homeassistant/automations/amd_workstation_power_recovery.yaml` — 5 min down -> plug off/on,
  10-min rate limit, alert-and-stop if still down. **Deployment is BLOCKED**: the HA Terminal & SSH
  addon rejects the repo deploy key (`id_ansible`); the fix is to paste this into the addon's
  authorized_keys:
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOjHFdTI+pgWj+qazI+dwH7udGc4QPYoIQpiqV0Fw/07 ansible-deploy@adams-macbook`
  (Native Shelly integration does NOT offer this Gen4 model in HA 2026.9.3; WS flow-start is not
  exposed in this version.)

## 5. NEXT: stability ladder (user installs both modules first)

Test command (unchanged): `bash ~/stress-run.sh -s 1500 -M 52000 -W --pause_delay 120 --pause_duration 15`
(pair = `-M 52000`; single stick = `-M 26000`). Every run: 25 min; report is
`Status: PASS|FAIL` + incident count in `/tmp/stress-out-*.log`.

Order (one change per run; stop when 0 incidents on TWO consecutive runs; any panic = revert):
1. Baseline: both modules, 4800 MT/s, current shim (C-states off, power-down off, VDDIO Auto).
2. DRAM **4000 MT/s**, timings Auto (biggest real lever: more data-eye margin).
3. Fan profile max/constant + airflow aimed at the DIMMs (18 s lag = thermal time constant).
4. DIMM VDD **1.15 V** (one step, then stop; non-monotonic like VDDIO).
5. **3600 MT/s** only if #2 reduced but didn't zero incidents.
Skip: loosened timings, FCLK, any VDDIO != Auto. Hard budget 6 runs (~3 h).

Known-good reference numbers (single defective module, shim): VDDIO Auto = 9 incidents (completed);
1.0 V = 547; 1.2 V = 929 + panic. Stock = boot panic.

## 6. RMA status (both filed — do not re-file)

- **Corsair (RAM, lifetime)**: request emailed 2026-10-18 00:04 to `support@corsair.zendesk.com`
  (their real Zendesk mailbox; help.corsair.com chat/form is Cloudflare-walled and blocks automation).
  Receipt attached; claim text `~/rma-evidence/corsair-claim-body.txt`; chat-paste variant
  `corsair-chat-paste.txt`. Claim INSISTS on a replacement part (same model or similar function/
  capacity) and explicitly refuses a refund/store credit (DRAM prices are up 4-6x). Watch for their
  reply; if they demand the web chat, that needs the user's browser (Cloudflare).
- **Minisforum (board, 2-year)**: claim emailed 2026-10-17 17:08 to `support@minisforum.com` inside the
  warranty window (delivered 2024-10-18, so it expired 2026-10-18). Two identical copies went out
  (verification read the wrong Sent mailbox and the retry duplicated it — harmless). Keep the ticket
  alive with "diagnosis ongoing, RAM RMA pending" and DO NOT ship hardware until the RAM verdict is
  final; the cross-slot result closes it either way.
- **MemTest86 on the defective module is still OWED** — Corsair techs expect it. Needs a USB stick and a
  boot at the machine. Pre-empt "it passed our bench" with our logs + the boot-panic behaviour.

## 7. Other outstanding items

- **Data-integrity audit gaps**: `debsums` is not installed (system-binary verification); no restic/borg
  backup jobs found on the box; keep older backup generations rather than rotating them out.
  (btrfs/ZFS would NOT help here — checksums are computed over page cache, so pre-hash flips are baked in
  with valid checksums.)
- **HA deploy key** (section 4) to switch on the plug's auto-recovery.
- **iGPU frame buffer** already at 1G; optional performance items: PPT control (hidden), Core
  Performance Boost = Auto (=on, good), Curve Optimizer/PBO (OC menu; only after RAM is settled).
- Consider raising **1Password's auto-lock timeout** — it locked mid-session three times tonight and
  breaks SSH/key-sudo on the box (the agent socket then refuses to sign).

## 8. Gotchas learned (do not re-learn these)

- `sudo -n` bypasses `pam_ssh_agent_auth` on this box — always plain `sudo cmd </dev/null` over `ssh -A`.
- Heredoc-written scripts can arrive with sudo lines mangled — transfer scripts with **base64**, byte-exact.
- `ansible-vault view/decrypt` fails on `ansible/inventory/group_vars/all.yml` (plain YAML with an inline
  `!vault` scalar). Resolve vars with:
  `ansible homeassistant -i inventory -c local -m debug -a "var=homeassistant_token"`.
- HA 2026.9.3 WS: no flow-start command (`config_entries/flow` -> unknown_command; only
  `flow/progress` and `flow/subscribe` exist). REST `/api/states`, `/api/services` work with the token.
- Mail via AppleScript: the app-level `sent mailbox` is NOT the Gmail account's Sent folder — iterate
  `mailboxes of account "Google"` for one whose name contains "Sent". NEVER blind-retry a send.
- Cloudflare blocks both curl and the automated browser on help.corsair.com.
- The board's UI hides advanced CBS menus (section 2) — don't quote those menu paths to the user again.

## 9. File index

- Evidence: `~/rma-evidence/` (dmidecode, SPD dumps, pstore records incl. `1792258831/`, stress logs,
  `chanprobe.c` + results, `df-config/`, `crash-artifacts-20261018/`, claim drafts, receipts).
- Tools: `~/bios-remote/` (bios-set EFI toolkit + records, `rma-session-runbook.md`, `memcanary.py`,
  units, `shelly-amd-plug-setup.sh`, `watchdog-livetest.sh`, `upon-return.sh`).
- Records: `~/repos/homelab/docs/ipam.md` rounds 5-34 (this campaign).
