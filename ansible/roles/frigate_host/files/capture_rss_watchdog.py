#!/usr/bin/env python3
"""Frigate capture-leak watchdog (frigate-01).

Problem: a single `frigate.capture:<cam>` process occasionally balloons to ~10 GB of
anonymous memory (healthy: ~200 MB; upstream 0.17.2 bug, root cause not yet identified).
It ends when the docker memcg (mem_limit) OOM-kills *that one child*. PID 1 survives
(`docker inspect` -> OOMKilled=false), so docker never restarts the container and the
camera sits dead until camera_health.py notices ~10 minutes later. The memcg also
thrashes just below its limit first, stalling every ffmpeg in the container.

What this does: poll per-process RSS every POLL seconds from the CT's own /proc view
(no API dependency) and, when a capture process crosses CAPTURE_LIMIT_MB (or any other
frigate.* process crosses OTHER_LIMIT_MB), (1) dump evidence so the leak can finally be
root-caused, then (2) restart the container. The restart is a full `docker compose restart`
because Frigate's s6 `finish` script halts the whole container whenever the frigate
service exits, so there is no cheaper Frigate-only restart.

Evidence lands in EVIDENCE_DIR/<utc-ts>-<cam>/ : RSS history for every frigate process,
/proc status + smaps_rollup + fd/thread counts of the offender, py-spy dump if the
binary is installed at /opt/frigate/py-spy, 15 min of container logs, /api/stats and
docker stats.
"""
import collections
import gzip
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

CAPTURE_LIMIT_MB = int(os.environ.get("CAPTURE_LIMIT_MB", "1536"))
OTHER_LIMIT_MB = int(os.environ.get("OTHER_LIMIT_MB", "3072"))
POLL = int(os.environ.get("POLL", "15"))
COOLDOWN = int(os.environ.get("RESTART_COOLDOWN", "300"))
HEARTBEAT = int(os.environ.get("HEARTBEAT", "900"))
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR", "/var/log/frigate-leak")
STATE_PATH = "/var/lib/frigate-rss-watchdog.json"
COMPOSE = "/opt/frigate/docker-compose.yml"
PYSPY = "/opt/frigate/py-spy"
FRIGATE = os.environ.get("FRIGATE_URL", "http://localhost:5000")
DRY = "--dry-run" in sys.argv
ONCE = "--once" in sys.argv
KEEP_EVIDENCE = 20

PROC_RE = re.compile(r"^(frigate\.[a-z_]+(?::\S+)?|python3 -u -m frigate)")


def log(msg):
    print(msg, flush=True)  # journald timestamps it


def sh(cmd, timeout=60):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (res.stdout or "") + (res.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"<{cmd[0]} failed: {exc}>"


def frigate_procs():
    """[(pid, rss_mb, etimes, title)] for frigate processes visible in the CT."""
    out = subprocess.run(["ps", "-eo", "pid=,rss=,etimes=,args="], capture_output=True,
                         text=True, timeout=20).stdout
    procs = []
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4 or not PROC_RE.match(parts[3]):
            continue
        procs.append((int(parts[0]), int(parts[1]) // 1024, int(parts[2]), parts[3].split()[0]
                      if parts[3].startswith("frigate.") else "frigate-main"))
    return procs


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def write(path, text):
    with open(path, "w", encoding="utf-8", errors="replace") as fh:
        fh.write(text)


def collect_evidence(pid, title, rss_mb, history):
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    cam = title.split(":", 1)[1] if ":" in title else title
    d = os.path.join(EVIDENCE_DIR, f"{stamp}-{cam}")
    os.makedirs(d, exist_ok=True)
    write(os.path.join(d, "trigger.txt"), f"{title} pid={pid} rss={rss_mb}MB limit=capture:"
          f"{CAPTURE_LIMIT_MB}/other:{OTHER_LIMIT_MB}\n")
    write(os.path.join(d, "rss_history.json"), json.dumps(
        {str(k): list(v) for k, v in history.items()}, indent=0))
    p = f"/proc/{pid}"
    for name in ("status", "smaps_rollup", "limits", "io"):
        try:
            with open(f"{p}/{name}", encoding="utf-8", errors="replace") as fh:
                write(os.path.join(d, f"proc_{name}.txt"), fh.read())
        except OSError as exc:
            write(os.path.join(d, f"proc_{name}.txt"), f"unreadable: {exc}\n")
    try:
        fds = os.listdir(f"{p}/fd")
        kinds = collections.Counter()
        for fd in fds:
            try:
                tgt = os.readlink(f"{p}/fd/{fd}")
            except OSError:
                continue
            kinds[re.sub(r"[:\[]?\d+\]?", "N", tgt)] += 1
        write(os.path.join(d, "fds.txt"), f"count={len(fds)} threads={len(os.listdir(p + '/task'))}\n"
              + "\n".join(f"{n:6d} {k}" for k, n in kinds.most_common(30)) + "\n")
    except OSError as exc:
        write(os.path.join(d, "fds.txt"), f"unreadable: {exc}\n")
    if os.access(PYSPY, os.X_OK):
        write(os.path.join(d, "pyspy_dump.txt"), sh([PYSPY, "dump", "--pid", str(pid)], 25))
    write(os.path.join(d, "docker_stats.txt"), sh(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}} {{.CPUPerc}} {{.PIDs}}"], 30))
    try:
        with urllib.request.urlopen(f"{FRIGATE}/api/stats", timeout=8) as resp:
            write(os.path.join(d, "api_stats.json"), resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        write(os.path.join(d, "api_stats.json"), f"unreachable: {exc}\n")
    logs = sh(["docker", "logs", "frigate", "--since", "15m"], 60)
    with gzip.open(os.path.join(d, "container_logs_15m.txt.gz"), "wt", encoding="utf-8",
                   errors="replace") as fh:
        fh.write(logs)
    # Log-volume summary: a flood of one repeating line is the leading leak hypothesis.
    per_min = collections.Counter(l[11:16] for l in logs.splitlines() if len(l) > 16)
    top = collections.Counter(re.sub(r"\d+", "N", l[30:130]) for l in logs.splitlines())
    write(os.path.join(d, "log_summary.txt"), "lines/min: " + json.dumps(sorted(per_min.items()))
          + "\n\ntop repeating lines:\n" + "\n".join(f"{n:7d} {k}" for k, n in top.most_common(15)) + "\n")
    # prune old evidence
    dirs = sorted(x for x in os.listdir(EVIDENCE_DIR) if os.path.isdir(os.path.join(EVIDENCE_DIR, x)))
    for old in dirs[:-KEEP_EVIDENCE]:
        sh(["rm", "-rf", os.path.join(EVIDENCE_DIR, old)], 30)
    return d


def check(history, state):
    now = time.time()
    procs = frigate_procs()
    live = {p[0] for p in procs}
    for pid in list(history):
        if pid not in live:
            del history[pid]
    offender = None
    for pid, rss, _age, title in procs:
        history[pid].append((int(now), rss, title))
        limit = CAPTURE_LIMIT_MB if title.startswith("frigate.capture") else OTHER_LIMIT_MB
        if rss > limit and (offender is None or rss > offender[1]):
            offender = (pid, rss, title)
    if not offender:
        return procs
    pid, rss, title = offender
    since = now - float(state.get("last_restart", 0))
    if since < COOLDOWN:
        log(f"LEAK {title} pid={pid} rss={rss}MB over limit but restart cooldown has "
            f"{int(COOLDOWN - since)}s left")
        return procs
    log(f"LEAK {title} pid={pid} rss={rss}MB over limit - collecting evidence then restarting Frigate")
    try:
        d = collect_evidence(pid, title, rss, history)
        log(f"evidence saved to {d}")
    except Exception as exc:  # noqa: BLE001  never let evidence failure block the restart
        log(f"evidence collection failed: {exc}")
    if DRY:
        return procs
    out = sh(["docker", "compose", "-f", COMPOSE, "restart", "frigate"], 180)
    state["last_restart"] = now
    state["restarts"] = int(state.get("restarts", 0)) + 1
    state["last_offender"] = f"{title}:{rss}MB"
    save_state(state)
    history.clear()
    log(f"restarted Frigate (total watchdog restarts: {state['restarts']}) {out.strip()[-200:]}")
    return procs


def main():
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    history = collections.defaultdict(lambda: collections.deque(maxlen=60))
    state = load_state()
    last_beat = 0.0
    log(f"watching frigate.capture>{CAPTURE_LIMIT_MB}MB other>{OTHER_LIMIT_MB}MB every {POLL}s"
        f"{' (dry-run)' if DRY else ''}")
    while True:
        try:
            procs = check(history, state)
            if time.time() - last_beat >= HEARTBEAT or ONCE:
                caps = sorted(((r, t) for _p, r, _a, t in procs if t.startswith("frigate.capture")),
                              reverse=True)
                log("ok: " + (", ".join(f"{t.split(':')[1]}={r}MB" for r, t in caps) or "no capture procs")
                    + f" (watchdog restarts so far: {state.get('restarts', 0)})")
                last_beat = time.time()
        except Exception as exc:  # noqa: BLE001
            log(f"check failed: {exc}")
        if ONCE:
            return
        time.sleep(POLL)


if __name__ == "__main__":
    main()
