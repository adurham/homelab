# Loki 3.0.0 → 3.7.1 upgrade plan (HISTORICAL — completed)

> **Status (2026-05-01):** This upgrade has landed. Loki is on 3.7.1 and
> Promtail has been retired entirely (replaced by Grafana Alloy — see
> `docs/promtail-to-alloy-plan.md`). The body below is kept as a
> reference for future Loki minor-version bumps; ignore the
> Promtail-specific sections.

Original context: Renovate PR #5 bumped `loki_version` (and the
since-deleted `promtail_version`) from `3.0.0` to `3.7.1`. Merging was
deferred because 7 minor versions can carry schema / config changes;
this is the deliberate plan that was executed.

## Pre-flight

1. Read the Loki release notes between v3.0.0 and v3.7.1, in particular:
   - https://github.com/grafana/loki/releases — every `v3.x.0` and the
     final patch (`v3.7.1`)
   - The "Upgrading" section of the docs:
     https://grafana.com/docs/loki/latest/setup/upgrade/
   - Look specifically for: schema_config changes, deprecated config
     keys, removed flags, structured-metadata changes, ruler changes.
2. Snapshot the live state on vm-01 in case rollback is needed:
   ```bash
   ssh root@172.16.0.42 "tar -czf /root/loki-pre-upgrade.tgz /etc/loki /var/lib/loki/rules /var/lib/loki/compactor"
   ```
   (Don't snapshot `chunks/` — it'll be huge and Loki can rebuild
   indices from chunks on a fresh schema if needed.)
3. Confirm current state is healthy:
   ```bash
   ansible vm-01 -m shell -a 'curl -s http://localhost:3100/ready'
   curl -s "http://172.16.0.42:8428/api/v1/query?query=up%7Bjob=%22loki%22%7D"
   ```

## Likely sticking points to watch

- `schema_config.configs[].schema` — we set `v13` (current). 3.x has
  introduced `v14` as an option; check whether v13 is still supported in
  3.7.x or if we'd need to add a new schema entry with `from:` set to a
  cutover date. Don't rewrite history — add a new entry.
- `compactor` — the API has shifted across 3.x. Our config has
  `delete_request_store: filesystem` which was added in 3.x but the
  exact key may have moved. Check.
- `limits_config.allow_structured_metadata` — we set `true`; this became
  the default at some point. Likely still valid, but verify.
- `analytics.reporting_enabled` — sometimes renamed.

If any of these key/section names changed, Loki will refuse to start and
log the error. The config is in `roles/loki/templates/loki.yml.j2` —
update there, not on the live host.

## Execution

1. **Bump role version:**
   ```yaml
   # ansible/roles/loki/defaults/main.yml
   loki_version: "3.7.1"
   # ansible/roles/promtail/defaults/main.yml
   promtail_version: "3.7.1"
   ```
2. **Update Loki config** if pre-flight reading flagged any breaking
   changes. Edit `roles/loki/templates/loki.yml.j2`.
3. **Deploy Loki first**, then Promtail (Loki is backwards-compatible
   with older Promtail more reliably than vice versa):
   ```bash
   cd ansible
   ansible-playbook deploy_monitoring.yml --limit vm-01 --tags loki
   # then if that succeeds:
   ansible-playbook deploy_monitoring.yml --limit 'vm-01:graf-01:private_subnet' \
     --start-at-task "Download promtail release zip"
   ```
   (The `--tags` form needs us to add `tags:` to the Loki tasks first;
   alternative: `--start-at-task` like we've used elsewhere.)
4. **Verify ingestion & queries:**
   ```bash
   # Loki ready
   ansible vm-01 -m shell -a 'curl -s http://localhost:3100/ready'
   # All hosts still labeled
   ansible vm-01 -m shell -a 'curl -s http://localhost:3100/loki/api/v1/label/host/values | python3 -m json.tool'
   # Push API smoke test (any 5xx?)
   ansible vm-01 -m shell -a 'curl -s "http://localhost:8428/api/v1/query?query=rate(loki_request_duration_seconds_count%7Broute%3D%22loki_api_v1_push%22%2Cstatus_code%3D~%225..%22%7D%5B5m%5D)"'
   # Query a recent log line
   ansible vm-01 -m shell -a 'curl -sG http://localhost:3100/loki/api/v1/query_range \
     --data-urlencode "query={job=\"systemd-journal\"}" --data-urlencode "limit=1"'
   ```
5. **Verify alerts still evaluate:** check Grafana → Alerting → log_*
   rules. If any are stuck in `error` state, check the Grafana logs for
   query parse errors against the new Loki.

## Rollback

If Loki refuses to start or alerts go to Error:

```bash
# On vm-01:
systemctl stop loki
tar -xzf /root/loki-pre-upgrade.tgz -C /
# Restore the older binary:
cd /tmp
curl -L -o loki-3.0.0.zip \
  https://github.com/grafana/loki/releases/download/v3.0.0/loki-linux-amd64.zip
unzip loki-3.0.0.zip
install -m 0755 loki-linux-amd64 /usr/local/bin/loki
systemctl start loki
```

Then revert `roles/loki/defaults/main.yml` and `roles/promtail/defaults/main.yml`
to `3.0.0` and re-run the role to push the matching Promtail back.

## Promtail considerations

Our Promtail config is small (`promtail.yml.j2` — journal scrape only).
Most Promtail breaking changes are in advanced features we don't use:
file matching globs, processing pipelines, push API signatures. Should
be safe across 3.0 → 3.7. Watch the journal scrape config — that's the
one part that's been stable.

## After upgrade

- Update this doc's "Pre-flight" target version if Renovate has bumped
  past 3.7.1 by then.
- Close PR #5 with a note linking the merge commit.
- Watch `loki_disk_pressure` and `loki_write_errors` for 24h post-upgrade
  to catch any latent issues.
