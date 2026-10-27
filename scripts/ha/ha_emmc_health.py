#!/usr/bin/env python3
"""Track the Home Assistant Green's eMMC wear and free space in VictoriaMetrics.

The box runs everything -- config, recorder DB, backups -- on one soldered 32 GB
eMMC. Space has an alert already (ha_host_disk_low at 3 GB); wear did not, and it
is the part that ends the device's life. The kernel exposes the JEDEC lifetime
estimate at /sys/block/mmcblk0/device/life_time as two hex bytes (type A and
type B estimates): 0x01-0x0A mean 0-10% ... 90-100% of rated life consumed,
0x0B means the device has exceeded it.

Runs from hermes-gw-01 over the HAOS SSH add-on; read-only.

Metrics:
  ha_emmc_life_used_percent{estimate="a"|"b"}
  ha_emmc_free_bytes
  ha_emmc_size_bytes
"""
import subprocess
import sys

HA_HOST = "192.168.86.2"  # the HAOS SSH add-on does not answer to mDNS from hermes-gw-01
HA_PORT = "2222"
VM = "http://172.16.0.42:8428/api/v1/import/prometheus"

CMD = (
    "cat /sys/block/mmcblk0/device/life_time; "
    "cat /sys/block/mmcblk0/size; "
    "df -B1 / | tail -1 | awk '{print $2\" \"$4}'"
)


def sample():
    out = subprocess.run(
        ["ssh", "-p", HA_PORT, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
         "-i", "/root/.ssh/ha_backup", "-o", "IdentitiesOnly=yes",
         f"root@{HA_HOST}", CMD],
        capture_output=True, text=True, timeout=45,
    )
    if out.returncode != 0:
        raise SystemExit(f"ssh failed: {out.stderr.strip()[:200]}")
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    life = lines[0]
    size_sectors = int(lines[1])
    total, avail = (int(x) for x in lines[2].split())
    a_hex, b_hex = life.split()
    metrics = []
    for label, raw in (("a", a_hex), ("b", b_hex)):
        code = int(raw, 16)
        if 1 <= code <= 0x0A:
            metrics.append(f'ha_emmc_life_used_percent{{estimate="{label}"}} {(code - 1) * 10}')
        elif code == 0x0B:
            # exceeded the rated lifetime: report 100 so the alert fires
            metrics.append(f'ha_emmc_life_used_percent{{estimate="{label}"}} 100')
    metrics.append(f"ha_emmc_free_bytes {avail}")
    metrics.append(f"ha_emmc_size_bytes {size_sectors * 512}")
    return metrics, life, avail


def main():
    metrics, life, avail = sample()
    body = "\n".join(metrics) + "\n"
    import urllib.request
    req = urllib.request.Request(VM, data=body.encode(),
                                 headers={"Content-Type": "text/plain"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as exc:  # noqa: BLE001 - report and fail, don't crash the timer
        print(f"warn: metric push failed: {exc}", file=sys.stderr)
    print(f"ha-emmc: life_time={life} free={avail / 2**30:.1f} GiB")


if __name__ == "__main__":
    main()
