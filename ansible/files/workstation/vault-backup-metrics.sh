#!/bin/bash
# Collector only (alerting is Grafana's): measures what actually LANDED in the 8TB vault, from the
# vault host itself, so it cannot be fooled by a push script that forgets to report. A generation
# counts only if it is complete (no .part suffix) and holds a non-empty dir for every PVE node.
# Replaces the metric the retired pve-backup-vault-push.sh used to push from pve01.
set -u
V=/mnt/vault/pve-backups
OUT=/var/lib/prometheus/node-exporter/vault_backup.prom
nodes="pve01 pve02 pve03"
best=0; gens=0
for g in "$V"/[0-9]*; do
  [ -d "$g" ] || continue
  case "$g" in *.part) continue;; esac
  gens=$((gens+1)); ok=1; ts=0
  for n in $nodes; do
    if [ -d "$g/$n" ] && [ -n "$(ls -A "$g/$n" 2>/dev/null)" ]; then
      m=$(stat -c %Y "$g/$n"); [ "$m" -gt "$ts" ] && ts=$m
    else ok=0; fi
  done
  [ "$ok" = 1 ] && [ "$ts" -gt "$best" ] && best=$ts
done
bytes=$(du -sb "$V" 2>/dev/null | cut -f1)
tmp=$(mktemp "$OUT.XXXXXX")
{
  echo '# TYPE pve_backup_vault_last_success_timestamp_seconds gauge'
  echo "pve_backup_vault_last_success_timestamp_seconds $best"
  echo '# TYPE pve_backup_vault_bytes gauge'
  echo "pve_backup_vault_bytes ${bytes:-0}"
  echo '# TYPE pve_backup_vault_generations gauge'
  echo "pve_backup_vault_generations $gens"
} > "$tmp" && chmod 0644 "$tmp" && mv "$tmp" "$OUT"
