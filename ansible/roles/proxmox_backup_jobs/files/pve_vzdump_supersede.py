#!/usr/bin/env python3
"""Delete THIS node's vzdump archives that a newer archive of the same guest supersedes.

Why: vzdump-nvme is a per-node local dir, not shared storage, and the backup jobs
carry one union vmid list on every node so a guest is always covered wherever HA
puts it. keep-last=1 only prunes within one node's storage, so when a guest moves
(HA failover, migration) its old archive stays on the old node forever, next to the
new one on the new node. 2026-11-15: 16 such leftovers, 115 GiB, on a pool that
also holds the guests' disks.

Rule (fail closed): an archive is deleted only if
  - the archive lives on this node,
  - a strictly newer archive of the same vmid exists on ANOTHER node, by more than
    MIN_NEWER_SECS, with a non-trivial size,
  - it is not protected,
  - every node's storage listing was read successfully (any error -> delete nothing).
The newest archive of a guest, and the only archive of a guest, are never touched.
Archives of guests that no longer exist are kept (newest copy) until someone
decides; they show up in pve_vzdump_orphan_bytes.

Metrics (textfile): pve_vzdump_* in pve_vzdump.prom.
DRY_RUN=1 lists what would go and deletes nothing.
"""

import json
import os
import subprocess
import sys
import time

STORAGE = os.environ.get("PVE_VZDUMP_STORAGE", "vzdump-nvme")
MIN_NEWER_SECS = 3600
MIN_NEWEST_BYTES = 1 << 20
DRY = os.environ.get("DRY_RUN") == "1"
TEXTFILE_DIR = os.environ.get("TEXTFILE_DIR", "/var/lib/node_exporter/textfile_collector")
NODE = os.uname().nodename


def pvesh(path, **params):
    cmd = ["pvesh", "get", path, "--output-format", "json"]
    for k, v in params.items():
        cmd += [f"--{k}", str(v)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"pvesh get {path}: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


def write_metrics(ok, deleted_bytes, pending_bytes, local_count, local_bytes, orphan_bytes):
    os.makedirs(TEXTFILE_DIR, exist_ok=True)
    now = int(time.time())
    prev = 0
    path = os.path.join(TEXTFILE_DIR, "pve_vzdump.prom")
    try:
        for line in open(path):
            if line.startswith("pve_vzdump_supersede_last_success_timestamp_seconds"):
                prev = int(float(line.split()[-1]))
    except OSError:
        pass
    last_ok = now if ok else prev
    body = (
        "# TYPE pve_vzdump_supersede_last_run_ok gauge\n"
        f"pve_vzdump_supersede_last_run_ok {1 if ok else 0}\n"
        "# TYPE pve_vzdump_supersede_last_success_timestamp_seconds gauge\n"
        f"pve_vzdump_supersede_last_success_timestamp_seconds {last_ok}\n"
        "# TYPE pve_vzdump_superseded_deleted_bytes gauge\n"
        f"pve_vzdump_superseded_deleted_bytes {deleted_bytes}\n"
        "# TYPE pve_vzdump_superseded_pending_bytes gauge\n"
        f"pve_vzdump_superseded_pending_bytes {pending_bytes}\n"
        "# TYPE pve_vzdump_local_archives gauge\n"
        f"pve_vzdump_local_archives {local_count}\n"
        "# TYPE pve_vzdump_local_bytes gauge\n"
        f"pve_vzdump_local_bytes {local_bytes}\n"
        "# TYPE pve_vzdump_orphan_bytes gauge\n"
        f"pve_vzdump_orphan_bytes {orphan_bytes}\n"
    )
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(body)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main():
    try:
        nodes = [n["node"] for n in pvesh("/nodes")]
        guests = {r["vmid"] for r in pvesh("/cluster/resources", type="vm")}
        archives = []
        for n in nodes:
            for i in pvesh(f"/nodes/{n}/storage/{STORAGE}/content", content="backup"):
                archives.append((i["vmid"], n, i["volid"], i["size"], i["ctime"], i.get("protected", 0)))
    except Exception as exc:  # fail closed: if any node cannot be read, delete nothing
        print(f"ABORT, nothing deleted: {exc}", file=sys.stderr)
        write_metrics(False, 0, 0, 0, 0, 0)
        return 1

    newest = {}
    for a in archives:
        if a[0] not in newest or a[4] > newest[a[0]][4]:
            newest[a[0]] = a
    local = [a for a in archives if a[1] == NODE]
    orphan = sum(a[3] for a in newest.values() if a[1] == NODE and a[0] not in guests)

    victims = []
    for vmid, _node, volid, size, ctime, prot in local:
        top = newest[vmid]
        if top[1] == NODE or prot:
            continue
        if top[4] - ctime > MIN_NEWER_SECS and top[3] >= MIN_NEWEST_BYTES:
            victims.append((vmid, volid, size, ctime, top))

    pending = sum(v[2] for v in victims)
    deleted = 0
    deleted_ids = set()
    failed = False
    for _vmid, volid, size, ctime, top in victims:
        stamp = time.strftime("%F %H:%M", time.localtime(ctime))
        print(
            f"{'WOULD DELETE' if DRY else 'delete'} {volid} ({size / 2**30:.1f} GiB, {stamp}); "
            f"newer copy on {top[1]} ({time.strftime('%F %H:%M', time.localtime(top[4]))})"
        )
        if DRY:
            continue
        r = subprocess.run(["pvesm", "free", volid], capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            deleted += size
            deleted_ids.add(volid)
        else:
            failed = True
            print(f"  FAILED: {r.stderr.strip()[:200]}", file=sys.stderr)
    print(
        f"{NODE}: {len(victims)} superseded, {deleted / 2**30:.1f} GiB freed"
        f"{' (dry run)' if DRY else ''}; orphan copies kept {orphan / 2**30:.1f} GiB"
    )
    if DRY:
        return 0
    left = [a for a in local if a[2] not in deleted_ids]
    write_metrics(not failed, deleted, pending - deleted, len(left), sum(a[3] for a in left), orphan)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
