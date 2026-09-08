#!/usr/bin/env bash
# Monitor for Tanium package_files that are genuinely stuck (not just queued) -
# i.e. customer-specific / legacy-signed content that will NEVER download
# (content-signing-key mismatch on old solutions, or the 127.0.0.1 self-cache
# generation bugs seen this session). Run periodically against the TS.
#
# Usage: ./check_stuck_downloads.sh <ts-ip> <ssh-user>
# Example: ./check_stuck_downloads.sh 172.16.0.57 tandev

set -euo pipefail
TS_IP="${1:?Usage: $0 <ts-ip> <ssh-user>}"
SSH_USER="${2:?Usage: $0 <ts-ip> <ssh-user>}"

echo "=== Stuck-download report for $TS_IP ($(date -u +%FT%TZ)) ==="

ssh "${SSH_USER}@${TS_IP}" "sudo -u postgres /usr/pgsql-16/bin/psql -p 5432 -d tanium -Atc \"
  SELECT
    CASE
      WHEN download_error_flag = 1 THEN 'ERROR_FLAGGED'
      WHEN download_status = 1005 AND download_start_time IS NULL THEN 'QUEUED_NOT_STARTED'
      WHEN download_status = 1005 AND download_start_time < (now() - interval '1 hour') THEN 'STALE_IN_PROGRESS_OVER_1H'
      WHEN download_status = 1005 THEN 'IN_PROGRESS'
      ELSE 'OTHER:' || download_status
    END AS bucket,
    count(*)
  FROM tanium.package_files
  WHERE deleted_flag = 0 AND download_status IS DISTINCT FROM 200
  GROUP BY 1
  ORDER BY 2 DESC;
\"" 2>&1 | grep -v "WARNING\|Unauthorized\|####"

echo ""
echo "=== Files stale >1h (candidates for permanently-undownloadable / legacy content-signing-key issue) ==="
ssh "${SSH_USER}@${TS_IP}" "sudo -u postgres /usr/pgsql-16/bin/psql -p 5432 -d tanium -Atc \"
  SELECT pf.id, pf.hash, pf.source, pf.download_start_time
  FROM tanium.package_files pf
  WHERE pf.deleted_flag = 0
    AND pf.download_status = 1005
    AND pf.download_start_time < (now() - interval '1 hour')
  ORDER BY pf.download_start_time
  LIMIT 50;
\"" 2>&1 | grep -v "WARNING\|Unauthorized\|####"

echo ""
echo "=== Packages associated with stale files (helps identify which customer solution owns them) ==="
ssh "${SSH_USER}@${TS_IP}" "sudo -u postgres /usr/pgsql-16/bin/psql -p 5432 -d tanium -Atc \"
  SELECT DISTINCT p.id, p.name
  FROM tanium.packages p
  JOIN tanium.packages_package_files ppf ON ppf.package_id = p.id
  JOIN tanium.package_files pf ON pf.id = ppf.package_file_id
  WHERE pf.deleted_flag = 0
    AND pf.download_status = 1005
    AND pf.download_start_time < (now() - interval '1 hour')
  ORDER BY 2
  LIMIT 50;
\"" 2>&1 | grep -v "WARNING\|Unauthorized\|####"

echo ""
echo "=== Current key settings (verify via console API, not raw SQL, if changes needed) ==="
echo "  max_concurrent_downloads and check_package_files_flag - check via:"
echo "  curl -sk https://${TS_IP}:8443/api/v2/system_settings/by-name/max_concurrent_downloads -H \"session: \$SESSION\""
