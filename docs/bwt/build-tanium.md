# BWT Lab — Phase 3: Tanium Server, Zone Servers, throttle config, clients

After phases 1+2, we have a clean network and 5 TanOS appliances at
their target IPs with their target FQDNs. Now install the Tanium roles,
configure the throttle scenario via API, and bring clients online.

## Artifactory pre-stage (Mac-side)

The BWT subnet has no route to `artifactory.ci.corp.tanium.com`. Stage
RPMs/debs on the Mac via the corp SOCKS5 proxy, then ship via SFTP from
ansible.

`scripts/tanium/fetch_artifactory_bundle.sh 7.8.5.1308` fetches:
- `centos8-x64/TaniumServer-7.8.5.1308-1.x86_64.rpm` (~71 MB)
- `centos8-x64/TaniumZoneServer-7.8.5.1308-1.x86_64.rpm` (~18 MB)
- `ubuntu24-x64/taniumclient_7.8.5.1308-ubuntu24_amd64.deb` (~16 MB)

into `files/tanium-7.8.5.1308/` (gitignored). Auth: anonymous on the
corp network. Idempotent — re-running skips already-present files.

TanOS 1.8.6 is RHEL 8 based, so `centos8-x64` RPMs (suffixed `.rhe8`)
apply to TS and TZS. There's no `rhel8-x64` dir in this artifactory
layout for 7.8.5.1308 — only `centos8-x64`. They're the same content,
the directory name is historical.

## TS/TZS install workflow

TanOS appliances ingest software via SFTP to `tancopy@<host>:/incoming/`
followed by `ssh tanadmin@<host> "install ts|tzs <version>"`. The
flow:

### 1. Grant tancopy the same SSH keys as tanadmin

The default tancopy user has no authorized_keys. Add ours:

```
ssh tanadmin@<host> "copy pubkeys tancopy"
```

This copies tanadmin's authorized_keys (which include
personal_macbook.pub) into tancopy's authorized_keys. Per-host action,
idempotent.

### 2. SFTP the RPM to /incoming

```
echo "put $RPM /incoming/" | sftp tancopy@<host>
```

`/incoming/` is wiped daily at 02:00 — fine, the install consumes it
before then.

### 3. Run the install command

TS:
```
echo "$CONSOLE_PW" | ssh -tt tanadmin@<host> "install ts 7.8.5.1308"
```

The `tanium` console password is read from stdin (TanOS prompts for
it). The password must satisfy:
- ≥1 lowercase, ≥1 uppercase, ≥1 numeric, ≥1 non-alphanumeric
- ≥10 chars
- Not dictionary-based
- Not contain "tanium" as username

Stored in vault as `vault_bwt_console_password`.

TZS:
```
ssh -tt tanadmin@<host> "install tzs 7.8.5.1308"
```

No stdin needed (ZS install doesn't prompt for a console password).

### 4. Verify

```
ssh tanadmin@<host> "report info"
# Expect: Role: Tanium Server (Standalone) or Tanium Zone Server
```

### 5. First console login: default content import — REQUIRED

This step is mandatory, not optional. **Without it the package
file-download pipeline never runs.** Empirically (2026-05-18): an
API-created package_file with a valid hash + bytes on disk will sit
forever in `cache_status: Processing` until Default Content is
imported, at which point the next scheduler tick correlates the
existing cache file and the package becomes `Cached`.

The first time you log in to the console (`https://10.99.0.10`, user
`tanium`, password from `vault_bwt_console_password`) on a freshly
installed TS, the UI redirects to `/ui/console/initial-import` and
imports two solutions:

- **Default Computer Groups** (~v1.0.33)
- **Default Content** (~v8.7.61)

This takes 2-3 min; stay on the page until both rows show "Complete"
("Stay on this page until import is complete"). The import does NOT
happen automatically on install — it's gated behind the first console
login.

Verify after:

```bash
# A few well-known default sensors should now exist:
curl -sk -H "session: <token>" 'https://10.99.0.10/api/v2/sensors?name=Computer%20Name' | jq '.data.id'
# Computer Group "All Computers" (id=1) should resolve:
curl -sk -H "session: <token>" 'https://10.99.0.10/api/v2/groups/1' | jq '.data.name'

# And — proof that the file-download pipeline works — upload a small file
# and check it transitions to Cached within a few seconds. If it sits in
# Processing for more than 30 seconds, the import didn't finish.
```

Theoretically we could trigger this via API (`POST /api/v2/import_xml`
against bundled content XML at
`/opt/Tanium/TaniumServer/initial_content/*.xml`) but the UI path is
fast enough that ansible-isation isn't worth it for a lab build.

## Why TS/TZS install isn't yet in an ansible role

Two reasons:

1. **Password generation needs a one-time-then-vault-it interactive
   step.** The console password must satisfy complex rules and we
   want it stored encrypted. Until we automate that, the role would
   either burn a one-shot password into the playbook (bad) or read
   from vault (fine, but presupposes the vault entry exists).

2. **The interactive nature isn't well-suited to ansible's
   `command` module.** `install ts` reads `tanium` password from
   stdin, but ansible's `command` module with stdin redirect is
   fiddly and the interactive nature plus password sensitivity made
   me wary. A proper play would use `expect` module or `script` with
   a here-doc.

For now, the install is documented above and captured in this doc.
Ansible-isation is a TODO.

## Tanium API authentication

Two auth modes; pick the right one:

### Session token (short-lived, ~5 min)
```
S=$(curl -sk -X POST https://<ts>/api/v2/session/login \
    -H "Content-Type: application/json" \
    -d '{"username":"tanium","password":"...console_pw..."}' \
    | jq -r .data.session)
curl -sk -H "session: $S" https://<ts>/api/v2/server_info
```

Use for ad-hoc admin tasks and ansible plays. The session expires
~5 min after creation but refreshes on use.

### API token (long-lived, with trusted-IP restriction)
```
curl -sk -X POST -H "session: $S" -H "Content-Type: application/json" \
  https://<ts>/api/v2/api_tokens \
  -d '{"notes":"automation","expire_in_days":365,"trusted_ip_addresses":"10.99.0.0/24"}'
```

**Critical:** `trusted_ip_addresses` MUST be set at creation time. PATCH
of the field is broken (the PATCH endpoint requires a "valid token
string for rotation" which isn't documented and we couldn't make work).
If you forget trusted_ip_addresses, DELETE the token and recreate.

Tokens without trusted_ip_addresses return 401 on every endpoint —
that's not an authorization bug, it's the trust-list working as
designed. The token is valid but the source IP isn't trusted.

Stored in vault as `vault_bwt_api_token`.

## Throttle configuration via /api/v2 (NOT psql)

Hard rule (Adam's standing instruction): platform writes go through the
REST API, not direct psql. The relevant endpoints:

### Create the test site

```
POST /api/v2/site_throttles
{
  "name": "BWTTestSite",
  "bandwidth_bytes_limit": 1250000,
  "download_bandwidth_bytes_limit": 1000000,
  "sensor_bandwidth_bytes_limit": 192500,
  "all_subnets_flag": 0,
  "subnets": [{"range": "10.99.0.0/24"}]
}
```

Limits in bytes/sec:
- 1,250,000 = 10 Mbps overall
- 1,000,000 = 8 Mbps download
- 192,500 = ~1.54 Mbps sensor

Tight numbers were chosen so even small accounting errors would be
visible.

### Toggle global settings

```
PATCH /api/v2/system_settings/by-name/client_cdn_state    body: {"value":"0"}
PATCH /api/v2/system_settings/by-name/site_throttles_use_local_ip   body: {"value":"1"}
```

- `client_cdn_state = 0` — CDN OFF. Forces all client traffic through
  peer protocol, isolating the counter we want to investigate. Without
  this, CDN bytes (which DO count toward `download` + `overall` but
  NOT `tanium_protocol_download` per source review) would muddy the
  measurement.
- `site_throttles_use_local_ip = 1` — matches NEC's production
  config (each customer differs; verify per-case).

### Files this produces

- `ansible/roles/bwt_throttle_config/` — idempotent role that handles
  both POST-if-missing and PATCH-if-different cases for site_throttles,
  and PATCH for system_settings
- `ansible/configure_bwt_throttle.yml` — playbook that orchestrates
  this against bwt-ts

### Verify

```
ansible-playbook configure_bwt_throttle.yml
# Look for the debug task output:
#   BWT repro lab configured:
#     site_throttles_use_local_ip = 1
#     client_cdn_state = 0 (CDN off — peer protocol only)
#     Site: BWTTestSite (10.99.0.0/24)
#       overall:  10.0 Mbps
#       download: 8.0 Mbps
#       sensor:   1.54 Mbps
```

Re-running is idempotent: a second run reports `changed=0`.

## Tanium client install on BWT clients

The standard `tanium_client` role downloads the client bundle from the
TS's client-management plugin endpoint:
`https://<ts>/plugin/products/client-management/v2/downloads/download-bundle/linux`.

**That endpoint returns 404 on the BWT TS** because the
client-management module isn't installed. Installing modules is a
substantial separate workstream (out of scope for the throttle repro).

The fix: a new `bwt_tanium_client` role that:
1. Fetches `tanium-init.dat` from the TS via `/api/v2/keys/315` (this
   endpoint DOES work without client-management — it's part of core TS)
2. Ships a pre-fetched local `.deb` from `files/tanium-7.8.5.1308/ubuntu24-x64/`
3. Installs the .deb via `ansible.builtin.apt`
4. Drops `tanium-init.dat` into `/opt/Tanium/TaniumClient/`
5. Starts the `taniumclient` service

### Tanium init.dat endpoint shape

```
POST /api/v2/keys/315
Header: session: <token>
Body:   {"settings":[{"name":"ServerNameList","value":"10.99.0.10"}]}
Body returns: binary protobuf (the init.dat)
```

The `ServerNameList` baked into init.dat is what the client uses as its
peer list. Initially we passed all 4 ZSes — clients connected to ZSes
but couldn't register with the TS because ZS-to-TS pairing wasn't done
(no `configure ipsec` / `add hub` run). For this repro we want clients
talking directly to the TS, so we override `ServerNameList` to
`10.99.0.10` on the running clients and restart. (Could have baked
this into init.dat from the start — fix in deploy_bwt_clients.yml.)

### Files this phase produces

- `ansible/roles/tanium_client/defaults/main.yml` — parameterized so it
  can target any TS (preserves existing behavior via defaults)
- `ansible/roles/tanium_client_host/defaults/main.yml` — parameterized
  inventory group + DNS settings
- `ansible/roles/bwt_tanium_client/` — BWT-specific install (local .deb,
  no module dependency)
- `ansible/deploy_bwt_clients.yml` — orchestrates CT provisioning +
  client install

### Verification

```
# Each client should be active + registered
ansible bwt_clients -m shell -a 'systemctl is-active taniumclient'

# TS-side: aggregate status should show all 8 registered
curl -sk -H "session: $TOKEN" https://10.99.0.10/api/v2/system_status \
  | jq '.data[1] | {leader_count, registered_with_tls_count, versions}'
# Expected: leader_count=8, registered_with_tls_count=8,
#           versions=[{version_string: "7.8.5.1308", count: 8}]
```

## Pitfalls

- **API token without trusted_ip_addresses returns 401 silently.** No
  obvious clue why. Always set trusted_ip_addresses at creation time
  to the subnet from which the token will be used (lab-wide:
  `10.99.0.0/24` for in-BWT, `192.168.86.0/24` for pve01-side).
- **License file is hostname-locked.** The license we used was issued for
  `ts-01.chi.lab.amd-e.com,ts-02.chi.lab.amd-e.com` — won't match
  `bwt-ts.bwt.local`. The TS still installs and runs, but Console
  features that require a valid license won't work. For throttle
  testing (which is core TS, not module-dependent), this is fine.
- **`/incoming` is daily-cleaned at 02:00.** RPMs uploaded after that
  time get wiped. Install promptly.
- **The `tanium_client` role's hardcoded ServerNameList.** Originally
  pointed at `tzs-01.chi.lab.amd-e.com,tzs-02.chi.lab.amd-e.com` — fine
  for the main lab, broken for BWT. Parameterized via
  `tanium_client_server_name_list` default.
- **Bundle endpoint 404s if client-management module isn't installed.**
  Don't try to "fix" by installing the module — for throttle repro,
  shipping a local .deb is simpler and reproducible.
- **`/api/v2/system_status` returns aggregates, not per-client list.**
  The format is `{data: [aggregate1, aggregate2, cache_info]}`. Per-client
  data is in cache rows accessed via paginated GET. For our verification,
  aggregates suffice.

## Adding ZS↔Hub pairing (post-install)

After TS+TZS are installed but clients are still routing direct to TS,
the pairing flow requires several non-obvious API moves. The "Add Zone
Server" Console UI button is backed by a REST route that doesn't appear
in `/api/v2`'s top-level listing.

### Step 1: Install the Hub role on the TS

```
echo "put TaniumZoneServer-7.8.5.1308-1.x86_64.rpm /incoming/" | sftp tancopy@bwt-ts
ssh tanadmin@bwt-ts "add hub"
# Result: "Generated client PKI bundle." + role becomes "Tanium Server with Hub"
```

### Step 2: Approve the Hub's auto-registration

The Hub auto-registers when installed. Find and approve it:

```
S=$(curl -sk -X POST https://bwt-ts/api/v2/session/login ... | jq -r .data.session)
# Find the HUB-type entry id
curl -sk -H "session: $S" https://bwt-ts/api/v2/server_registration_requests | jq '.data[] | select(.type=="HUB")'
# PATCH approve
curl -sk -X PATCH -H "session: $S" -H "Content-Type: application/json" \
  https://bwt-ts/api/v2/server_registration_requests/<hub_id> \
  -d '{"approved_flag":true}'
```

### Step 3: Import TS public key + set AllowedHubs on each ZS

Per Tanium docs, on EACH ZS:
1. SFTP `tanium-init.dat` (fetched via `POST /api/v2/keys/315`) to
   `tancopy@<zs>:/incoming/`.
2. Drive the TanOS console via QMP keystrokes:
   `Main Menu → 2 (Tanium Operations) → I (Import Public Key) → y`
3. In Tanium Operations: `2 (Config Settings) → 9 (Edit TZS Settings) →
   A (Add)`. Key=`AllowedHubs`, value=`<ts-ip>`.
4. `ssh tanadmin@<zs> "service restart taniumzoneserver"`

The keystroke sequence is captured in
`scripts/proxmox/qmp_keystroke.py` and demonstrated for bwt-zs-01/02
during the BWT lab build (see session transcript 2026-05-15).

### Step 4: Add each ZS to the Hub (the hidden API route)

`POST /api/v2/server_trusts` returns 500 "valid server guid must be
specified" — that's not the right endpoint for adding new ZSes. The
correct route is **nested under hubs**:

```
POST /api/v2/hubs/<hub_registration_id>/zone_servers
Body: {"address": "<zs-ip>"}
```

Source-verified in `Components/REST/RESTHandler.cpp` line ~187. Route
map says `{"zone_servers", "zone_server"}` valid only nested under
`/api/v2/hubs/<id>/`.

```
# Add ZS-01 and ZS-02 to the Hub
for zs in 10.99.0.11 10.99.0.12; do
  curl -sk -X POST -H "session: $S" -H "Content-Type: application/json" \
    https://bwt-ts/api/v2/hubs/1/zone_servers \
    -d "{\"address\":\"$zs\"}"
done
```

After POST, each ZS appears in `server_registration_requests` with
`type: "ZONE_SERVER"`. Approve via PATCH:

```
curl -sk -X PATCH -H "session: $S" -H "Content-Type: application/json" \
  https://bwt-ts/api/v2/server_registration_requests/<zs_id> \
  -d '{"approved_flag":true}'
```

### Step 5: Re-issue client init.dat pointing at ZSes

Client init.dat that was baked with `ServerNameList=<ts-ip>` still
routes direct to TS, even after `TaniumClient config set ServerNameList`
override. The init.dat values win at startup. Re-issue:

```
curl -sk -X POST -H "session: $T" \
  -H "Content-Type: application/json" \
  https://bwt-ts/api/v2/keys/315 \
  -d '{"settings":[{"name":"ServerNameList","value":"<zs1>,<zs2>"}]}' \
  -o tanium-init.dat
# Push to all clients + restart taniumclient
```

### Verify

```
curl -sk -H "session: $S" https://bwt-ts/api/v2/system_status | \
  jq '.data[] | select(.zone_servers != null) | .zone_servers'
# Expected (8 clients across 2 ZSes):
# [
#   {"hub_address": "127.0.0.1", "zone_server_address": "10.99.0.11:17472", "count": 4},
#   {"hub_address": "127.0.0.1", "zone_server_address": "10.99.0.12:17472", "count": 4}
# ]
```

Established 2026-05-15: 8 BWT clients distributed 4/4 across bwt-zs-01
and bwt-zs-02. ZS-03 and ZS-04 remain installed-but-cold (AWS-side
reserved equivalents).

## Adding ZS to Hub via API (the route that was hard to find)

POST `/api/v2/hubs/<hub_registration_id>/zone_servers` with body
`{"address": "<zs-ip>"}` — this is what the Console UI's "Add Zone
Server" button hits. Source: `Components/REST/RESTHandler.cpp` line
~187 in the platform repo, route map `{"zone_servers", "zone_server"}`
valid only nested under `/api/v2/hubs/<id>/`.

NOT working: `/api/v2/zone_servers` (Invalid object route),
`/api/v2/server_trusts` POST (500 "valid server guid required").

Full pairing flow:
1. `add hub` on TS (with TZS RPM in /incoming).
2. PATCH `/api/v2/server_registration_requests/<hub-id>` approved_flag=true.
3. On each ZS: import tanium-init.dat via TanOS menu (`2 → I`) + add
   AllowedHubs setting via TanOS menu (`2 → 2 → 9 → A`) + restart TZS.
4. POST `/api/v2/hubs/<hub-id>/zone_servers` with {address: <zs-ip>}.
5. PATCH `/api/v2/server_registration_requests/<zs-id>` approved_flag=true.
6. Re-issue client init.dat with ServerNameList=ZS-list.

Verified 2026-05-15: 8 clients distributed 4/4 across bwt-zs-01 and
bwt-zs-02 via `/api/v2/system_status` zone_servers array.
