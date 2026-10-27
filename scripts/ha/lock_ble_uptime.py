#!/usr/bin/env python3
"""Report BLE availability for a Home Assistant entity, day by day.

Used for the front-door lock, which drops off yalexs_ble whenever its BLE link
gets marginal. Answering "did moving the antenna help?" needs numbers, not a
feeling -- this prints the same measure before and after a change.

  ./lock_ble_uptime.py                        # last 7 days, front door lock
  ./lock_ble_uptime.py --entity lock.front_door_4 --days 14
  ./lock_ble_uptime.py --recent                # last 6h transitions + 30/60/120m

Data source: VictoriaMetrics, series homeassistant_entity_available.
"""
import argparse
import collections
import datetime as dt
import json
import urllib.parse
import urllib.request

VM = "http://172.16.0.42:8428"


def fetch(entity: str, start: int, end: int, step: int = 60):
    q = f'homeassistant_entity_available{{entity="{entity}"}}'
    url = f"{VM}/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": q, "start": start, "end": end, "step": str(step)}
    )
    data = json.load(urllib.request.urlopen(url, timeout=60))
    res = data["data"]["result"]
    if not res:
        raise SystemExit(f"no series for {entity}")
    return [(float(ts), float(v)) for ts, v in res[0]["values"]]


def daily(vals):
    per_day = collections.defaultdict(lambda: [0, 0])
    for ts, v in vals:
        day = dt.datetime.fromtimestamp(ts).strftime("%m-%d")
        per_day[day][0] += 1
        if v == 0:
            per_day[day][1] += 1
    print("day     minutes  down_min  uptime%")
    for day, (n, z) in sorted(per_day.items()):
        flag = "  <-- degraded" if n - z < n * 0.95 else ""
        print(f"{day}  {n:8d}  {z:8d}  {100 * (n - z) / n:6.2f}{flag}")
    run = best = 0
    best_end = None
    for ts, v in vals:
        if v == 0:
            run += 1
            if run > best:
                best, best_end = run, ts
        else:
            run = 0
    if best_end:
        print(f"longest outage: {best} min, ending "
              f"{dt.datetime.fromtimestamp(best_end):%Y-%m-%d %H:%M}")


def recent(vals):
    prev = None
    trans = []
    for ts, v in vals:
        if prev is None or v != prev:
            trans.append((dt.datetime.fromtimestamp(ts).strftime("%H:%M"),
                          "UP" if v == 1 else "DOWN"))
            prev = v
    print("transitions (last 6h):", trans[-16:])
    end = vals[-1][0]
    for win in (30, 60, 120, 360):
        seg = [v for ts, v in vals if ts >= end - win * 60]
        if seg:
            print(f"last {win:3d} min: {100 * sum(seg) / len(seg):5.1f}% up")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entity", default="lock.front_door_4")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--recent", action="store_true", help="6h transitions + windowed uptime")
    args = ap.parse_args()
    end = int(dt.datetime.now().timestamp())
    if args.recent:
        recent(fetch(args.entity, end - 6 * 3600, end))
    else:
        daily(fetch(args.entity, end - args.days * 86400, end))


if __name__ == "__main__":
    main()
