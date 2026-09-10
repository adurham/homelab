# roles/logrotate

Rotates/prunes application-level log files that aren't covered by the
OS package defaults already in `/etc/logrotate.d/` (apt, dpkg, ufw,
rsyslog, etc. — those ship with their own package and don't need this
role).

## Why this exists

Fleet audit 2026-09-10: every host in the cluster had ONLY the stock
OS-package logrotate entries. No app-level log producer (media-ingest
scrapers, collectors, etc.) had any rotation/retention configured.
media-ingest-02 hit this first in practice — its ofscraper wrapper had
been writing unrotated logs since June, growing to 2.3GB (75% of the
container's 8GB disk) before being noticed.

## Two distinct problems, two mechanisms

1. **Continuously-appended, fixed-name log files**
   (e.g. `/var/log/foo/app.log`) — real logrotate stanzas, driven by
   `logrotate_configs`. logrotate's rename+truncate model fits this:
   a long-running process holds the file open in append mode,
   `copytruncate` (default) lets rotation happen without a service
   restart.

2. **Uniquely-named files in dated subdirectories, one new file per
   run, never reopened** (e.g. ofscraper's
   `main_profile_YYYY-MM-DD/*.log` tree) — logrotate's rename/truncate
   model doesn't apply; there's nothing to "rotate", each file is
   already immutable once written. Handled instead by
   `logrotate_prune_paths`: a daily systemd timer running
   `find <path> -mtime +N -delete` (plus removing now-empty dated
   subdirectories). Same retention intent, different mechanism because
   the file lifecycle is different.

Both lists are empty by default (role is a no-op if unused). Set
per-group/per-host in `inventory/group_vars/*.yml` or inline in
`inventory/proxmox.yml`, same convention as `alloy_log_unit_allowlist`.

## Example

```yaml
logrotate_configs:
  - name: media-ingest-02
    paths:
      - /var/log/media-ingest-02/scraper.log
    frequency: daily
    rotate: 14
    compress: true
    owner: mediaingest
    group: mediaingest

logrotate_prune_paths:
  - path: /var/lib/media-ingest-02/logging
    days: 30
```
