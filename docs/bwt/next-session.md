# BWT Lab — Next Session Handoff

Written 2026-05-18 after a long session. Read this first before doing
anything. The actual task is **build the load harness for the throttle
repro**, not anything else.

## DO NOT DO

These are the wrong-turn rabbit holes from the last session. Skip them.

- **Do NOT install Client Management module** — Adam explicitly said it's
  not needed.
- **Do NOT install TMS (Tanium Module Server)** — Adam was angry I did.
  TMS is currently deployed at `bwt-tms` (VMID 225, 10.99.0.20) and
  half-configured. **Tear it down before doing anything else** (see
  Cleanup section below).
- **Do NOT psql write** — Adam's standing rule. API only for platform
  writes.
- **Do NOT chase "register TMS with TS" workflows** — same reason.

## Current lab state (verified working)

| Component | VMID | IP | Role | Status |
|---|---|---|---|---|
| bwt-dhcp | CT 114 | 10.99.0.2 | dnsmasq | ✓ running |
| bwt-ts | 220 | 10.99.0.10 | TS 7.8.5.1308 + Zone Server Hub | ✓ running |
| bwt-zs-01 | 221 | 10.99.0.11 | TZS 7.8.5.1308 | ✓ paired, active |
| bwt-zs-02 | 222 | 10.99.0.12 | TZS 7.8.5.1308 | ✓ paired, active |
| bwt-zs-03 | 223 | 10.99.0.13 | TZS 7.8.5.1308 | ⚠ installed, NOT paired (reserved) |
| bwt-zs-04 | 224 | 10.99.0.14 | TZS 7.8.5.1308 | ⚠ installed, NOT paired (reserved) |
| bwt-tms | 225 | 10.99.0.20 | TMS 7.8.5.1308 | ❌ DELETE (see cleanup) |
| bwt-tc-01..08 | CT 320-327 | 10.99.0.x | Tanium client 7.8.5.1308 | ✓ all 8 registered |

**Client distribution:** 4 clients via ZS-01, 4 via ZS-02. Verified via
`/api/v2/system_status` → `zone_servers[]`.

**Default content imported:** Default Computer Groups (1.0.33) + Default
Content (8.7.61) imported via first-login UI on 2026-05-18. Without this
step the TS has no sensors/packages/saved questions out of the box.
Documented in `build-tanium.md` step 5.

**Throttle config (BWTTestSite):**
- overall: 10 Mbps (1,250,000 bytes/sec)
- download: 8 Mbps (1,000,000 bytes/sec)
- sensor: 1.54 Mbps (192,500 bytes/sec)
- subnet: 10.99.0.0/24
- `client_cdn_state = 0` (CDN off, peer-protocol only)
- `site_throttles_use_local_ip = 1`

**Vault secrets** (in `ansible/group_vars/all/tanium_secrets.yml`):
- `vault_bwt_tanadmin_password` — TanOS tanadmin user
- `vault_bwt_console_password` — Tanium "tanium" console admin
- `vault_bwt_api_token` — API token (trusted_ip: 10.99.0.0/24)

## Cleanup before starting

The bwt-ts has `Active Module Server: bwt-tms.bwt.local` set from a
wrong-turn experiment. Revert this:

1. Tear down bwt-tms:
   ```
   ssh root@192.168.86.11 'qm stop 225 && sleep 5 && qm destroy 225 --purge'
   ```

2. Reset bwt-ts module server config back to default (127.0.0.1). On
   bwt-ts via QMP keystroke or SSH, navigate Tanium Operations →
   Configure Module Server → and set the address back to 127.0.0.1, OR
   leave it (the loopback default is what install-time TMS-less appliances
   have — having "bwt-tms.bwt.local" pointed at a now-deleted appliance
   just makes the TS log warnings but doesn't break core TS).

3. Remove bwt-tms from inventory:
   - `ansible/inventory/proxmox.yml` — delete `bwt_module_servers` block
   - `ansible/inventory/group_vars/bwt_module_servers.yml` — delete file
   - `ansible/deploy_bwt_tms.yml` — delete file

4. Verify clean state: `cd ansible && ansible-lint`

## THE ACTUAL TASK: Load harness

We need to drive **`tanium_protocol_download`** traffic from the TS out
to clients via the active ZSes, so we can compare:
- **Channel 1**: TS-side `/metrics` counter (`tanium_throttle_bytes_used_total{site="1",type="tanium_protocol_download"}`)
- **Channel 2**: Wire byte counters on ZSes (iptables on TCP 17472)
- **Channel 3**: Per-client received-bytes (from the deploying action)

If all three agree under heavy traffic → throttle counter is accurate.
If TS counter drifts from wire traffic → counter accounting bug
(which is what NEC is hitting).

## THE TECHNICAL BLOCKER (RESOLVED 2026-05-18)

The blocker last session was NOT an API limitation. It was that
**Default Content had never been imported** on the TS. Without that
import, the package file-download pipeline doesn't run — uploaded
package_files sit in `cache_status: Processing` forever even though
all the DB rows (`package_files`, `server_package_files`,
`packages_package_files`) look correct.

Confirmed via HAR capture of the Console UI upload flow (saved at
`~/Downloads/10.99.0.10.har`):

1. `POST /api/v2/upload_file_stream`
   - Content-Type: `multipart/form-data; boundary=...` (NOT
     `application/octet-stream`; my old attempts used octet-stream and
     the server accepted them but I'm not 100% sure that produced the
     same on-disk artifact — switch the harness to multipart to match
     the UI exactly).
   - Body: one `file` form field with the raw bytes + filename.
   - Response: `{"data":{"file_size":N,"hash":"<sha256-hex>"}}`.

2. `POST /api/v2/packages`
   - Content-Type: `application/json`, header `tanium-options: {}`.
   - Body has `files: [{name, size, hash, source:"", download_seconds:0, fileType:"LOCAL", percentUploaded:100, fileId:"file-N"}]`.
   - `source` is empty (the UI does NOT use a `https://localhost/cache/<hash>`
     URL — my earlier theory was wrong). `fileType:"LOCAL"` +
     `percentUploaded:100` are UI-only metadata the server seems to ignore.

3. No magic bootstrap call between the two — just upload then create
   package. The UI flow worked end-to-end: package id 46 ("Test",
   126 MB) went from `Processing` to `Cached` in ~4 seconds.

The package id 17 ("BWT TinyTest") I created last session ALSO
transitioned to `Cached` — at 17:12 UTC, right after Default Content
finished importing. So importing Default Content unblocks ALL stuck
package_files, retroactively.

Action: `build-tanium.md` step 5 now flags the Default Content import
as REQUIRED. Update the build runbook to do that import as a hard
prerequisite for any lab work.

What works:
- `POST /api/v2/upload_file_stream` (Content-Type: application/octet-stream,
  body = raw bytes) → returns `{hash, file_size}`. Verified — file lands
  in upload cache folder.
- `POST /api/v2/upload_file` (chunked, Content-Type: json, body has
  base64 bytes + hash + destination_file) → file lands in
  DownloadCacheFolder (different from above). Verified.
- `POST /api/v2/packages` with `files: [{hash, name, size}]` → creates
  package + package_file records. Verified.
- `POST /api/v2/saved_actions` with `start_now_flag: true` → creates
  saved_action with status=Pending. Verified.

What's broken:
- After all the above, `package_files[].seeded_flag` stays NULL.
- Therefore `packages.available_time` stays at epoch (1900-01-01).
- Therefore `reissue_saved_action` SQL function refuses to dispatch
  (gate: `available_time IS NOT NULL`).
- `tanium_action_scheduler_active_scheduled_actions: 1` but
  `issue_total: 0` — scheduler sees but refuses.

What I traced (source-verified on platdev-jump platform repo):
- `seeded_flag=1` set by `issue_seeding_action(_pfid)` in
  `StoredProcedures.Postgres.sql`
- That's only called by `update_all_server_package_files()` which
  requires all active servers to have matching non-empty
  `download_identifier` in `server_package_files` table.
- `download_identifier` only written by `RequestFileChunksHandler::MarkDownloadComplete`
  in `Components/Server/RequestFileChunksHandler.cpp:1146`.
- That only runs from `LoadPackageFile()` (same file:1028) when the
  pre-condition is `!m_dlid.empty()` — i.e. the file ALREADY has a
  download_identifier set.

So the chain has a chicken-and-egg I couldn't break from the API alone.

**The Console UI's "Upload File" button works.** It must do one more
API call after upload that bootstraps the chain. We need to figure out
what that is. Options for next session:

1. **Browser DevTools capture** — log into https://10.99.0.10 in
   Firefox, open Network tab, create a package via the UI's
   "Create Package" → "Upload File" flow. Capture the exact request
   sequence. This is the most reliable path.

2. **Look at PackageRequests.cpp more carefully** — specifically the
   `FindOrCreatePackageFile` function. It probably has a code path that
   recognizes "this hash is already in the upload-cache" and pre-seeds
   `server_package_files`.

3. **Try `direct_download_flag: true`** — I had it false in my tests.
   The schema says: "If set to true, clients attempt to download the
   file from the URL that is specified in the source field. If the
   attempt fails, or if direct..." (truncated in my dump but might be
   the key).

4. **Wait longer.** I waited 60s after package POST. The seeding cron
   might run every 5 minutes (looking at `baton_expiration_seconds: 300`).
   Try wait of 6+ minutes.

5. **Look at PATCH `/api/v2/package_files/{id}` with `trigger_download: 1`**
   I tried this once and got "Processing" status but never completed.
   Re-try after waiting longer, OR re-try after package upload with a
   real downloadable `source` URL (not the TS's own /cache/<hash>).

## API docs reference

Adam's local copy at `~/Downloads/platform_rest_docs_7/`:
- `api_data.json` — structured endpoint metadata (use `execute_code` to query)
- `Tanium Server REST API Reference.pdf` — full reference, 862 pages
- Key pages: 488-490 (package_spec schema + example), 558-562 (Create
  package with examples), 593-594 (Upload package files)

To query specific schemas/examples programmatically:
```python
import json
data = json.load(open('/Users/adam.durham/Downloads/platform_rest_docs_7/api_data.json'))
# 418 endpoints. Filter by url/type.
```

## Files / artifacts that already exist

| Path | What |
|---|---|
| `~/repos/homelab/ansible/` | All playbooks + roles |
| `~/repos/homelab/docs/bwt/` | Build docs (README, network, tanos, tanium, skill-candidates, harness-blocker, this file) |
| `~/repos/homelab/scripts/proxmox/qmp_keystroke.py` | QMP keyboard driver for TanOS automation |
| `~/repos/homelab/scripts/tanium/fetch_artifactory_bundle.sh` | Pulls RPMs from artifactory |
| `~/repos/homelab/files/tanium-7.8.5.1308/` | TS, TZS, TMS RPMs + Ubuntu24 client deb (gitignored) |

Skills:
- `proxmox-tanos-automation` (in `~/.hermes/skills/tanium/`) — QMP
  keystroke bootstrap pattern, TanOS DEV passwords, wizard navigation,
  ZS↔Hub API pairing

Warm memory facts (search via `memory recall`):
- 600: API-not-psql rule for Tanium platform writes
- 601: ZS pairing API route `/api/v2/hubs/<id>/zone_servers`
- 602: Package upload + downloader gating (the blocker described above)
- 603: Throttle direction (all counters are OUTBOUND from TS/ZS)

## Uncommitted git state

Lots of changes in `~/repos/homelab/` from the last few sessions —
SDN, gateway, DHCP, TanOS automation, ZS pairing, client deployment,
throttle config. All ansible-lint production-clean. After bwt-tms
cleanup, commit in focused chunks. Adam uses 1Password SSH for signing
— write commit messages to /tmp/cmN.txt and ask Adam to approve the
agent prompts in batches.

## Recommended order for next session

1. Cleanup (tear down bwt-tms, remove from inventory + playbooks).
2. Browser DevTools capture of "Create Package + Upload File" UI flow
   on bwt-ts. This unblocks everything.
3. Build the load harness: ansible role + script that deploys a
   known-size package to all 8 clients, samples metrics on TS+ZS+clients
   in parallel, dumps results to a per-run timestamped directory.
4. Run a few baseline experiments to characterize counter behavior under
   different loads.
5. Compare findings to NEC's `tanium_protocol_download` exceedance
   pattern, write up.

## Time logged on case 00271560 so far

8 hours logged 2026-05-15 (subcategory Support-Platform). Next session
will need its own time entry when the work concludes.
