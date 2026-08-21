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
| `tanium_windows_vm_clone` | Clone the win-server-2022 template, assign static IP, rename, wait for WinRM. |
| `tanium_lab_ad_domain` | Promote the first DC of `tanium.lab`, or join a member server to it. |
| `tanium_lab_service_account` | Create the domain service account used as the Tanium Server's DB identity. |
| `tanium_lab_sql_login` | `CREATE LOGIN ... FROM WINDOWS` + grant sysadmin, for one or more accounts. |
| `tanium_lab_restore_customer_db` | **Customer-DB playbook only.** Identity-checked, guarded restore of a customer `.bak`. |
| `tanium_server_install` | Silent-install Tanium Server (NSIS `/S` + real params, verified against source). |
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

## Validated (2026-08-20)

End-to-end tested against a disposable VM (259, torn down after): clone,
resize, start, guest-agent wait, OOBE-unstick, static-IP assignment, and
WinRM-reachability all confirmed working from a cold template clone.

All three Tanium components were manually installed successfully against
the live case1 investigation VMs using the exact parameter sets now baked
into their respective roles:

- **Tanium Server** (win-ts-case1-01): `Get-Service 'Tanium Server'`
  Running, `TaniumReceiver.exe` alive, port 443 listening, target
  database's `version_history` table correctly gained a new row
  (upgrade, not drop/recreate) — confirmed via the actual Tanium Console
  UI (login succeeded, real customer historical data visible, branding
  intact).
- **Tanium Module Server** (win-tms-case1-01, fresh clone after the
  original VM hit an unrecoverable WinRE loop — see incident below):
  `Get-Service 'Tanium Module Server'` Running, `TaniumModuleServer.exe`
  alive. Registration against the Server via `TaniumModuleServer.exe
  register ... --pass-file` failed with `class InvalidBase64` /
  `Failed to parse protected data from string` regardless of whether the
  password file was plaintext, base64, or PowerShell DPAPI-protected —
  the exact expected format is still unknown. Complete registration via
  the Console UI (Administration -> Solutions -> Module Server) instead;
  this role does not yet automate registration reliably.
- **Tanium Zone Server** (win-tzs-case1-01): `Get-Service 'Tanium
  ZoneServer'` Running, `TaniumZoneServer.exe` alive, using a
  `tanium-init.dat` fetched directly from the Server's own install
  directory with zero Console interaction.

The roles themselves (as opposed to the manual command lines) have not
yet been re-run end-to-end in one playbook pass against a fresh clone
with every fix in place — re-validate before trusting the full playbook
unattended for a new case, but every individual installer's real
behavior is now confirmed correct.

**2026-08-21 follow-up fixes are NOT yet re-validated end-to-end**
(the `create-admin-user` SQL-login fix, the SOAPServer.key/.crt
regeneration, the `win_service_info`-based completion check, and the
whole `tanium_lab_restore_customer_db` role + customer-DB playbook are
all new since the validation above). They were built from real,
hands-on-diagnosed incidents this session, but only the underlying
manual fixes (granting the computer account, running
`KeyUtility.exe selfsign`, manually installing/starting the service)
were exercised for real — the Ansible role code wrapping them has only
been lint- and syntax-checked, not run against a live VM. Treat this
playbook family as "believed correct, not yet proven" until a real run
happens.
