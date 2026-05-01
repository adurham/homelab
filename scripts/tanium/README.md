# Legacy Tanium diagnostic scripts

Frozen one-off / diagnostic tooling from earlier troubleshooting work.
**Not actively maintained.** Kept in the repo as recoverable reference,
not as an extensible toolset.

## Status

- `pyproject.toml` carries an extensive `per-file-ignores` block for
  `scripts/tanium/**` (S105/S106/S108/S110/S113/S310/S311/S314/S318/S323,
  E402/E701/E722, F401/F841, B007/B018/B023/B904) — the lint rules are
  silenced rather than the code being modernized. Don't read those
  ignores as endorsement of the code, just acknowledgement that nothing
  here is on the maintenance roadmap.
- New diagnostic / one-off Tanium tooling should live elsewhere
  (a separate repo, a per-incident gist, or `scripts/` with a clean
  ruff profile). Don't extend this directory.

## What's here

A mix of:

- PCAP analyzers (`analyze_tanium_pcaps.py` + `ANALYZE_TANIUM_PCAPS_README.md`)
- Performance test scripts (`tanium_perf_test*`, `tanium_download_perf_test.py`,
  `TANIUM_PERF_TEST_README.md`)
- API and SQL utilities (`clientAPI.py`, `md5_sql_*`, `push_metrics.py`,
  `question_load.py`, `change_tds_settings.py`, `toggle_tds_sensors.py`)
- Bulk import / cleanup scripts (`import_users.ps1`, `import_groups.ps1`,
  `clean THR alerts.py`, `extract_ids.py`, `extract_urls.ps1`)
- Action / sensor scaffolding (`actions/`, `sensors/`, `create_action.py`)
- Misc helpers (`open_psql.sh`, `rename_files.sh`, `reset_tanium_pki.sh`,
  `scan_port_443.py`, `spam_questions.py`, `sudo_airgap.{sh,ps1}`,
  `tanium_compare.py`, `tds_wrapper.py`, `tls_test.py`, `urls.txt`)

## If something here is genuinely needed

Lift it into a properly-maintained module: re-write to current Python
style, drop the broad ignores for that one file, add tests if it's
worth keeping. Otherwise leave it where it is — these scripts have
served their purpose.
