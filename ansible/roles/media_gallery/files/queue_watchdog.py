#!/usr/bin/env python3
"""
Stuck-queue watchdog for the media gallery background reapers.

Checks the trash (delete) and move queues. If either has items whose oldest
entry has been waiting longer than STUCK_AFTER_SEC, the reaper is wedged — print
a one-line alert to stdout and exit non-zero. If everything is healthy (empty, or
draining normally), print NOTHING and exit 0 so the watchdog stays silent.

Designed to run as a cron 'watchdog' (no_agent): silent stdout = no message sent;
non-empty stdout = alert delivered verbatim.

Run ON the gallery CT (reads the on-disk queues directly).
"""
import json
import os
import sys
import time

DELETE_QUEUE = os.environ.get("TG_DELETE_QUEUE", "/var/lib/media-gallery/pending_delete.json")
MOVE_QUEUE = os.environ.get("TG_MOVE_QUEUE", "/var/lib/media-gallery/pending_move.json")
# A delete entry carries ts (enqueue time). If the oldest pending item has been
# waiting longer than this, the reaper isn't draining. Generous vs REAP_GRACE(8s)
# + normal per-file Drive latency (~2.5s); a healthy queue of N drains in ~N*3s.
STUCK_AFTER_SEC = int(os.environ.get("TG_QUEUE_STUCK_SEC", "900"))  # 15 min


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def main():
    now = time.time()
    alerts = []

    dq = _load(DELETE_QUEUE)
    if dq:
        # delete entries have a ts; if none do (older format), fall back to file mtime
        oldest_ts = min((float(e.get("ts", 0) or 0) for e in dq), default=0)
        if oldest_ts <= 0:
            try:
                oldest_ts = os.path.getmtime(DELETE_QUEUE)
            except OSError:
                oldest_ts = now
        age = now - oldest_ts
        if age > STUCK_AFTER_SEC:
            alerts.append(f"delete queue STUCK: {len(dq)} item(s), oldest waiting "
                          f"{int(age // 60)}m")

    mq = _load(MOVE_QUEUE)
    if mq:
        # move entries have no ts; use the file mtime as a proxy for "not draining"
        try:
            mtime = os.path.getmtime(MOVE_QUEUE)
        except OSError:
            mtime = now
        age = now - mtime
        if age > STUCK_AFTER_SEC:
            alerts.append(f"move queue STUCK: {len(mq)} item(s), unchanged for "
                          f"{int(age // 60)}m")

    if alerts:
        print("⚠️ media-gallery reaper: " + "; ".join(alerts) +
              " — check media-gallery-trash/upload services on the gallery CT.")
        sys.exit(1)
    # healthy / empty -> silent
    sys.exit(0)


if __name__ == "__main__":
    main()
