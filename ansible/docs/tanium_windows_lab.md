# Windows TS/TMS/TZS/SQL lab (Ansible)

Repeatable, idempotent Ansible replacement for the manual/VNC-driven
build of a Windows-based Tanium Server + Module Server + Zone Server +
SQL lab in the Proxmox homelab. Grew out of a hands-on case1 SQL-restore
investigation (2026-08-20) where the manual build hit a real Windows/AD
limitation and needed a domain — see "Why the AD domain exists" below.

## Two playbooks — pick the right one

- **`provision_tanium_windows_lab.yml`** — the clean-lab path. Every
  database it creates is brand new. **Never touches customer data.**
  Use this for ordinary Tanium-lab work with no customer backup
  involved.
- **`provision_tanium_windows_lab_with_customer_db.yml`** — everything
  in the clean-lab playbook PLUS one inserted play
  (`tanium_lab_restore_customer_db`) that restores a customer's `.bak`
  into the target SQL Server, with real identity-based safety checks,
  BEFORE the Tanium Server install runs against it. Use this ONLY when
  the explicit goal is reproducing something against a customer's real
  data.

These were split into two playbooks 2026-08-21 after a real incident
(see below) where a parameter mistake in the single combined playbook
silently dropped and recreated a customer's restored production
database. **Never add a customer-DB-restore step to the clean-lab
playbook "just this once"** — that blurring of the two paths is exactly
what caused the incident. If you need customer-DB behavior, use the
second playbook; if you're touching the clean-lab playbook, keep it
customer-data-free.

## Prerequisites

- Template VMID 9000 (`template-win-server-2022`) must exist, built via
  `build_windows_template.yml` + `docs/windows_template_guide.md`
  (sysprep `/generalize /oobe /shutdown`, then converted to a template).
  If the template wasn't re-sysprepped after later changes, clones can
  boot stuck mid-OOBE — the `tanium_windows_vm_clone` role has a
  defensive fix for this, but a properly-sysprepped template is the real
  fix.
- `microsoft.ad` and `ansible.windows` collections (see
  `requirements.yml`; `ansible-galaxy collection install -r
  requirements.yml`).
- `vault_win_admin_password`, `vault_tanium_lab_dsrm_password`,
  `vault_tanium_lab_svc_password`, `vault_tanium_lab_sql_sa_password` in
  `group_vars/all/vault.yml`.
- macOS control machine: export `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`
  before any `ansible-playbook` run that touches a `winrm` host — see
  "macOS WinRM worker crash" below.
- The Tanium Server/Module Server/Zone Server installer `.exe` files and
  a `tanium.license` for the target version, downloaded separately (see
  Usage below for how to pass their paths in).

## Why the AD domain exists

Tanium Server's silent installer needs a Windows-authenticated SQL login
for a *remote* SQL Server (`/SQLServerName=... /DBUserName=...
/DBUserDomain=... /DBUserPassword=...`). `CREATE LOGIN ... FROM WINDOWS`
resolves the account's SID via a cross-machine LSA/SAM lookup that has no
trust path between two WORKGROUP machines. Confirmed by hands-on repro
2026-08-20: matching local accounts with identical username+password,
the "Network access: Allow anonymous SID/Name translation" policy,
`RestrictAnonymousSAM`, null-session pipes, and even running SQL Server's
own service as the matching local account all failed with the same
"Windows NT user or group not found" (SQL error 15401) — this is a hard
Windows/SQL Server limitation, not a config gap. Standing up a
lightweight AD domain (`tanium.lab`) and joining both boxes fixed it
immediately (same command, no other changes). A fully local SQL Server +
Local System combo on a single host doesn't need a domain at all — see
`tanium_server_install`'s role header for that alternative.

## Role summary

| Role | Purpose |
|---|---|
| `tanium_windows_vm_clone` | Clone the win-server-2022 template, assign static IP, rename, wait for WinRM. Also auto-dismisses the OOBE product-key screen (see "Known gaps"). |
| `tanium_lab_ad_domain` | Promote the first DC of `tanium.lab`, or join a member server to it. |
| `tanium_lab_service_account` | Create the domain service account used as the Tanium Server's DB identity. |
| `tanium_lab_sql_install` | Install the SQL Server 2022 engine itself + the modern `sqlcmd` client (no role did this before 2026-08-22 — every SQL box had been manually pre-built). |
| `tanium_lab_sql_login` | `CREATE LOGIN ... FROM WINDOWS` + grant sysadmin, for one or more accounts. |
| `tanium_lab_restore_customer_db` | **Customer-DB playbook only.** Identity-checked, guarded restore of a customer `.bak`. |
| `tanium_server_install` | Silent-install Tanium Server (NSIS `/S` + real params, verified against source). Runs its DB-create/upgrade and admin-user steps under two different confirmed-correct Windows identities — see "Validated" below. |
| `tanium_moduleserver_install` | Silent-install Tanium Module Server, register against the Server. |
| `tanium_zoneserver_install` | Silent-install Tanium Zone Server (fetches its own key file automatically). |

All roles are idempotent (safe to re-run after a partial failure) via a
`win_stat`/registry/SQL-existence check before doing anything.

## Installer silent-mode parameters

NSIS installers for this platform have **no `/?` help and are not
documented on help.tanium.com** for silent/scripted use (the public docs
only cover the interactive wizard). The parameters used by these roles
were verified directly against the installer source
(`Projects/Tanium/Win/Installer/{server,moduleserver,zoneserver}.nsi`,
platform repo tag `version/7.8.2.1000`) on `platdev-jump`, not guessed
against the compiled binary. See each role's task-file header comment
for the full parameter reference and any per-installer gotchas (e.g. the
Module Server's registration password must go through a temp file via
`/RegisterAdminPassFile=`, not an inline CLI arg — there isn't one).

## macOS WinRM worker crash

Running these roles from a Mac against `ansible_connection: winrm` hosts
can fail with `[ERROR]: A worker was found in a dead state` and no
traceback. This is a macOS-only crash in ansible-core's WinRM connection
worker process (Objective-C runtime fork-safety check triggered by
`requests`/`urllib3` having already touched CoreFoundation state before
the worker forks) — confirmed 2026-08-20, not a WinRM or network problem
(raw `pywinrm` works fine without it). Fix:

```bash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
```

before any `ansible-playbook` invocation that touches a WinRM host.

## Real incidents this session (2026-08-20) — read before running

**DB drop/recreate incident (high severity, recovered).** The first live
run of `tanium_server_install` against a SQL Server that already had a
correct, freshly-restored customer database was missing
`/UseSQLServer=1` and had `/UseExistingDB=0`. Without `/UseSQLServer=1`,
`$UsePostgres` (an NSIS `Var`, default empty string, not `"0"`) never
gets forced to `"0"`, so the installer's driver-check silently takes the
Postgres branch even for a declared SQL Server target; combined with
`/UseExistingDB=0`, it unconditionally dropped and recreated the
database. Recovered by re-running `RESTORE DATABASE ... WITH REPLACE`
from the original `.bak` (still present on disk) — no permanent data
loss, but this could have been. Both parameters now default safely in
`tanium_server_install` (`/UseSQLServer=1` always set; `/UseExistingDB`
defaults to `1` via `tanium_use_existing_db`). Treat `/UseSQLServer=1`
as load-bearing for every SQL Server target, and treat
`tanium_use_existing_db: 0` with the same caution as `DROP DATABASE`.

**msiexec hang inside SetupServer.exe (medium severity, worked around).**
The installer's SQL Native Client / Command Line Utilities download step
(`nsExec::ExecToStack` calling `msiexec /i ... /qn`) was observed to hang
indefinitely — near-zero CPU, no new Windows Installer event-log
entries — regardless of interactive-session vs Session-0 launch context.
A manual `msiexec /i ... /qn /norestart` of the identical already-downloaded
`.msi` completed in seconds. Root cause undetermined (likely an IPC/pipe
issue specific to `nsExec::ExecToStack`'s stdout capture, not a
session-isolation problem as originally suspected). Fix: `tanium_server_install`
now pre-installs both MSIs directly via `win_shell` + `Start-Process -Wait`
BEFORE running `SetupServer.exe`, so `CheckForSQLDrivers` finds them
already present and the hanging code path is never reached at all.

**WinRE boot-loop on reboot (medium severity, worked around).** Any VM
cloned from `template-win-server-2022` inherits `boot=order=ide2;virtio0`
with the original Windows Server install ISO still attached — any
reboot (not just first boot) can boot off that ISO instead of the disk,
landing in WinRE ("Choose your keyboard layout") instead of normal
Windows. Hit on 2+ separate VMs from ordinary `Restart-Computer`/`win_reboot`
calls. `tanium_windows_vm_clone` now unconditionally ejects the ISO and
fixes boot order every run; the template itself and all pre-existing
CASE1 VMs were fixed in place too. **Once WinRE has been entered, a plain
reboot/reset re-enters WinRE again even with boot order already
correct** — bootmgr's failure counter needs a genuine cold cycle
(`qm stop <vmid>` then `qm start <vmid>` via the Proxmox API, not
`qm reset` and not another `win_reboot`). Also: WinRE's `winre.wim`
commonly lacks the VirtIO storage driver even though the real installed
OS has it fine — `diskpart > list disk` inside WinRE reporting "no fixed
disks" is a WinRE-environment limitation, not evidence of real disk
corruption; don't chase disk-repair paths, just cold-cycle the VM.

**Unattended reinstall aborted mid-run, service left uninstalled
(high severity, recovered, 2026-08-21).** Something re-ran
`SetupServer.exe` against an already-working win-ts-case1-01 hours after
the earlier incident above was thought fully resolved (root trigger
never conclusively identified). The re-run correctly used the fixed
`/UseSQLServer=1 /UseExistingDB=1` parameters and successfully upgraded
the database, but then failed at the separate
`TaniumReceiver.exe database create-admin-user` step with "Login failed
for user 'DOMAIN\HOSTNAME$'" and aborted BEFORE installing the Windows
service — leaving Tanium Server completely uninstalled (files present,
no service, despite the DB upgrade having already succeeded). Two real
bugs found and fixed:
  - `create-admin-user` authenticates to SQL as the Tanium Server host's
    own COMPUTER ACCOUNT (`DOMAIN\HOSTNAME$`), not the `DBUser*`
    service account passed on the command line — it had no SQL login
    at all. `tanium_lab_sql_login` now grants sysadmin to both the
    domain service account and the Server's computer account (both
    playbooks' SQL-login play was updated).
  - The same aborted run had already deleted `SOAPServer.key`/`.crt`
    (removed as part of the upgrade's own cleanup, never regenerated
    since the abort happened before that step) — after manually fixing
    the SQL login and re-running the remaining install steps by hand,
    the service installed and even briefly reported "Running" before
    crashing on startup with "Error initializing private keys ...
    SOAPServer.key ... file specified." `tanium_server_install` now
    detects and regenerates missing cert/key files via
    `KeyUtility.exe selfsign`, and re-verifies the service is STILL
    running 15 seconds after start (not just that `Start-Service`
    returned success) — `TaniumReceiver.exe` file existing was also
    found to be a bad completion signal (extracted early, well before
    the service is actually installed), replaced with a real
    `win_service_info` check.
  - Recovered by hand: granting the computer account sysadmin,
    regenerating the cert/key with `KeyUtility.exe selfsign`, and
    manually re-running `-i` (install service) + setting the service
    account + `Start-Service`. Customer database was never at risk this
    time (`/UseExistingDB=1` correctly upgraded rather than dropped it).
  - This incident is also what prompted splitting into two playbooks
    (see "Two playbooks" above) — the user's read after this was "we
    might need two roles then... one that just installs a clean
    TS/TMS/TZS/SQL/DC for Windows labbing, and one that does that but
    also restores a customer's DB," to keep clean-lab runs structurally
    incapable of touching customer data by omission, not just by
    parameter discipline.

**Database naming — SetupServer.exe cannot be pointed at a custom DB
name (confirmed 2026-08-21).** The real, source-verified parameter list
for `SetupServer.exe` has no database-name override — every live
install this session targeted a database literally named `tanium`.
`tanium_target_db_name` in the customer-DB playbook controls what
`tanium_lab_restore_customer_db` restores into and what
`tanium_server_install`'s safety pre-flight check queries, but does NOT
get passed to the installer itself (there's no parameter to pass it
to). If two investigations ever need to coexist on the same SQL Server
with genuinely separate Tanium databases, that needs separate SQL
Server instances or boxes, not just a different database name under the
default instance — unverified, re-check `/SQLInstance` in source before
relying on this.

## Usage

### Clean lab (no customer data)

```bash
cd ~/repos/homelab
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible-playbook \
  -i ansible/inventory/proxmox.yml ansible/provision_tanium_windows_lab.yml \
  -e tanium_setup_server_exe_local_path=~/Downloads/tanium_7.8.2.1136/SetupServer.exe \
  -e tanium_setup_moduleserver_exe_local_path=~/Downloads/tanium_7.8.2.1136/SetupModuleServer.exe \
  -e tanium_setup_zoneserver_exe_local_path=~/Downloads/tanium_7.8.2.1136/SetupZoneServer.exe \
  -e tanium_license_local_path=~/Downloads/tanium_7.8.2.1136/tanium.license
```

### With a customer's restored SQL backup

```bash
cd ~/repos/homelab
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible-playbook \
  -i ansible/inventory/proxmox.yml ansible/provision_tanium_windows_lab_with_customer_db.yml \
  -e tanium_setup_server_exe_local_path=~/Downloads/tanium_7.8.2.1136/SetupServer.exe \
  -e tanium_setup_moduleserver_exe_local_path=~/Downloads/tanium_7.8.2.1136/SetupModuleServer.exe \
  -e tanium_setup_zoneserver_exe_local_path=~/Downloads/tanium_7.8.2.1136/SetupZoneServer.exe \
  -e tanium_license_local_path=~/Downloads/tanium_7.8.2.1136/tanium.license \
  -e tanium_customer_bak_local_path=/path/to/customer/backup.bak
```

`tanium_lab_restore_customer_db` will refuse to run (loudly, with no
override flag) if the target database already exists without this
exact backup's identity marker — see that role's task-file header for
the full safety design. This playbook has NOT yet been run end-to-end
in one pass against a fresh clone — the underlying restore logic is
new, unlike the individual install steps it wraps (see "Validated"
below for what has actually been exercised for real).

Zone Server's key file (`tanium-init.dat`) needs no manual step — see
`tanium_zoneserver_install`'s role header — it's fetched automatically
from the Tanium Server box as long as the Server install ran first
(the play ordering above already guarantees this).

To build a fresh set of VMs for a different case, copy the
`tanium_windows_lab` inventory group in `inventory/proxmox.yml` (new
VMIDs, new `ip_win_*_case` vars in `group_vars/all/vars.yml`) rather than
overwriting the case1 entries in place.

## Validated (2026-08-22 — clean-lab playbook confirmed fully working end-to-end)

**`provision_tanium_windows_lab.yml` completed a genuinely clean, fully
unattended run from absolute scratch** — all 5 VMs destroyed and
recloned, zero manual intervention of any kind (no VNC clicking, no
manual registry edits, no hand-run commands) — with every host reporting
`failed=0`. Directly verified afterward: all 5 services genuinely
Running (AD `NTDS`/`Netlogon`, `MSSQLSERVER`, `Tanium Server`,
`Tanium Module Server`, `Tanium ZoneServer`). This is the first time
this playbook has been proven end-to-end, not just per-component.

Getting to that clean run required finding and fixing a real chain of
bugs — each confirmed via live testing before moving to the next (see
git log `d8479f2..HEAD` on `ansible/` for every commit referenced
below):

1. **OOBE "enter product key" screen blocks every fresh clone
   indefinitely** (`6e51a6a`, `73bf333`, `e303f3a`) — the
   `template-win-server-2022` template's sysprep was run with no
   `unattend.xml`, so it carries no embedded product key; every fresh
   clone stops on this screen with no timeout ever resolving it. Interim
   fix: `tanium_windows_vm_clone` now auto-dismisses it via the same
   VNC-bridge technique used for manual template work
   (`files/pve_vnc_bridge.py` + `files/vnc_click.sh`), bounded to 12
   attempts 30s apart, checking the existing OOBE readiness gate between
   clicks. **The correct long-term fix — baking a KMS client setup key
   into the template's answer file so this screen never appears at all —
   is not yet done; see "Known gaps" below.**
2. **Proxmox clone storage-lock contention** (`f11c2d3`) — cloning all 5
   VMs in the same play (Ansible's default parallel execution) fires all
   5 `qm clone` invocations at the same storage backend simultaneously;
   Proxmox's own locking rejects the losers with `got timeout`. Genuine
   transient contention, not a permanent failure — fixed with a bounded
   retry instead of serializing the whole play.
3. **SQL Server's own update-search step fails via WinRM** (`2bf382d`) —
   without `/UpdateEnabled=False`, `setup.exe` defaults to checking
   Windows Update before installing, which throws Access Denied over
   this WinRM session. Disabled explicitly (also just faster/more
   deterministic for a disposable lab install).
4. **SQL Server setup.exe needs a real logon, not bare WinRM**
   (`6acc301`, `3f8544c`) — `setup.exe` DPAPI-encrypts saved
   passwords under `CurrentUser` scope while writing its config XML.
   WinRM/Negotiate is a network logon (type 3) with no loaded user
   profile and no DPAPI master key, so the encrypt call throws
   `CryptographicException: Access is denied`. Fixed by launching via a
   scheduled task with `LogonType=Password` (`/RU` + `/RP`, not a
   passwordless/S4U task, which still lacks the credential material
   DPAPI needs) — and separately, `.\Administrator` (the usual
   local-account `schtasks` syntax) fails on a domain-joined box with
   "No mapping between account names and security IDs was done"; the
   box's real hostname (`WIN-SQL-CASE1\Administrator`) works.
5. **`win_shell` mishandles a piped `Out-Null` over WinRM** (`bbe3cac`) —
   a raw multi-statement `-Command` string containing `| Out-Null` fails
   with `'Out-Null' is not recognized as an internal or external
   command`, even though the identical command succeeds via `qm guest
   exec` and via `-EncodedCommand`. Looks like an argument-marshalling
   quirk specific to this WinRM session, not a real PowerShell/pipe
   problem. Sidestepped with `$null = ...` instead of `| Out-Null`.
6. **`pki show` needs a real loaded profile too** (`0d83906`, `7d1ad42`)
   — same DPAPI/network-logon class of problem as SQL Server's own
   installer: `TaniumReceiver.exe pki show` consistently (not
   intermittently — confirmed by failing 5 retries with 15s delays,
   twice) fails over WinRM with "Failed to connect to database," while
   the identical command via `qm guest exec` (SYSTEM identity, no WinRM)
   succeeds immediately every time. `tanium_moduleserver_install`'s TLS
   fingerprint lookup now uses `qm guest exec` instead of WinRM.
7. **`vncdo` can hang forever** (`cb93781`) — caught live as a genuinely
   stuck process (11+ minutes, never returned) that stalled an entire
   playbook run across all 5 VMs (parallel host execution meant one hung
   click attempt blocked the whole play). `vnc_click.sh` now wraps the
   `vncdo` invocation in a hard `timeout 20`.
8. **Circular `ansible_host`/`tanium_server_ip` reference for the
   co-located Zone Server Hub** (`52c0fd2`, ported to the customer-DB
   playbook in `c33933f` after a manual review caught it there too) —
   the "Install the Zone Server Hub" play runs on the same host as the
   Tanium Server and set `tanium_server_ip: "{{ ansible_host }}"` as a
   play-level var, but the role's own tasks also set
   `ansible_host: "{{ tanium_server_ip }}"` as a task-level var for
   their WinRM override. Jinja can't resolve the resulting cycle within
   the same host context and fails with "Recursive loop detected in
   template: maximum recursion depth exceeded." Fixed by referencing
   the raw `ip_win_ts_case1` inventory variable directly instead of the
   `ansible_host` alias that's also being overridden downstream.
9. **Native-vs-WOW64 registry hive split for Tanium Server's DB config**
   (`ab7683f`, hardened in `0b9d097`) — `SetupServer.exe` only ever
   writes the DB connection config (`SQLConnectionString`, `DBUserName`,
   `DBUserDomain`) to the WOW64-redirected registry view
   (`HKLM:\SOFTWARE\Wow6432Node\Tanium\Tanium Server`), but the
   genuinely 64-bit `TaniumReceiver.exe` service reads the NATIVE view
   (`HKLM:\SOFTWARE\Tanium\Tanium Server`) at startup. Invisible
   immediately after a fresh install (the installer's own in-process run
   happens to work), but any later reboot spins up the real service
   fresh, it reads the empty native hive, and the server loops forever
   on "Failed to connect to database" even though SQL/network/firewall
   are all fine. Fixed by syncing the DB connection keys into the native
   hive too, gated on a check of **all three** keys (not just one) so a
   hypothetical partial prior sync can't silently look "done" forever.
10. **`TaniumReceiver.exe`'s DB-create/upgrade + `database
    create-admin-user` steps need specific, DIFFERENT identities**
    (`561a106`, the core of the fully-remote install) — confirmed via 3
    independent live data points: WinRM = Access Denied;
    scheduled-task-with-password-but-no-real-login = DLL init crash
    (`0xC0000142`); the DB-upgrade step specifically needs to run as the
    domain service account (`TANIUM\taniumsvc`, needs `SeBatchLogonRight`
    granted via `secedit` + local Administrators membership, both now
    done automatically), while `create-admin-user` specifically needs
    `NT AUTHORITY\SYSTEM` (fails as `taniumsvc` with "login is from an
    untrusted domain"). `tanium_server_install` now runs each sub-step
    under its confirmed-correct identity and finishes the remaining
    steps (cert regen, service install, service-account-set, start)
    manually when `SetupServer.exe` itself aborts partway through at the
    `create-admin-user` boundary — this is a fully remote fix, no
    interactive/console/VNC/RDP session used anywhere in this sequence.
11. **KeyUtility.exe needs its sibling DLLs, and its own DB-connectivity
    dependents needed real fixes too** (`6c285b5`, `d8479f2`,
    `cc8ce4f`) — a Module Server install never ships `KeyUtility.exe`
    (only Tanium Server/Zone Server do); fetching just the one binary
    from the Server box crashes with `STATUS_DLL_NOT_FOUND` since it
    dynamically loads `libcrypto-3.dll`/`libssl-3.dll` from its own
    directory. Fixed by fetching the whole sibling-DLL set, transferred
    via a local temp file + `win_copy` rather than a base64 command-line
    argument (which fails past ~8191 characters — fine for the small
    `tanium-init.dat`, not for a real compiled binary).
12. **The SQL Server engine itself was never installed by any role**
    (`d8479f2`, `cc8ce4f`) — every prior session's testing had reused a
    manually pre-built SQL box; `tanium_lab_sql_login` only ever managed
    logins on an *already-present* instance. `tanium_lab_sql_install` now
    closes that gap: downloads SQL Server 2022 Developer Edition media
    directly via Microsoft's small self-downloading SSEI bootstrapper (a
    pre-staged ISO failed to mount cleanly over this Proxmox/VM's IDE
    CD-ROM emulation — not worth fighting, guest internet access works
    fine), then installs the modern Go-based `sqlcmd`
    (`github.com/microsoft/go-sqlcmd`, queried via the GitHub API for the
    current release rather than guessing a URL).

**Not yet re-validated end-to-end: `provision_tanium_windows_lab_with_customer_db.yml`.**
Every individual step it wraps (SQL install, Tanium Server install
against an existing DB, Module Server, Zone Server) is now proven via
the clean-lab playbook's successful run, and the customer-restore role's
own identity-guarded logic was reviewed and had one real bug fixed
(the same Hub circular-reference crash as the clean-lab playbook, ported
in `c33933f`) — but the playbook has never actually been run start-to-
finish this session, because no customer `.bak` has been re-sourced yet
(see "Known gaps"). Treat it as "believed correct, lint/syntax-clean,
each component proven individually" rather than "proven end-to-end"
until that real run happens.

## Known gaps / follow-up work

- ~~**Template lacks a baked-in Windows product key**~~ — **FIXED,
  2026-08-22.** Template VMID 9000 was rebuilt with
  `vault_windows_server_2022_mak` baked into its `unattend.xml`
  `ProductKey` field (specialize pass) and re-sysprepped — see
  `windows_template_guide.md`'s "Sysprep and Template Conversion"
  section for the exact procedure and the new
  `bake_product_key_into_template.yml` one-shot playbook. Confirmed via
  TWO independent from-scratch clone tests (one from the intermediate
  rebuild VM, one from the final swapped-in VMID 9000 itself) that OOBE
  now reaches `IMAGE_STATE_COMPLETE` with genuinely zero manual
  intervention — no VNC, no clicks, the product-key screen never
  appears at all. `tanium_windows_vm_clone`'s auto-click workaround
  (fix #1 above) is kept in place as a defense-in-depth safety net
  (gated behind a pre-check that skips it entirely when OOBE already
  reports ready, which is expected on every clone from here on) in
  case a future template rebuild ever regresses this fix.
- **Customer-DB playbook not yet run end-to-end** — needs a customer
  `.bak` re-sourced first (the original was lost to an earlier VM-254
  destroy incident; the user confirmed another copy exists elsewhere but
  it has not yet been supplied to this environment).
- Intermittent Proxmox-host-level guest-agent flakiness (VMs 254/255/258
  observed going briefly unresponsive to `qm guest exec` mid-session,
  independent of any Ansible role logic) was seen repeatedly this
  session but never blocked a full run once the above fixes landed —
  worth keeping an eye on if a future run stalls at a guest-agent-wait
  task with no obvious cause; it has self-resolved every time so far.
