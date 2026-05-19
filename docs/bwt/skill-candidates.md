# Skill candidates from this build

Patterns that emerged that should live as reusable skills (not buried in
BWT-specific docs). Each section maps a discovered pattern to a candidate
skill name and what it covers.

## Already extracted

- **`proxmox-tanos-automation`** (`~/.hermes/skills/tanium/proxmox-tanos-automation/`)
  — covers the QMP send-key bootstrap, kickstart-secret extraction,
  default TanOS DEV password (Tanium1), wizard navigation, and the
  cloned-IP collision pattern. Already created during the build.

## Candidates not yet extracted

### 1. `proxmox-sdn-isolated-vnet`

**Why:** The pattern of creating a fresh isolated VXLAN VNet on an
existing zone, with a dedicated gateway-CT model, recurs whenever you
need a clean test subnet on a Proxmox cluster. Not specific to Tanium.

**What it would cover:**
- VXLAN vs Simple zone tradeoff (multi-node vs single-node, DHCP support)
- PVE 9.1 limitation: built-in SDN DHCP only on Simple zones
- Why not to install dnsmasq directly on pve hosts (hygiene)
- The "dedicated DHCP CT on the new bridge" pattern
- pve_*_gateway role pattern (single-node holds gateway IP + SNAT)
- The PRIVATE-MONITORING-IN firewall gotcha (existing isolation breaks
  cross-subnet reach, requires public DNS or new firewall rules)
- How to verify each layer: ip addr / iptables / DHCP smoke test CT

**Trigger:** "I need an isolated test subnet on my Proxmox cluster" or
"how do I add a dedicated DHCP server for a VLAN."

### 2. `ansible-tanos-control-plane`

**Why:** TanOS appliances need a specific ansible setup pattern
(ProxyJump, KbdInteractiveAuthentication=yes, tanadmin user, no
ControlMaster for some operations). The pattern recurs and is currently
documented in 3+ places (tanium_cluster.yml, bwt_servers.yml).

**What it would cover:**
- The `ansible_user: tanadmin` vs `tandev` choice (depends on whether
  appliance is initial-config-complete)
- `KbdInteractiveAuthentication=yes` is REQUIRED in `ansible_ssh_args`
  (TanOS pam_authentication_methods= publickey,keyboard-interactive)
- `ControlMaster=auto` is fine but be aware
- ProxyJump patterns: via pve01 root vs via Tailscale-gw vs direct
- Why `ansible.builtin.command` works for TanOS but
  `ansible.builtin.shell` may not (TanOS shell is the dispatcher, not
  a real /bin/sh)
- Why `delegate_to: localhost` is sometimes the right answer (e.g.
  Mac has the SSH agent forwarding; pve01 might not)

**Trigger:** "I want to use ansible against TanOS appliances" or
"why is my TanOS ansible play failing on KbdInteractiveAuthentication."

### 3. `tanium-api-automation`

**Why:** Programmatic Tanium platform config (sites, throttles, global
settings) via /api/v2 is recurring. The traps around API tokens
(trusted_ip_addresses mandatory) and the session-token vs API-token
choice are easy to get wrong.

**What it would cover:**
- session token vs API token: when to use which
- `trusted_ip_addresses` MUST be set at creation — PATCH is broken
- Subnet-scoped tokens for lab/automation
- Idempotent PATCH patterns for system_settings/by-name
- Idempotent POST-or-PATCH patterns for site_throttles
- Common endpoints: /api/v2/session/login, /api/v2/api_tokens,
  /api/v2/site_throttles, /api/v2/system_settings/by-name, /api/v2/keys/315,
  /api/v2/system_status
- Auth via inventory ansible_ssh_common_args (ProxyJump for lab-internal)
  vs direct uri module
- The standing rule: ALWAYS prefer /api/v2 over psql for writes (memory fact 600)

**Trigger:** "How do I configure Tanium X via API" or "my API token is
401ing."

### 4. `tanium-client-bundle-bootstrap`

**Why:** The client-management plugin dependency for the bundle-download
endpoint is non-obvious and breaks lab builds. The "ship a local .deb +
fetch init.dat only" pattern is what works when modules aren't yet
installed.

**What it would cover:**
- `/plugin/products/client-management/v2/downloads/download-bundle/linux`
  requires client-management module installed (returns 404 otherwise)
- `/api/v2/keys/315` doesn't need any module (core TS endpoint)
- Pre-staging client RPM/deb from artifactory (per-platform layout:
  `centos8-x64`, `ubuntu24-x64`, etc.)
- ServerNameList override on a running client:
  `TaniumClient config set ServerNameList ...` then restart
- LastGoodServerName as the registration health indicator
- TS-side verification via /api/v2/system_status (aggregate format —
  not per-client list)

**Trigger:** "Tanium client install fails with HTTP 401 / 404" or
"my client isn't registering."

### 5. `corporate-artifactory-via-socks5`

**Why:** Fetching from `artifactory.ci.corp.tanium.com` from a homelab
that can't reach corp network is recurring (any time we need to pull
Tanium builds for testing). The SOCKS5 proxy pattern is general but the
exact incantation isn't obvious.

**What it would cover:**
- `ALL_PROXY=socks5h://127.0.0.1:1080 HTTPS_PROXY=...` for curl/wget
- `git config --global http.https://git.corp.tanium.com/.proxy
  socks5h://127.0.0.1:1080` for persistent git auth via SOCKS
- `tanium-generic-local/tanium/<version>/<platform>/` artifactory layout
- Anonymous auth on corp network (no API key needed for reads)
- The per-platform directory naming: `centos8-x64` covers RHEL 8 too;
  no `rhel8-x64` dir for 7.8.x
- Idempotent fetch script patterns (skip-if-present)

**Trigger:** "I need to fetch a Tanium build" or "artifactory is timing
out."

## Anti-patterns documented

These are things we tried that DIDN'T work. Worth capturing somewhere
(probably in `proxmox-tanos-automation` skill's "what we tried" section):

- **qga `guest-ssh-add-authorized-keys` on a fresh TanOS template.**
  Fails with "Permission denied" because qga runs as unprivileged
  qemu-ga user; can't create `/home/tandev/.ssh/`. Even after the
  template is fully provisioned and tandev's homedir exists.
- **Setting `--dhcp-range` on a VXLAN subnet without `--dhcp dnsmasq`
  on the zone.** API accepts the config but no daemon spawns.
- **Trying to PATCH api_tokens.trusted_ip_addresses by id.** Returns
  404 "valid token string must be specified for rotation." Solution:
  DELETE and recreate.
- **Setting `--serial0 socket` and trying to scrape boot output.** TanOS
  grub.cfg doesn't add `console=ttyS0` so serial console is mute. Use
  VGA-console + screendump instead.
- **sshpass + keyboard-interactive auth.** Fails silently on TanOS
  (rejected by pam). Use a python-pty driver if password auth is needed.
- **`ssh -o ProxyJump=` with empty value.** Errors with
  `no argument after keyword "proxyjump"`. Either omit the option or
  give it a real value.

## How to extract a skill from this doc

For each candidate section above:

1. Run `skill_manage(action='create', name='<name>')` with the section
   content as the body, plus a YAML frontmatter `name:` + `description:`.
2. The description is what the LLM matches against when deciding to load
   the skill — write it like a search query someone would type, e.g.
   "Tanium client install fails with HTTP 401 / 404."
3. After creating, test loading by `skill_view('<name>')` and confirm
   the content is useful in isolation (i.e. doesn't reference "the BWT
   lab" as if the reader knew what that was).
4. Update this `skill-candidates.md` to move the section from "candidates"
   to "extracted."

Prefer extracting one skill at a time as needs arise rather than batch-
creating all 5. Skills accrue tokens in every session; only the actually-
useful ones should live in warm memory long-term.
