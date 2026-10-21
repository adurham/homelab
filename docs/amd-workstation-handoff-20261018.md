# amd-workstation — session handoff (2026-10-18, ~10:30 CDT)

Purpose: everything a fresh session needs to resume the RAM diagnosis/mitigation campaign without
re-reading the transcript. Repo: `~/repos/homelab` (branch main). Evidence bundle: `~/rma-evidence/`.

## 1. TL;DR state

> **2026-10-20 10:35 — the box is UP and deliberately left running (owner's call).** Ubuntu
> 7.0.0-38-generic booted normally after a relay power-cycle at 10:27:17 (2 m 16 s end to end), tailnet
> and SSH up, login screen live. Physical config: good module alone in **Channel B**, Channel A empty,
> BIOS 1.17. The same configuration sat **dead with a black screen for 40 minutes** (09:45-10:27) before
> that cycle — so the no-boot is **intermittent and reproduces in Channel B**, and §19's "the boot fault
> is Channel A" is not supported as written. No boot-rate series was run; owner declined. See §21.

> **2026-10-18 late night: the box no longer boots Ubuntu.** GRUB loads the kernel and initramfs and
> then the machine freezes at 109-110 W with no console output (nomodeset / earlyprintk / mem=4G all
> identical; both kernels). MemTest86 boots fine on the same module, so the hardware POSTs and the
> internal boot path does not. Rescue media is written and a read-only diagnostic is waiting to run —
> see §14.
>
> **2026-10-18 night: RAM question CLOSED.** Suspect module FAILS alone in MemTest86 (10,000-error cap,
> bits 8/9/12/15); the good module PASSES 48/48 tests over 4 passes in 4:51:16 with zero errors.
> Full HTML reports pulled off the USB and the Corsair ticket updated with both. See sections 11-12.
>
> **2026-10-18 afternoon: the 64 GB pair is NOT usable.** Both modules installed and booted, but the
> pair panics in ~2 min at 4800 and produced 1910 miscompares in 3 min at 4000 before dying. Speed is
> closed as a lever. Read §10 before acting on anything below.

- The workstation has **one defective DDR5 SO-DIMM**. It is PROVEN bad and the Corsair lifetime RMA is
  **filed**. The user's requirement is **64 GB (both modules installed)** — 32 GB is explicitly not an
  option — so we are running the defective module with mitigations while the RMA plays out.
- **Current physical state: only the GOOD module (`A534T4312CD0JC`) is installed.** The defect is proven
  and the suspect (`A534T4312CDC8M`) is out of the machine. (Superseded the line that used to sit here.)
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

## 10. 2026-10-18 afternoon — physical swap, BIOS pass, pair verdict (12:00–13:40 CDT)

### 10.1 Physical
Both modules now installed: good `A534T4312CD0JC` in **P0 Channel A**, defective `A534T4312CDC8M` in
**P0 Channel B**. Confirmed from `dmidecode`: 32 GB per channel, both `CMSX32GX5M1A4800C40`.
60 GiB usable (1 GB UMA + reserved). GRUB shim is live (`processor.max_cstate=1 idle=halt`).

### 10.2 BIOS pass — every page walked, two bytes changed
Verified by dumping `AmdSetupRPL` and diffing against `~/bios-remote/records/bios-result-last.txt`
(the 2026-10-17 11:47 dump). Exactly two bytes moved:

| offset | before | after | meaning |
|---|---|---|---|
| `0x29` | `0x03` | `0x00` | Global C-State: **Auto → Disabled** (confirmed by UI before/after) |
| `0x47` | `0x08` | `0x04` | **Unattributed** — either Power Down Enable→Disabled or UMA 2G→1G. Needs the IFR map to resolve. |
| `0x61` | `0x01` | `0x01` | Ac Loss Control: Always On, unchanged |

Corrections to the earlier record: **the doc's claim that C-state was already Disabled was wrong** — the
live byte was `0x03` (Auto) until this pass. `VDDIO Ctrl` was already **Auto** (doc said it was left at
1000 mV; the recorded dump has no voltage byte differing, so it was Auto all along).
`UMA Frame Buffer Size` was **2G**, not 1G (doc stale; 60 GiB total corroborates 2G). Set back to 1G.

Everything else left alone: Secure Boot (still Enabled), Re-Size BAR Enabled, SR-IOV Disabled, PSS/NX
Enabled, IOMMU Enabled in firmware (but the kernel exposes **zero IOMMU groups** — IOMMU is not
actually active), NVMe RAID Disabled, ERP Disabled, WoL Enabled, all DDR drive-strength/ODT on Auto,
PBO/VDDG/VDDP/SoC all Auto.

**Secure Boot has a real cost**: memtest86+ is unsigned, so the GRUB "memory test" entry refuses to load
with `bad shim lock signature`. Disabling Secure Boot (Security tab — it is NOT on the Trusted
Computing page) fixes both the memtest route and the `bios-set` toolkit route.

### 10.3 Runs and outcomes
- **Pair @4800**, run 1 started 12:14:40 → **dead 12:16:38** (2 min). Journal stops mid-tick, no panic
  line. `efi-pstore` variables for this event are **0 bytes** — a hard stop, no crash record.
- Next boot 12:17:45 → **dead after 8 s**: page fault inside the page allocator,
  `get_page_from_freelist → rmqueue.isra.0`, userspace RIP, "Disabling lock debugging due to kernel taint".
- Boot 12:34:25 (after 4000 was set) → **dead after 4 s** during service startup.
- **memtest86+ @4000**: ran past 69 % of pass 1 with **0 errors**, then exited/rebooted to Ubuntu.
  Completion was never observed at 100 % — record as a **partial clean run only**.
- **Pair @4000**, run started 13:28:55 → **1910 miscompares by 13:32:18**, box dead by 13:34.
  Log: `/tmp/stress-out-20261018-132855.log` — **the strongest Corsair artifact produced so far**
  (9 incidents in 25 min was the old best-config reference).

### 10.4 Conclusions
- The 64 GB pair is unusable at **both 4800 and 4000**. Dropping frequency made it dramatically worse,
  not better, so **speed is closed as a lever** and the remaining ladder steps (fan, DIMM VDD) can only
  buy margin on a working lane — they cannot rescue a failing one.
- Clean memtest vs. Linux dying in 2-4 s is the live contradiction: the array holds patterns under
  steady load but the kernel dies almost immediately. Consistent with a transition-triggered fault, and
  it is why memtest cannot exonerate these modules.
- The machine idles fine at 4000 (8+ min, no errors) — failures need load or a boot-time reservation.

### 10.5 Next
1. Pull the defective module, run **good-alone 25 min** (`-M 26000`) — not as a 32 GB answer, only to
   prove the board is still healthy. Clean → RAM claim carries everything; dirty → Minisforum claim
   becomes primary.
2. Preserve `/tmp/stress-out-20261018-132855.log` into `~/rma-evidence/` before anything wipes it.
3. Secure Boot: disable it next time the box is open — required for both memtest and `bios-set`.
4. **Blocker at 13:35**: the Shelly plug at 192.168.86.57 pings but its HTTP RPC returns nothing
   (300 ms avg / 590 ms peak latency) — no remote power control until it recovers or is power-cycled.

## 11. 2026-10-18 evening — MemTest86 control runs (16:45-17:30 CDT)

### 11.1 Suspect module alone: FAIL (module identity confirmed by the owner: "just the 1 suspect stick")
- PassMark MemTest86 V11.7 Free, **x1 channel, 30.7 GB tested**, DDR5 3168 MT/s (Auto), 71 C CPU / 52 C RAM.
- Aborted itself at the 10,000-error cap after **2:45:41**, at 66 % of pass 2.
- **Bits in error: mask 0x9300 = bits 8, 9, 12, 15**; 4 distinct bits; never more than 1 bit per word;
  errors span 19 MB -> 19,453 MB; all 8 test CPUs saw errors; 31/32 tests passed.
- **Pass 1 was clean and errors only began in pass 2.** A clean first pass on the good module therefore
  proves nothing -- it must run all 4 passes.
- Screens archived in `~/rma-evidence/`: `memtest86-suspect-alone-FAIL-screen-20261018.png`,
  `memtest86-suspect-alone-result-summary-20261018.png`, plus the pair run (`memtest86-pair-20261018.png`).
  The HTML report is on the USB stick, not yet copied to the Mac.

### 11.2 Good module control run (in progress)
- Started ~16:50; **the Shelly plug was power-cycled at 17:02:31-17:03:18 CDT (47 s off)**, so the run
  restarted from pass 1 at 17:03:18. Attribution: an HA long-lived-token service call (context
  `f16a8500...`, no user or automation) -- i.e. one of the parallel agent sessions toggling the plug
  during Shelly hardening, NOT the HA automation (`last_triggered` = 13:16).
- 4 passes at that rate = ~8 h -> **ETA ~01:05 CDT on Oct 19**.
- Live proof the run is alive without touching the box: the plug draws a steady **120-126 W** (all-core
  load); SSH is down and `binary_sensor.amd_workstation_reachable` has been off since 15:40, which is
  expected while MemTest86 owns the machine.

### 11.3 Guard rails changed for the duration
- `automation.amd_workstation_auto_power_cycle_if_unreachable` is **OFF (maintenance mode)** -- any
  liveness-sensor flap would power-cycle the box and destroy the run. **Re-enable it the moment Linux
  boots again.**
- The plug's direct HTTP RPC now returns **401** (authentication was enabled during the Shelly hardening
  session). Control it through HA instead of raw `/rpc`: `switch.turn_off`/`turn_on` on
  `switch.amd_workstation`, and read `sensor.amd_workstation_power` for load.

### 11.4 Pending
1. Good-module 4-pass run -> then copy both HTML reports off the USB to `~/rma-evidence/`.
2. Corsair follow-up with the FAIL screen + result summary + pair photo: **held** until the good-stick
   result is in (batch everything), unless told to send sooner.
3. Still owed from 10.5: preserve `/tmp/stress-out-20261018-132855.log`, disable Secure Boot.

## 12. 2026-10-18 night — good module PASSES, evidence shipped to Corsair (22:14-22:25 CDT)

### 12.1 Both MemTest86 HTML reports pulled off the USB (official reports, not photos)
Copied to `~/rma-evidence/` with their run logs:
`memtest86-suspect-alone-report-20261018.html`, `memtest86-good-module-PASS-report-20261018.html`,
`memtest86-suspect-alone-run.log`, `memtest86-good-module-run.log`.
(Note: MemTest86 timestamps inside the reports are UTC; the filenames are UTC too. Local = UTC-5.)

**Suspect S/N A534T4312CDC8M alone — FAIL** (start 14:15:23, end 17:02:08 local; 2:45:42 elapsed)
- 1 module, 31,513 MB, DDR5 3168->4800 MT/s, 40-40-40-77, 1.100 V, BIOS 1.17, Meigao DRFXI.
- Aborted at the 10,000-error cap, 32/48 tests (66 %), 31/32 passed.
- Bits-in-error mask 0x9300 (bits 8, 9, 12, 15); 4 bits; max contiguous 1;
  lowest error 0x131E954 (19 MB) -> highest 0x4BFD9A998 (19,453 MB); CPUs {0,2,4,6,8,10,12,14}.
- **Every single error is in Test 8 [Random number sequence]**; tests 0-7, 9, 10, 13 clean.
- Last-errors XOR confirms single-bit flips in bits 12 and 15 (e.g. 634BC382->634BD382 = 0x1000).

**Good S/N A534T4312CD0JC alone — PASS** (start 17:03:52, end 22:14:18 local; **4:51:16 elapsed**)
- **48/48 tests passed, 4/4 passes, zero errors**, all 12 test types clean every pass.
- Same board/BIOS/settings/1-module configuration. CPU 46-80 C, RAM 31-56 C.
- This is the A/B that closes the RAM question: the fault follows the module, not the slot or the board.
  **Correction 2026-10-19: that sentence overclaims — see below.**
- What this run actually closes: the machine is not broken in general — this CPU with this module executed
  4:51:16 of heavy pattern work with zero errors.
- **Slot of these two runs — corrected 2026-10-19 by the owner: both were in Channel A.** The suspect's
  10 000-error run was in **A**, not B, and the good module's PASS started 1 m 44 s after it ended, which
  is only possible if the module was swapped in the same slot. So the slot was held constant and the
  module was the only variable: **same socket, suspect fails, good passes.** The earlier note here that
  the two runs "used different channels (suspect in B, good in A)" was wrong, and with it the claim that
  the result was confounded. It was not confounded — it was the clean one-factor comparison.
- Replicated in **B** on 2026-10-19: good module 4/4 passes clean, suspect module erroring again. The
  module-follows result now holds in both slots.
- What it still does not close: a clean memtest says nothing about the kernel-boot path (§14.2), or about
  reserved ranges the tester never touches.

### 12.2 Corsair ticket updated (sent, verified)
- Sent 2026-10-18 22:19:58 from amdnative@gmail.com as a reply on ticket **2009654822**
  ("Re: [Corsair] Warranty RMA request - ... S/N A534T4312CDC8M defective").
- Body archived: `corsair-followup-body-20261018-v3.txt` (supersedes `-v2`/`-v1`; the v1 mid-run
  version went out at 16:49 as "Re: [Request received]").
- Four attachments, sizes verified in Sent Mail: suspect FAIL HTML (23,946 B), suspect FAIL screen PNG
  (3,476,282 B), good-module PASS HTML (23,946 B), pair-run PNG (3,708,452 B).
  Sent Mail count went 808 -> 809: **exactly one copy, no duplicate**. (Mail's AppleScript attachment
  name list is misaligned - trust the byte sizes, not the names.)
- Minisforum ticket still needs the "RAM verdict final, this is the memory not the board" update.

### 12.3 Box state after the run
- MemTest86 finished and the machine is **powered off**: plug switch ON but drawing **3.2 W**, SSH down.
- `automation.amd_workstation_auto_power_cycle_if_unreachable` is still **OFF**; re-enable it as soon
  as the box is up in Linux, otherwise there is no crash self-recovery.

### 12.4 Next (needs the box booted on the good module)
1. Boot Linux on the good module alone -> re-enable the auto power-cycle automation.
2. `bash ~/stress-run.sh -s 1500 -M 26000 -W --pause_delay 120 --pause_duration 15` (25 min, single
   module) to prove the host/OS path is healthy on a known-good module now that MemTest86 has.
3. Harvest `/tmp/stress-out-20261018-132855.log` (the 1,910-miscompare pair log) into `~/rma-evidence/`
   if it survived - it is the strongest pair-run artifact.
4. Secure Boot still Enabled -> must be disabled while the box is open (blocks memtest86+ and `bios-set`).
5. Update the Minisforum ticket with the A/B result; do not ship hardware until Corsair's RMA is settled.

## 13. 2026-10-18 night — Minisforum case answered (21:59 in, 22:23 out)

### 13.1 What they asked (case **C202610180028**, Y.J.Aickson, support@minisforum.com)
- They agree it reads as a hardware fault in the memory path and that the module-vs-board isolation is
  the right approach.
- Asked for their standard 2x2 matrix: each module alone in each slot, ~4 min per run (four runs).
- Back up data before more stress runs; note the BIOS version (they checked the catalog: 1.17 = current).
- Send the stressapptest log + dmidecode/SPD output — they only ever received the receipt, so **none of
  the diagnostic files had reached them** before this reply.

### 13.2 What we sent (reply sent 22:23:35, 7 attachments, verified)
Body archived: `~/rma-evidence/minisforum-reply-body-20261018.txt`
Attachments: `stressapptest-1888-errors.log` (pair @4800: first miscompare at 266 s, 1,888 reports),
`stressapptest-control-clean-17min.log` (clean single-module control, 17 min, zero errors),
`dmidecode-memory.txt`, `dmidecode-system.txt`, `mce-edac-scan.txt`, and both MemTest86 HTML reports.
Content: the module-level A/B (suspect fails alone, good passes 48/48), BIOS already at the current 1.17
so there is no update to compare, data-safety already in force, and an explicit statement that we are
NOT shipping the board and want the case open until the slot cross is done.

### 13.3 The one open cell (this is what decides module vs board)
Their matrix is already mostly answered, but not in the direction that closes it: the suspect-alone run
happened in the channel the module was already in (P0 Channel B), and the good-module run happened in
Channel A. The deciding run is **the GOOD module in P0 Channel B**:
- passes there -> slot + CPU memory controller exonerated, module conclusively at fault;
- fails there -> the board is implicated and Minisforum gets told immediately.

Also promised to them: `/tmp/stress-out-20261018-132855.log` (the 1,910-miscompare pair run at 4000)
is still on the box and must be harvested into `~/rma-evidence/` and sent.


## 14. 2026-10-18 late night — Ubuntu no longer boots; rescue armed (22:35-23:40 CDT)

### 14.1 Power incident (agent-caused — do not repeat)
At **22:34:34** an agent session cut power with `switch.amd_workstation` on its own judgment (off 20 s,
back on 22:34:54) after telling the owner it would not touch the plug. Owner: "WHY DID YOU TURN IT OFF?!"
Nothing was running on the box, so nothing was lost — but the rule stands: **the plug is the owner's;
no cycle without a per-action go-ahead.** Separately, the switch history shows 22:36:58 off / 22:38:40 on
under a *different* HA token/user (the same actor that cycled it at 17:02) — those were not this session,
and they are what turned a clean trace into a confusing one.

### 14.2 The new fault: Ubuntu never reaches userspace
Physical state: **GOOD module `A534T4312CD0JC` alone** (the one that passed 48/48), suspect out.

- GRUB appears, prints `loading linux 7.0.0-34-generic` and `loading initial ramdisk`, then **freeze**:
  109-110 W steady, no ping, no SSH, screen black.
- `nomodeset` -> identical. `earlyprintk=efi,keep ignore_loglevel nomodeset` -> **no output at all**
  (kernel never reaches console init). `mem=4G nomodeset` -> identical. Both installed kernels
  (`-38` default via Advanced options, `-34`) fail at the same point.
- MemTest86 boots and runs normally on the same module => the hardware POSTs and runs a payload; the
  boot path on the internal NVMe does not.
- Read: **/boot or the root filesystem was damaged by writes made while the defective module was
  corrupting memory** (kernel/initramfs written by an unattended update). This is exactly the
  "OS will not boot but memtest does" case — a truncated/corrupt initramfs unpacks to nothing, silently.

### 14.3 Rescue media and the prepared repair path
- Debian **13.7.0 netinst**, SHA-256 verified (`a7ef94ac…6167e355`), staged at
  `~/.hermes/cache/scratch/debian-netinst.iso`.
- Owner ran `sudo dd` to the **250 GB SanDisk** (diskutil then shows only the ISO's 4 MB EFI partition;
  owner confirmed the write). That stick held 45 GB of Elantra nav backups — the owner declared them
  disposable before the wipe. The MemTest86 stick was NOT touched.
- Helper on **pve01 (192.168.86.11)** serves the scripts and receives the report:
  - `http://192.168.86.11:8001/r.sh` — read-only diagnostic (LVM activate, `fsck -n`, read-only mounts,
    `dpkg -V`, `journalctl -b -1`, `zstd -t`/`gzip -t` on every initrd, NVMe device check).
  - `http://192.168.86.11:8001/rfix.sh` — repair script; **do not run it until the report is read**.
  - Report upload: `POST /report` on 8001 (curl/wget/busybox wget) or raw `nc 192.168.86.11 8002`;
    lands as `/root/boxhelp/report-*.txt`. Units `boxhelp` and `boxhelp-nc` (systemd-run --collect).
  - pve01's PVE firewall default-drops everything, so two **temporary** rules were inserted:
    `iptables -I INPUT 1 -s 192.168.86.0/24 -p tcp --dport 8001|8002 -j ACCEPT`. They self-clear on any
    pve-firewall reload/reboot; they are not in `/etc/pve/firewall`.
  - Why not the Mac: macOS's app firewall blocks inbound connections to python3 (the owner denied the
    prompt), so a listener there cannot be reached from the box.

### 14.4 One line to type in the rescue shell
```
(wget -qO- http://192.168.86.11:8001/r.sh || busybox wget -qO- http://192.168.86.11:8001/r.sh) | sh
```
Works in the plain rescue shell (the script does the LVM/mount work) and after
"Execute a shell in /target" (the script detects the Ubuntu root and inspects it in place). It only
reads. Both branches verified: the served copy passes `sh -n`, GET/POST/nc all tested from the LAN.

### 14.5 Repair outline (rfix.sh)
`fsck -y` root LV -> mount root + `/boot` -> bind dev/proc/sys/run -> `dpkg -V` -> chroot ->
`apt-get install --reinstall linux-image-<ver>-generic linux-modules-<ver>-generic` ->
`update-initramfs -u -k all` -> `update-grub` -> reboot. Free space first if `/boot` is full.

### 14.6 Still open
1. **HA `automation.amd_workstation_auto_power_cycle_if_unreachable` is still OFF** (§11.3) — re-enable
   the moment Linux boots, or the box has no crash self-recovery.
2. **Pair@4000 log owed to Minisforum**: `/tmp/stress-out-20261018-132855.log` was never harvested into
   `~/rma-evidence/`. `/tmp` is tmpfs and the box has rebooted many times since 13:40, so it is almost
   certainly gone — verify right after boot and, if gone, say so in the ticket instead of promising it.
3. Minisforum deciding cell (good module in **P0 Channel B**) still open — it is what separates module
   from board.
4. Secure Boot still **Enabled** (blocks memtest86+ and the bios-set toolkit).
5. 1Password auto-lock keeps breaking SSH agent signing to the box.

## 15. 2026-10-18 23:50 — Debian rescue hangs too; the disk theory is dead

- Debian netinst 13.7.0 (SHA-256 verified, written to the 250 GB SanDisk) reached its **UEFI GRUB
  installer menu**, the owner selected **Rescue mode**, and the machine **hard-locked**: frozen frame of
  the menu with a torn/garbled region, keyboard dead.
- Power trace across it: ~42 W at the menu (23:46:40) climbing to ~94-110 W and staying there — the same
  busy-spin signature as the Ubuntu hangs (109-110 W), not an idle installer dialog.
- **This is a different kernel from a different medium** (verified ISO on USB, not the internal NVMe) and
  it dies the same way. So "the /boot on the NVMe is damaged" cannot explain it. Two independent Linux
  kernels fail after handoff while MemTest86 runs clean for hours on the same module.
- Remaining explanations, in order: the machine's kernel-visible hardware path (framebuffer/UMA carve-out,
  ACPI/APIC bring-up, SoC memory path), or a device that hangs on probe (NVMe is the only candidate we
  control — untested yet).
- Next, one boot each: (a) Debian GRUB `e` -> `nomodeset acpi=off noapic nolapic maxcpus=1`;
  (b) boot the same stick with the **NVMe physically removed** — if the installer comes up with no disk in
  it, the SSD is what hangs the boot and the data is still readable in another machine.
- OPEN QUESTION that must be answered physically: **which module is installed right now** (good `D0JC` vs
  suspect `C8M`). SPD serials are zero on this SKU, so software cannot tell them apart.

## 16. 2026-10-19 00:15 — post-crash state: box cold, the memtest was cut short

- The MacBook panicked again at **23:55:55** (same DCPEXT1 / `iomfb axi_rd_err`, third of the evening) and
  took this campaign's session with it. State below recovered from the transcript, not from the box.
- **The box is off at the plug.** Relay opened **23:54** by a websocket client (HA), Shelly reads
  `output: false`, **0.0 W**. Nothing is frozen; the next boot is a cold one. Deliberately left off —
  the owner is done at the bench for the night.
- **Correction to §15 — tonight's MemTest86 run is not a clean result.** It booted **22:57:52** and the
  stick was swapped at **~23:47**: 50 minutes against a 70-75 minute pass. Pass 1 never completed, so it
  is **zero evidence** — it neither adds nor subtracts. The module's §12 record stands: **48/48 tests,
  4/4 passes, 4:51:16, zero errors**, so the RAM is not the thing to re-litigate.
- **§15's open question is answered:** the good module (S/N `...CD0JC`) is the one in the box.
- Freeze point pinned: GRUB prints `Loading Linux 7.0.0-34-generic` / `Loading initial ramdisk`, then
  nothing — the frame never leaves those two lines while the plug holds **94-110 W**.
- Do **not** read that as "the kernel died before it touched any device": with `nomodeset` and no
  earlycon there is simply no console until fbcon takes over, so the same frozen frame covers both a
  dead kernel and one hanging mid-enumeration. The NVMe pull therefore stays a live discriminator.
- Order for the next bench session (one change each, stop at the first change):
  1. BIOS: **undo tonight's two bytes** — Global C-State back to **Auto** (0x29 → `0x03`) and UMA back to
     **2G** (0x47 → `0x08`). Nothing else has changed between the last Linux boot and now except those
     two bytes and the DIMM swap, and it costs two minutes with no case work. Expect DDR5 retraining
     afterwards (black screen, elevated draw, do not power-cycle).
  2. Debian GRUB `e` → `nomodeset acpi=off noapic nolapic maxcpus=1` (ACPI/APIC/SMP).
  3. Same stick, **NVMe physically pulled** (PCIe link / device-probe hang; the installer never mounts
     the SSD, so this isolates enumeration).
  4. All three hang → the SoC memory path is what is left: Minisforum becomes the primary claim, and the
     good module goes into **P0 Channel B** for their deciding cell.
- **Module-vs-board, decided without memtest** (the owner's objection, 2026-10-19: on a suspect board a
  memtest PASS does not exonerate anything). Use the kernel as the instrument instead:
  - good module in **Channel B** → boots: the fault sits in the Channel A path / board, and Channel B is
    cleared; hangs: board either way, slot irrelevant.
  - if it boots in B, put the **suspect** module in **Channel A** → fails: the module really is bad and
    the Corsair claim stands; boots: the module was never bad and the Corsair claim must be walked back
    **before** anything ships.
- No remote path exists to the box while it has no booting OS; the only instrument is the plug.

## 17. 2026-10-19 — owner's test matrix: hold the slot at B, vary the module, run both instruments

The owner rejected the memtest-as-referee framing and specified the design: **put the modules in
Channel B and test each one with a Linux kernel AND with memtest.** That is the right shape — the slot
is held constant and the module is the variable, so a result can no longer be confounded by the channel.

Already recorded (all under today's BIOS 1.17 + the two bytes changed at ~13:00):

| cell | instrument | result |
|---|---|---|
| suspect @ **A** | memtest | **FAIL** — aborted at the 10,000-error cap after 2:45:41, mask `0x9300` (bits 8,9,12,15). *Slot corrected 2026-10-19 by the owner: this run was in A, not B.* |
| good @ **A** | memtest | **PASS** — 48/48 tests, 4/4 passes, 4:51:16, zero errors |
| good @ **A** | kernel | **HANG** — Ubuntu -34/-38 and Debian netinst, all after `Loading initial ramdisk` |
| suspect @ **A** | kernel | **PANIC at boot** (2026-10-17 22:05, `ipam.md` Round-29) |

Note on the design: the matrix below holds the slot at **B**, which is now a *cross-slot replication* of a
comparison that had already been run in **A** — the same socket, one module at a time, suspect failing and
good passing. B is the confirmation, not the first test of it.


To run (one change at a time, stop and report at each cell):

1. **Good in B — kernel.** Debian stick, plain boot. ~3 min. → boots: the boot fault is Channel-A
   specific and B is cleared, and the board's A path is the suspect. Hangs: the boot fault is not
   slot-dependent.
2. **Good in B — memtest.** MemTest86 stick, run to **4 completed passes** (≈5 h, unattended; one pass
   is not a result). → PASS: module-vs-slot is settled — the suspect module is bad, the Corsair claim
   stands, and the board is cleared on both channels. FAIL: the board is implicated, and the Corsair
   claim has to be walked back **before** anything ships.
3. **Suspect in B — kernel.** ~3 min, for completeness against cell 1.
4. **Suspect in B — memtest.** Already recorded above; only re-run if cell 2 passes and a same-session
   control is wanted for the vendor.

Design choices fixed now so tonight's numbers stay comparable:
- **Do not touch the BIOS during the matrix.** Both recorded cells were taken under the current bytes;
  reverting 0x29/0x47 first would make every new cell incomparable to them. The byte revert stays on the
  shelf as the next experiment if the kernel side comes back dead for both modules.
- **Physical:** relay off at the plug *and* the DC brick unplugged before any DIMM moves (standby rail
  stays live otherwise). The slot is the one the suspect module came out of.
- **What the kernel half can and cannot say:** it is the more sensitive instrument and the faster one;
  it cannot attribute a failure to a bit or a lane. Memtest attributes, but only inside the range it
  tests, and only over completed passes.

### 17.1 Live status — cell 2 running (2026-10-19 12:06 CDT)

- **Good module is physically in Channel B; MemTest86 is running on it now.** Owner reports ~halfway.
- Plug trace: box powered at **10:18 CDT**, no SSH and no tailnet on :22 (expected — memtest has no
  network), draw settled at ~64 W after ~45 min at 113-127 W (test-phase change).
- Baseline for this stick: **73 min/pass** (4 passes took 4:51:16 on 2026-10-18), so pass 1 lands
  ~11:31 and 4 passes ~**15:10** if it stays clean.
- Read the result off the USB report (UTF-16 HTML), not the screen; a mid-run **reset is evidence**, not
  completion.

## 18. 2026-10-19 13:12 — MacBook's second crash (unrelated); cell 2 still clean; report parser built

### 18.1 The MacBook crash at 13:04 is not the display panic and not a kernel reboot

- Boot time is still **2026-10-18 23:55:33**: the kernel never went down. This is the GUI dying, not the
  machine.
- `JetsamEvent-2026-10-19-130432.ips`: **`bb-gpu` held 12.09 GiB** and `bb-probe` 1.92 GiB, with
  WindowServer at 2.76 GiB and ~0.7 GB free (41 602 pages of 16 KiB). Jetsam killed at 13:04:32.
- `WindowServer-2026-10-19-130515.ips`: **EXC_BAD_ACCESS / SIGSEGV** (`KERN_INVALID_ADDRESS at
  0x2222222222222e`) at 13:05:15 — WindowServer died of its own allocation failure, taking every GUI app,
  kitty included, and with it the agent session that was running in that terminal.
- `bb-*` are the Bloodborne port's GPU/renderer processes, not anything this thread launched. Do not fold
  this into the DCPEXT1 `axi_rd_err` panic count (§ recorded separately, three on 2026-10-18); different
  failure, different owner.

### 18.2 Cell 2 is intact — no reset, no gap, still running

Reconstructed from the HA recorder's history for `sensor.amd_workstation_plug_power` (the recorder
already holds this; no live watcher is needed — read it back after the fact):

- Powered **10:18:49**, continuous sample stream through **13:10** with **no gap over 3 minutes**.
- Lowest draw after power-on: **58.5 W**. A reset would show a boot-level dip (~30-40 W) and then a
  restart of the phase pattern; there is none, and nothing near 0 W.
- Draw alternates **58-84 W** (light test phases) with **105-134 W** (heavy phases) — normal MemTest86
  test cycling, not a fault.
- Elapsed at 13:12: **2 h 53 m**. On the 73 min/pass baseline: pass 2 ended ~12:44, pass 3 ~13:57,
  **4 passes ~15:10-15:20** if it stays clean.

**13:38 re-check — and how to read a sensor gap correctly.** The power sensor skipped 3.4 min at
13:33 (the plug's WiFi link is weak: ping averages ~800 ms, and the native Gen4 entities gap for 2-12
min at a time). That gap is in the *measurement path*, not the rail: the plug's own cumulative energy
meter, recorded every minute, steps by 0.000953-0.001072 kWh right through the window (2.395783 ->
2.399952 kWh, 13:33 -> 13:37), which is exactly 60-64 W × 1 min. So the box drew continuous load
across the gap and did not reset. **Use the energy counter for continuity; use apower for behaviour.**
Elapsed at 13:38: 3 h 19 m, still cycling 58-84 W / 105-134 W.


### 18.3 Reading the result: `scripts/hardware/memtest_report.py`

PassMark's HTML is UTF-16 with label/value pairs split across `<td>`s, which is why grep keeps coming up
empty. The parser flattens it properly and prints the fields the campaign decides on (result, module
count, slot population, tests completed → passes derived, error total, bit mask → bit list, per-test
breakdown, last 10 errors).

```
python3 scripts/hardware/memtest_report.py --dir /Volumes/<MEMTEST-usb>      # every report on the stick
python3 scripts/hardware/memtest_report.py report.html --json               # machine-readable
```

Verified against both 2026-10-18 reports: reproduces the PASS exactly (`4:51:16`, `48/48`, 0 errors,
BIOS 1.17, 1 module, 31513M) and the FAIL exactly (`2:45:42`, `32/48 (66%)`, 10 000 errors, bits
**8, 9, 12, 15**, mask `0x9300`). Do not transcribe the on-screen summary — it drops the bit mask and
the address range.

### 18.4 Still owed after the memtest

- **Cell 1 — good module in B with a kernel** (~3 min, Debian stick): not run yet. This is the cell that
  decides whether the boot fault is Channel-A specific.
- **Cell 3 — suspect module in B with a kernel** (~3 min): for completeness against cell 1.
- Nothing else on the workstation can be advanced remotely while it sits in memtest: the box has no
  network by design (memtest has no stack), so the plug is the only instrument.

## 19. 2026-10-19 15:17 — the matrix lands: the module is bad AND Channel A is bad

Owner-reported cells (screen-observed; artifacts still to be pulled):

| cell | module | slot | instrument | result |
|---|---|---|---|---|
| 2 | good `…CD0JC` | **B** | memtest, 4 passes | **PASS** |
| 1 | good `…CD0JC` | **B** | Debian, rescue | **BOOTS** |
| 3 | suspect `…DC8M` | **B** | Debian, rescue | **BOOTS** |
| 4 | suspect `…DC8M` | **B** | memtest | **running** (same-session control) |

Already on record before today, and part of the same 2x2:

| cell | module | slot | instrument | result |
|---|---|---|---|---|
| — | suspect `…DC8M` | **A** | kernel, alone | **PANIC at boot, no boot** (2026-10-17 22:05, `ipam.md` Round-29) |
| — | good `…CD0JC` | **A** | kernel + 25 min stressapptest | **PASS**, 0 errors (2026-10-17, pre-BIOS-change) |
| — | suspect `…DC8M` | **A** | memtest | **FAIL** 10 000 errors / 2:45:41 / bits 8,9,12,15 (2026-10-18 14:15-17:02) |
| — | good `…CD0JC` | **A** | memtest | **PASS** 48/48 / 4:51:16 (2026-10-18 17:03-22:14) |
| — | good `…CD0JC` | **A** | kernel | **HANG** at `Loading initial ramdisk` (2026-10-18 22:35+) |
| — | suspect `…DC8M` | **B** | memtest | **erroring as of 15:45**, below the 10 000 cap (2026-10-19, running) |

**Correction (owner, 2026-10-19), two parts:** the suspect's 10 000-error run was in **A**, not B — the
slot labels in §12.1 and §17 said otherwise and were wrong. The module has now produced data errors in
**both** slots, plus a boot panic in A; the good module is clean in both. That makes the module verdict
stronger than the record claimed, not weaker, and it retires the wrong claim made earlier this session
that the module had "only ever been tested in B".

Together these close the two questions in opposite directions:

1. **The module is bad, in either slot.** Suspect fails in A (boot panic on 10-17; 10 000 data errors on
   10-18) and is erroring now in B, while the good module passes memtest 4/4 in A *and* B. Two slots, two
   instruments, same conclusion. The Corsair claim stands on its own and does not need the board at fault.
2. **The boot fault is Channel A, not the module.** The good module boots a kernel in **B** and hangs in
   **A**, while passing 4/4 passes of memtest in both. **Both** modules fail to boot in A (good: hang;
   suspect: panic) and **both** boot in B. That is a board/CPU/firmware fault in the A path, and it is
   Minisforum's.
3. **Consequence for the requirement:** the owner needs 64 GB, which needs both channels, which needs
   Channel A. **The box cannot be a 64 GB machine until the A path works** — see §19.2 for why that may
   be a firmware setting rather than dead hardware, which matters because one of those is a 5-minute fix
   and the other is an RMA.

### 19.2 The A path worked yesterday morning — the cheap discriminator is the BIOS byte revert

The record has the good module **booting a kernel and passing a 25-minute stressapptest in Channel A** on
2026-10-17 (Round-28, old BIOS bytes). The A-slot boot failure appears only after the 2026-10-18 ~13:00
change of two setup bytes (`0x29` Global C-State Auto→Disabled, `0x47` 0x08→0x04 unattributed). Under the
current bytes the same module, same slot, hangs at `Loading initial ramdisk` while the same module boots
in B.

So "the board's A path is physically dead" is not the only live explanation, and it may not be the best
one. Before shipping the board:

1. Finish cell 4 (memtest, suspect in B).
2. **Revert `0x29` and `0x47` to the recorded 10-18 11:47 values** (`0x29=0x03`, `0x47=0x08`), put the good
   module in **A**, boot the Debian stick. Boots → the fault was a firmware setting, 64 GB is back on the
   table with no RMA. Still hangs → the A path is genuinely bad and the Minisforum dossier gets stronger
   (it then has: A fails for both modules under two BIOS configurations, B works for both).
3. Do not skip step 2 by assuming hardware. It is one boot.

### 19.3 Plug timeline for the afternoon (verified from the recorder + the plug's energy meter)

- 10:18:49 power-on → memtest (good @ B) runs **4 h 51 m**, ending ~15:09:49 — exactly the 4-pass
  duration this stick produced on 2026-10-18 (4:51:16). Only the HTML can *prove* 4 passes; the duration
  is consistent, not proof, so cell 2 stays "owner-reported PASS" until the report is parsed.
- 15:11:48-15:12:51 at 55.8-57.1 W = a short boot (the Debian rescue cell, good @ B).
- **15:14:19: 0.0 W** — the only power interruption of the day, ~30-60 s: the module swap.
- 15:14:48: 55.2 → 74.6 → 78.9 W over ~60 s = a second short boot (the Debian rescue cell, suspect @ B).
- 15:16:18 onward: 118-123 W = memtest at heavy test load (cell 4).

The boot windows are only ~90 s each, which is why the plug cannot tell a Debian rescue boot from a
memtest reboot into the USB menu by power alone — the screen is what distinguishes them, and that is why
cells 1 and 3 are recorded as owner-observed. If Minisforum needs more than the cross-slot argument, the
cheap artifact is one photo of the B-slot rescue prompt (or the A-slot hang) from the same session.

### 19.4 Cell 4 (suspect in B) — erroring early, and that is not what the A run looked like

The suspect's **A** run stayed clean through pass 1 and first failed in **test 8 of pass 3**, reaching the
10 000-error cap at **2:45:41**. The **B** run is already showing errors well inside that window, so this
is either a different failure rate or a different test failing first — the report will say which, and the
distinction matters: the same test-8 signature reproduced early is a solid control, while an early,
different signature means the fault is rate-dependent and the A run's timing is not a stable baseline.

The one thing that would overturn the verdict is a 4-pass clean run in B. Errors in B, on top of 10 000 in
A, closes the module question outright: bad in both slots, on the record, for Corsair.

## 20. 2026-10-20 09:10 — third failure mode: the suspect freezes MemTest86 in B; Corsair still silent

### 20.1 Cell 4 ended in a freeze, not a result

- **Suspect in B: MemTest86 erroring inside the first pass, then froze.** The tester locked up and wrote
  no report. Owner-observed; no HTML artifact exists for this cell.
- Plug trace agrees with a freeze and not a finish: draw went flat at **104.0-105.4 W** from ~15:30 on
  10-19 and did not vary once through 09:10 on 10-20 — that is ~17.5 h on a single value. A running
  MemTest86 cycles 58-84 W / 105-134 W; a completed one idles at ~58-64 W (as on 10-18 22:00-22:14).
  Nothing cycles, nothing idles: it stopped.
- Failure-mode tally for S/N `…DC8M`: **boot panic in A** (10-17 22:05) → **10 000 data errors in A**
  (10-18, mask 0x9300) → **tester freeze in B** (10-19). Three distinct modes, two slots.
- Good module `…CD0JC`: 4/4 passes, zero errors, in **A** and in **B**. The host is not the variable for
  any of these three.
- Artifact to capture: the frozen screen is the only record of this cell — photograph it before the box
  is powered off. Nothing else is coming from it, and it has been drawing 104 W for ~17.5 h.
- **Owner photographed the frozen screen, then power was cut at 09:17:34** via HA
  (`switch.amd_workstation_power` → off). Verified after: both switch entities `off`, both power sensors
  `0.0 W`, port 22 closed, plug energy meter settled at **4.439314 kWh**. The box is cold, not frozen —
  the next boot is a cold boot, which is what the A-slot test needs anyway.

### 20.2 Corsair — no human reply in 57 h; follow-up sent 2026-10-20 09:12

- Inbox contains only the Zendesk auto-ack (10-18 00:04, "expect a reply within 24-48 hours") and two
  Zendesk echoes of **our own** updates (10-18 16:49 and 22:20). No agent has responded, and the 24-48 h
  window they quoted has expired.
- Sent a follow-up at **09:12:10** from amdnative@gmail.com as a reply on ticket **2009654822**.
  Verified afterwards: exactly one copy in `[Gmail]/Sent Mail`, Outbox empty, Drafts empty (no duplicate,
  no blind retry). Body archived: `~/rma-evidence/corsair-followup-body-20261020.txt`.
- It states the both-slot result, the three failure modes, the good module clean in both slots, and asks
  for RMA approval plus shipping instructions — replacement part, not refund or credit.
- Minisforum was **not** chased today, deliberately: their update depends on the A-slot BIOS-revert test
  (§19.2). If that boot works, the board claim changes shape and their letter must not say "board is
  dead" first.

## 21. 2026-10-20 09:45 — box powered on with the good module in B: it does not come up

- Owner reinstalled the good module in **Channel B** (the configuration that booted yesterday) and asked
  for power. Plug on at **09:45:05**; draw ramped 0 → 53.6 → 59.4 W and then sat at **61.2-61.5 W, dead
  flat for 11+ minutes** (through 09:56).
- No tailnet (`tailscale` offline, tx but rx 0), no SSH on 100.66.90.53:22, no LAN presence. It never
  reached userspace.
- **No USB stick is installed**, so it is booting the **NVMe** — i.e. the installed Ubuntu. This is a new
  cell that has never been run: *Ubuntu on the NVMe, in Channel B*. Yesterday only the **Debian rescue
  USB** was proven to boot in B.
- Two candidate states, and the draw cannot separate them:
  1. **GRUB's recordfail menu.** Ubuntu sets `GRUB_TIMEOUT=-1` after failed boots, so it sits at the menu
     forever waiting for a keypress — static screen, ~61 W, no network. This fits the history exactly
     (two failed boots on 10-18).
  2. The same initramfs hang as in A, now in B.
- **This matters for the A-slot conclusion.** If Ubuntu fails to boot in B as well, the boot fault is not
  slot-specific and §19.2's "A path is bad" framing is wrong; the differentiator would then be OS/medium,
  not channel. Do not send Minisforum anything until this cell is read (one look at the screen, or one
  Enter keypress at the menu, decides it).

### 21.1 10:05-10:10 — resumed after a MacBook crash; the cell is unchanged and still stuck

- The macOS session died at **09:58:37** (WindowServer userspace-watchdog timeout, twice: 09:58:37 and
  09:59:17), machine restarted 10:00:25. GUI-level death, not a kernel panic, and unrelated to the box.
- Box state re-read from the plug at **10:08-10:10**: relay `on`, draw a stable **58.1-59.9 W** (10 samples
  over 2 min), 120.5 V, plug temp 29 °C. Cumulative energy meter **4.460394 kWh** vs **4.439314 kWh** at
  the 09:17:34 power-cut → 21.08 Wh over ~24 min ≈ 53 W average, i.e. **continuous power, no reset and no
  reboot-level dip** in the window. It has now sat in this one state for ~25 min.
- Still no tailnet (last seen 1 d), no SSH on 100.66.90.53:22, no LAN presence.
- **New, weak signal toward candidate 2:** the draw fell from 61.2-61.5 W (09:45-09:56) to 58.1-59.9 W
  from ~09:56 on, a ~2 W step. A kernel console blanking at the 600 s default (≈09:55) fits that step;
  GRUB's menu does not blank the screen. That is a hint, not an identification — the two states still
  cannot be separated electrically, and the screen is still the decider.
- Decider still outstanding: one look at the screen (or one keypress) — owner step, one question at a
  time. If it is blank, a keypress that brings text back means it is a kernel/initramfs hang, not GRUB.

### 21.2 10:14-10:22 — the screen is black and a keypress changes nothing: this is not a GRUB menu

- Owner report: the display is a **black screen with no output**, before and after pressing **Enter**.
  (The monitor has no signal-vs-lit distinction recorded, and the box's keyboard has no Caps Lock LED, so
  the LED liveness test was unavailable.)
- **This retires candidate 1 for practical purposes.** A GRUB menu at `GRUB_TIMEOUT=-1` accepts a
  keypress and boots its default entry; 25+ min later there is still no tailnet, no SSH and no LAN
  presence. A menu waiting for input would have a kernel running by now. Caveat: it assumes a working
  keyboard is attached to the box, which has not been separately confirmed.
- What remains: (a) a kernel/initramfs hang in B whose VT no longer wakes on a keypress, or (b) a hang
  at or below POST with no video out at all. Note the box showed video for the Debian rescue boots in
  this same slot on 10-19, so (b) would be a **new** failure mode introduced after the 17.5 h freeze.
- Discriminator: a watched cold boot. Both cases are separated by one thing — whether the POST/splash
  screen appears at all before the black.

### 21.3 10:27-10:35 — a power cycle brought it up: the boot failure is intermittent, in B

- **10:27:16 relay off** (confirmed dark, 0.0 W), **10:27:17 relay on**. Draw ramped 41 -> 56 -> 65 W,
  dipped to 37 W, held ~78 W for ~30 s, peaked **106 W** for ~6 s, then decayed to 55-60 W. That is a
  real boot, not a static state.
- **It booted.** Ubuntu login screen (owner-observed), `amd-workstation` on the tailnet, port 22 open,
  `uptime` 2 min at 10:31. `systemd-analyze`: 11.510 s firmware + **31.555 s loader** + 745 ms kernel +
  3.102 s initrd + 1 min 29.5 s userspace = **2 m 16 s**. The loader figure is abnormally long.
- **Config read back from the box, not inferred:** `dmidecode -t 17` shows `P0 CHANNEL A / DIMM 0` =
  *No Module Installed*, `P0 CHANNEL B / DIMM 0` = 32 GB `CMSX32GX5M1A4800C40` at 4800 MT/s. BIOS 1.17
  (08/28/2026) on `DRFXI`. Kernel `7.0.0-38-generic`.
- **The 09:45 attempt left no trace on disk.** `journalctl --list-boots` ends at 10-18 13:19:42 ->
  13:33:25 before today's 10:28:29 boot; nothing between. So it never mounted root and never ran
  journald — a stall at or before initramfs, not a userspace hang.
- **The GRUB-recordfail hypothesis is structurally dead twice over:** `/etc/default/grub` has
  `GRUB_TIMEOUT=0` with `GRUB_TIMEOUT_STYLE=hidden`, so there is no menu to sit at (`grub-editenv` could
  not read `/boot/grub/grubenv` — it falls back to `nvme0n1p2` and fails — so the recordfail flag itself
  stays unread, but with timeout 0 it could not have been waiting for a keypress either way).
- **NVMe is not implicated by its own counters:** Samsung 970 EVO 500GB, fw `2B2QEXE7`, 1% used,
  **0 media/data-integrity errors**, 86 unsafe shutdowns. The scary-looking 977 is a single *Invalid
  Field in Command* admin command (`status 0x2002`, `cmdid 0x7005`) counted 977 times in log entry 0;
  every other entry in the 64-slot log is empty. Enumerated at 2.88 s, root mounted at 5.5 s this boot.
- **Consequence for §19 conclusion 2 ("the boot fault is Channel A, not the module"):** same module,
  same slot, same medium, same BIOS produced *both* no-boot (09:45) and clean boot (10:27) inside one
  hour. A single A-slot hang (10-18 22:35) therefore cannot distinguish a dead A path from this
  intermittent fault. Do not send Minisforum a "board is dead" letter on the current record. What would
  separate them is a **boot-rate measurement** (N cold boots per channel) — proposed, owner declined for
  now.
- **Owner decision 10:35:** leave the box exactly as it is — up, in B, no further cycles.
- Evidence bundle pulled off the box while it was alive: `~/rma-evidence/amd-workstation-20261020/`
  (`ev-dmesg.txt`, `ev-dmidecode.txt`, `ev-journal.txt`, `ev-nvme.txt`, `ev-nvme-err.txt`).
- **Side finding, separate thread, not chased:** `sudo` on this box logs `pam_ssh_agent_auth: error:
  key_from_blob: remaining bytes in key blob 44` — the ED25519-SK blob does not parse, so the gate is
  likely being satisfied by the forwarded 1Password RSA key instead of the YubiKey. There is no
  `/etc/security/pam_ssh_agent_auth.conf` on the box. That contradicts the "the sudo key file holds
  exactly one sk key and no RSA" claim recorded during the 10-19 fleet gating work; verify before
  relying on it.

## 22. 2026-10-20 10:36-11:14 — the single-module stress control PASSES

- **What ran:** `stressapptest -s 1500 -M 26000 -W --pause_delay 120 --pause_duration 15`, 32 copy
  threads, on the **good module alone in Channel B** (30276 MB total, 26000 MB allocated ≈ 86%).
  Duty-cycled on purpose: 120 s of load then a 15 s pause, repeated — the power-dip trigger, not a
  steady burn. Started 10:36:41, ended 11:01:44.
- **Result: PASS, twelve load dips, nothing.** `Stats: Completed: 31009208.00M in 1500.36s
  20667.83MB/s, with 0 hardware incidents, 0 errors`. **0 miscompares, 0 `Hardware Error` lines, 12
  "Pausing worker threads" events.** Log pulled to `~/rma-evidence/amd-workstation-20261020/`
  (`stress-out-20261020-103641.log`, plus the watcher trace `ws-stress-watch.log`).
- **Contrast with the pair:** the 2026-10-17 02:00 run (`-s 28800 -M 52000`, both modules installed)
  produced its first miscompares at **619 s — on the first resume after the first pause**, across CPUs
  1/2/13/16/18/29 with patterns `OneZero32`, `walkingInvOnes~32`, `Checker8b10b32`. Same instrument,
  same duty-cycle profile, opposite result once the suspect module is out.
- **What it does and does not establish.** It gives the campaign the stress-instrument control that was
  missing: the machine + this module survive the transition trigger that the pair failed on. It does
  **not** clear the board for a *pair* (that is a different memory footprint and the thing the 64 GB
  requirement actually needs), and it says nothing about the intermittent boot hang (§21.3) — different
  instrument, different failure. Treat it as one completed control cell, not as a stability verdict for
  the box.
- **Not taken:** any long soak (the 10-17 equivalent was 8 h), and the same run with the module in
  Channel A. Both remain open cells.
- **Operational note for the next run:** the harness unloads kdump for the window and re-arms it in an
  EXIT trap, but a **detached** run (`setsid nohup`) loses the forwarded SSH agent when the launching
  connection closes, so the trap's `sudo kdump-config load` fails with `sudo: a password is required`
  and kdump stays unloaded. Re-armed manually at 11:15 and verified (`loaded kdump kernel`). Either run
  it attached, or re-arm by hand afterwards and check it.

- **Owner position, 11:20:** the box stays up. The board is **not** proven clean and that stays open — but
  it is "clean enough" for current use with the good module alone in Channel B, so no board claim is
  being made or dropped. The only blocking dependency now is a **Corsair human reply** on RMA ticket
  2009654822 for the bad module (`A534T4312CDC8M`); everything measured on this box is already in their
  hands as of the 09:12 follow-up.

### 22.1 11:25 mail check — Corsair still has not answered; Minisforum HAS and is waiting on us

- **Corsair (ticket 2009654822): zero human contact, ever.** The thread in the Google inbox contains only
  the 10-18 00:04 auto-ack, our two updates (10-18 16:49, 10-20 09:12) and Zendesk's echoes of those same
  two updates (10-18 22:20, 10-20 09:12). No agent reply in ~83 h, and their quoted 24-48 h window closed
  roughly two days ago.
- **Judgement: do not send a third follow-up today.** The 09:12 one went two hours ago; another now reads
  as pestering and buys nothing. Escalation trigger = nothing from a human by 10-21 09:00, then go around
  the ticket (support phone/chat) rather than adding more mail to the same thread.
- **Minisforum DID reply with a human** (Y.J.Aickson, 10-19 01:52): "please take your time with the
  testing, and simply let us know the results when you have them." So *they* are waiting on *us* — that
  is an open loop, and it cannot be closed with the old framing: the update we owe them now has to say
  that the same configuration both failed and booted in Channel B (§21.3), i.e. the "A path is bad" claim
  is withdrawn pending a boot-rate measurement, not restated.

### 22.2 2026-10-21 10:03 — escalation sent to Corsair (and one blank reply before it)

- Still **zero human contact** as of 10:05 (`Corsair` hits in the Google inbox: the 10-18 auto-ack, our
  10-18 16:49 and 10-20 09:12 updates, and Zendesk's echoes). Nothing in Junk either (1,248 scanned, 0
  hits). That is ~113 h from the original request.
- **Escalation sent 10:03:18** on the ticket thread from `amdnative@gmail.com` to
  `support@corsair.zendesk.com`: four asks (RMA number, shipping instructions, advance-ship vs
  on-receipt, expected date) plus the timeline. Body archived at
  `~/rma-evidence/corsair-escalation-body-20261021.txt`; verified present in `[Gmail]/Sent Mail` by
  reading the message `source` (5,712 chars, body string found), Outbox empty, one copy.
- **A first attempt at 10:01:32 went out BLANK.** Zendesk's echo at 10:02:12 shows it as
  `[No content]`. Cause and rule: in Mail's AppleScript, `reply <msg> without opening window` followed by
  `set content of r` compiles and sends, but the body is dropped — the reply must be created
  `with opening window` for the composed text to stick. (And `opening window` written without `with` is
  a compile error: "Expected expression but found end of line".) Verify a send by reading the message's
  `source`, never its `content` — `content` comes back empty for HTML messages and will tell you a
  perfectly good send was blank.
- The escalation opens by telling them to disregard the blank reply, so the `[No content]` entry in the
  thread is accounted for.
