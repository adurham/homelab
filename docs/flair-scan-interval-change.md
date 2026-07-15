# Flair Integration Scan Interval Change

The HACS Flair integration (RobertD502/home-assistant-flair) defaults to a
30-second scan interval. This was lowered to 15 seconds to reduce data
staleness.

## What was changed

File: `/config/custom_components/flair/const.py` on HA host (192.168.86.2)

```
DEFAULT_SCAN_INTERVAL = 30  →  DEFAULT_SCAN_INTERVAL = 15
```

## Why

The HA Flair integration polls the Flair cloud API every 30s, but with
processing + caching lag, vent positions were showing 65+ minutes stale
in HA. The Flair vents themselves report to the cloud every 2-5 min.

Lowering to 15s helps, but the primary fix is the `flair_fast_poller.py`
script which polls the Flair API directly at 15s and pushes to HA as
custom sensors, bypassing the integration's lag entirely.

## Re-apply after HACS update

If the Flair integration is updated via HACS, the const.py will be
overwritten and the scan interval will revert to 30s. Re-apply with:

```bash
ssh -p 2222 root@192.168.86.2 \
  'sed -i "s/DEFAULT_SCAN_INTERVAL = 30/DEFAULT_SCAN_INTERVAL = 15/" \
  /config/custom_components/flair/const.py'
```

Then reload the Flair integration:
```bash
# Via HA API: POST /api/config/config_entries/entry/{entry_id}/reload
```
