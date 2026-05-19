# BWT Load Harness — actual blocker

Status: lab is fully built, throttle config correct, but driving live
`tanium_protocol_download` traffic requires content-distribution
infrastructure that **bare TaniumServer does not include**.

## What works

Verified live on the BWT lab (2026-05-15):

- `/metrics` endpoint scrape via session auth — all counters present:
  - `tanium_throttle_bytes_used_total{site="1",type="tanium_protocol_download"}`
  - `tanium_throttle_bytes_used_total{site="1",type="download"}`
  - `tanium_throttle_bytes_used_total{site="1",type="overall"}`
  - `tanium_throttle_bytes_used_total{site="1",type="sensor"}`
  - `tanium_throttle_bytes_limit{site="1",type="..."}` — all configured limits
- `POST /api/v2/upload_file_stream` (Content-Type: octet-stream): uploads
  to upload-cache folder, returns `{hash, file_size}`. **Different folder
  from the chunk-cache** — file is `/cache/<hash>`-servable but NOT
  available for peer-protocol distribution.
- `POST /api/v2/upload_file` (legacy chunked, Content-Type: json,
  base64-encoded bytes, destination defaults to DownloadCacheFolder).
  Returns `{file_cached:true, percent_complete:100}` but **still does not
  populate `server_package_files` rows or trigger seeding**.
- `POST /api/v2/packages` with file hash references — creates package_file
  row referencing the hash, but `seeded_flag` stays NULL.
- `POST /api/v2/saved_actions` with `start_now_flag: true,
  approved_flag: true` — creates a saved_action that the scheduler picks
  up (`tanium_action_scheduler_active_scheduled_actions: 1`) but
  **silently refuses to issue** because the package isn't "available".
- ZS↔Hub pairing via API (documented separately).

## The actual blocker, traced from source

`reissue_saved_action` in `Components/Database/UpgradeSteps/StoredProcedures.Postgres.sql:1100`
gates dispatch on:
```sql
exists ( select available_time from packages
         where id = _cid AND deleted_flag = 0 AND available_time IS NOT NULL )
```

`available_time` is set by `UpdatePackagesAvailableTime` in
`Components/SOAP/SQL/PackageSQL.cpp:380` which only runs when:
```sql
NOT EXISTS ( SELECT ... FROM package_files pf, packages_package_files ppf
             WHERE ... AND pf.seeded_flag = 0 )
```

`seeded_flag` is set by `issue_seeding_action(_pfid)` in the same SQL
file (line 685), which is called by `update_all_server_package_files`
(line 1100) — which only flips a package_file to seeded when all
**active servers** report the same non-empty `download_identifier` in
`server_package_files`.

The `download_identifier` is written by `UpdateServerPackageFiles` in
`Components/Server/PackageFiles.cpp:28`, called only from
`RequestFileChunksHandler::MarkDownloadComplete` in
`Components/Server/RequestFileChunksHandler.cpp:1161`, called from
`LoadPackageFile` (line 1028), which only runs when:
```cpp
if ( !it->m_dlid.empty() && !it->m_downloadErrorFlag && !ChunkCollectionHasDLID( it->m_dlid ) )
```

**`m_dlid` is the download_identifier — which is empty until set by the
above chain.** Catch-22.

The downloader (TDownloader, separate binary) is what bootstraps
`download_identifier` after a successful HTTP pull from `source`. **It
does not run on bare TaniumServer.** It's part of the broader
content-distribution infrastructure that includes module servers, CPMS
(Cloud Package Management Service), or content.tanium.com pulls — none
of which are active on a freshly-installed standalone TS without
modules.

## Why this won't matter for NEC

NEC is TaaS (Tanium Cloud). Their TS has the full content-distribution
stack: TDownloader, CPMS, module servers, content.tanium.com pulls.
That's why their `tanium_protocol_download` counter actively moves with
real package traffic.

A bare-TS lab cannot 1:1 mirror this without installing the same
content-distribution infrastructure — which requires Tanium internal
build artifacts that aren't generally available outside Tanium Cloud
deployments.

## What the lab IS still useful for

- **Throttle config verification**: confirm the `/api/v2/site_throttles`
  and `/api/v2/system_settings` APIs work, validate the JSON shape
  customers' tools should use.
- **TanOS automation patterns**: the QMP-keystroke template-baking and
  ZS↔Hub pairing API patterns are now durable knowledge in the skill and
  warm memory.
- **Sensor-throttle testing**: the `type="sensor"` counter responds to
  sensor evaluation traffic, which IS bandwidth-throttled by the same
  code path as `tanium_protocol_download`. Different bucket but same
  enforcement logic.
- **Raw protocol probing**: direct TCP 17472 traffic between clients
  and ZSes can be measured at the iptables layer for protocol-level
  experiments that don't need a full content workflow.

## What it is NOT useful for

- End-to-end Action+Package deployment without manually priming the
  chunk collection (which is a closed system).
- Reproducing the exact `tanium_protocol_download` overage scenario NEC
  hits — that requires TaaS-equivalent content infrastructure.

## Recommendation

Treat the lab as infrastructure-only. For the NEC case, use the lab to
validate **configuration-shape** hypotheses (does `site_throttles_use_local_ip=1`
have the effect the docs say?) via the throttle-statuses API and
ad-hoc protocol traffic, but **do not try to reproduce the full traffic
pattern** — that requires content infrastructure we don't have.

The original NEC investigation should focus on what we DID learn from
production data (source-verified counter routing, etc.) plus targeted
data-pulls from their TaaS environment via lockbox.
