#!/bin/bash
# Fetch Tanium Server/ZS RPMs from corp artifactory through the local SOCKS5
# proxy and stage them under ~/repos/homelab/files/tanium-<version>/.
#
# Why: the homelab BWT subnet has no route to artifactory.ci.corp.tanium.com.
# The Mac has the SOCKS5 proxy (Proxy VPN on 127.0.0.1:1080); the lab does
# not. So we fetch locally, ansible ships the RPMs to /incoming on each
# TanOS appliance, and the install role runs the TanOS `install ts` /
# `install tzs` CLI commands.
#
# Usage:
#   ./scripts/tanium/fetch_artifactory_bundle.sh 7.8.5.1308
#   ./scripts/tanium/fetch_artifactory_bundle.sh 7.8.5.1308 ~/Downloads/staging
#
# Layout produced (gitignored):
#   files/tanium-7.8.5.1308/centos8-x64/TaniumServer-7.8.5.1308-1.x86_64.rpm
#   files/tanium-7.8.5.1308/centos8-x64/TaniumZoneServer-7.8.5.1308-1.x86_64.rpm
#
# Requires: corp SOCKS5 proxy listening on 127.0.0.1:1080 (Proxy VPN).
# Verify with: nc -z 127.0.0.1 1080

set -euo pipefail

VERSION="${1:?usage: $0 <version> [dest_root]}"
DEST_ROOT="${2:-$(cd "$(dirname "$0")/../.." && pwd)/files}"

PROXY="socks5h://127.0.0.1:1080"
BASE_URL="https://artifactory.ci.corp.tanium.com/artifactory/tanium-generic-local/tanium/${VERSION}"
DEST="${DEST_ROOT}/tanium-${VERSION}/centos8-x64"

# TanOS 1.8.x is RHEL 8 based — both TS and TZS RPMs live in centos8-x64
# (no rhel8-x64 dir in 7.8.5.x). The .rhe8 client RPM is bundled and
# served by the TS itself, so we don't pull it here.
# TS + ZS RPMs (centos8-x64) and the Ubuntu 24 client deb (for BWT LXC
# clients which all use ubuntu-24.04-standard template).
FILES_CENTOS8=(
  "TaniumServer-${VERSION}-1.x86_64.rpm"
  "TaniumZoneServer-${VERSION}-1.x86_64.rpm"
)
FILES_UBUNTU24=(
  "taniumclient_${VERSION}-ubuntu24_amd64.deb"
)

# Sanity-check the SOCKS5 proxy is up before we make the user wait on a
# timeout.
if ! nc -z -w 2 127.0.0.1 1080 2>/dev/null; then
  echo "ERROR: SOCKS5 proxy not reachable at 127.0.0.1:1080" >&2
  echo "Start the Proxy VPN (Cisco Secure Client in the Lima VM) and re-run." >&2
  exit 1
fi

mkdir -p "${DEST}"
mkdir -p "${DEST_ROOT}/tanium-${VERSION}/ubuntu24-x64"

fetch_one() {
  local subdir="$1"
  local fname="$2"
  local out="${DEST_ROOT}/tanium-${VERSION}/${subdir}/${fname}"
  local url="${BASE_URL}/${subdir}/${fname}"

  if [[ -s "${out}" ]]; then
    echo "  [skip] ${fname} already present ($(stat -f%z "${out}" 2>/dev/null || stat -c%s "${out}") bytes)"
    return 0
  fi
  echo "  [fetch] ${url}"
  ALL_PROXY="${PROXY}" HTTPS_PROXY="${PROXY}" curl -fL --progress-bar -o "${out}" "${url}"
  local size
  size=$(stat -f%z "${out}" 2>/dev/null || stat -c%s "${out}")
  echo "  [ok]    ${fname} (${size} bytes)"
}

for f in "${FILES_CENTOS8[@]}"; do
  fetch_one centos8-x64 "$f"
done

for f in "${FILES_UBUNTU24[@]}"; do
  fetch_one ubuntu24-x64 "$f"
done

# Skip the original loop below — handled by fetch_one above
exit_after_legacy() { return 0; }
exit_after_legacy

# Legacy loop (kept for diff readability — never reached due to early return)
for f in "${FILES_CENTOS8[@]}"; do
  out="${DEST}/${f}"
  url="${BASE_URL}/centos8-x64/${f}"

  if [[ -s "${out}" ]]; then
    echo "  [skip] ${f} already present ($(stat -f%z "${out}" 2>/dev/null || stat -c%s "${out}") bytes)"
    continue
  fi

  echo "  [fetch] ${url}"
  ALL_PROXY="${PROXY}" HTTPS_PROXY="${PROXY}" \
    curl -fL --progress-bar -o "${out}" "${url}"

  size=$(stat -f%z "${out}" 2>/dev/null || stat -c%s "${out}")
  echo "  [ok]    ${f} (${size} bytes)"
done

echo ""
echo "Staged ${VERSION} under: ${DEST}"
echo ""
echo "Sha256:"
shasum -a 256 "${DEST}"/*.rpm
