#!/usr/bin/env python3
"""
BWT throttle measurement rig — orchestrator.

Drives one throttle measurement experiment end-to-end:

  1. Take t=0 snapshot of TS /metrics + ZS netdiag firewall counters.
  2. Start a background sampler thread polling /metrics at the configured
     interval; rows go to <outdir>/metrics.csv.
  3. POST a saved_action targeting "All Computers" deploying the named
     package. Capture the saved_action_id + first action_id.
  4. Poll /api/v2/actions/<id>/status until all expected clients report
     terminal (success / failed) or until the deadline.
  5. Stop the sampler.
  6. Take t=end snapshot of /metrics + ZS netdiag firewall.
  7. Per-client cache verification: pct exec on each bwt-tc-XX to stat
     the cached file.
  8. Dump everything to <outdir>/ along with a run-manifest.json that
     summarizes the run inputs + outputs.

Usage:
  bwt-run-experiment.py --package-id 46 \
      --action-name "BWT throttle baseline" \
      --outdir-base "/path/to/case/bwt-runs" \
      [--targets all|<group_id>] \
      [--interval 1] [--max-duration 9000]

Token + URL come from environment (BWT_API_TOKEN, BWT_TS_URL) or the
defaults (lab values).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shlex
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


# --- defaults --------------------------------------------------------------

DEFAULT_TS_URL = os.environ.get("BWT_TS_URL", "https://10.99.0.10")
DEFAULT_API_TOKEN = os.environ.get(
    "BWT_API_TOKEN",
    # Lab API token from group_vars/all/tanium_secrets.yml. Replace per env.
    "token-388a95d3c103e864ccc22dfdb78e21c6212f8e08f675ee8acf71eb8a84",
)
ZONE_SERVERS = ["bwt-zs-01", "bwt-zs-02"]
CLIENT_VMIDS = list(range(320, 328))  # bwt-tc-01..08
PVE_NODE_FOR_VMID = {
    320: "pve01", 321: "pve01", 326: "pve01",
    322: "pve02", 323: "pve02", 327: "pve02",
    324: "pve03", 325: "pve03",
}
PVE_JUMP = "root@192.168.86.11"

# Metrics we care about (full match against the Prometheus exposition).
METRIC_PATTERN = re.compile(
    r"^(tanium_throttle_bytes_used_total|"
    r"tanium_client_external_download_bytes_read_total|"
    r"tanium_throttle_writes_total|"
    r"tanium_chunk_request_queue_dropped_total|"
    r"tanium_client_connection_count)\b"
)


# --- HTTP helpers ----------------------------------------------------------

def _ssl_ctx():
    """Permissive SSL ctx — TS uses self-signed cert."""
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def http_request(url: str, *, token: str, method: str = "GET",
                 body: bytes | None = None, content_type: str | None = None,
                 timeout: int = 30) -> tuple[int, bytes]:
    headers = {"session": token}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# --- ZS dispatcher (via ansible — handles password keyboard-interactive) ---

def zs_firewall_snapshot(zs_host: str) -> str:
    """Invoke `netdiag show firewall` via ansible. Returns raw stdout.

    Ansible config + vault password are discovered relative to the
    repo's `ansible/` directory — we run ansible with cwd set there so
    `ansible.cfg` (and `.vault_pass`) resolve correctly.
    """
    repo = Path(__file__).resolve().parents[2]  # scripts/tanium/ -> repo root
    ansible_dir = repo / "ansible"
    # Force ANSIBLE_CONFIG so we still pick up vault_password_file even
    # if the caller has set a global override.
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(ansible_dir / "ansible.cfg")
    cmd = [
        "ansible", "-i", "inventory/proxmox.yml",
        zs_host, "-m", "raw",
        "-a", "netdiag show firewall",
    ]
    proc = subprocess.run(cmd, cwd=ansible_dir, env=env,
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ansible netdiag-show-firewall failed for {zs_host}: "
            f"rc={proc.returncode} stderr={proc.stderr[:300]} stdout={proc.stdout[:300]}"
        )
    # ansible raw output has a header line `<host> | CHANGED | rc=0 >>` then payload.
    out = proc.stdout
    if " >>\n" in out:
        out = out.split(" >>\n", 1)[1]
    return out


def _iptables_count(s: str) -> int:
    """Parse `1234`, `493K`, `187M`, `1.5G` into an int (bytes)."""
    s = s.strip()
    if not s:
        return 0
    mult = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    if s[-1] in mult:
        return int(float(s[:-1]) * mult[s[-1]])
    return int(s)


def parse_firewall_chains(raw: str) -> dict:
    """Extract iptables byte counters from TanOS `netdiag show firewall`.

    Returns a flat dict keyed by `<family>_<chain>` plus per-rule entries.
    `netdiag show firewall` prints both IPv4 and IPv6 tables; we tag the
    family so we can isolate IPv4 (where peer-protocol traffic lives).

    Schema:
        ipv4_INPUT_default     = {packets, bytes}    # default-policy aggregate
        ipv4_INPUT_dpt_17472   = {packets, bytes}    # per-rule inbound
        ipv4_OUTPUT_default    = {packets, bytes}
        ipv6_* mirrored

    Default-policy lines look like:
        Chain INPUT (policy DROP 0 packets, 0 bytes)
        Chain OUTPUT (policy ACCEPT 1197K packets, 187M bytes)

    Per-rule lines we care about look like:
        8226  493K ACCEPT     tcp ... tcp dpt:17472 /* service=taniumzoneserver */
    """
    out: dict = {}
    family = "ipv4"  # default; flips on "IPv6 Firewall:"
    current_chain = None  # tracks which chain we're inside for per-rule lines

    chain_re = re.compile(
        r"Chain (\w+) \(policy \w+ (\S+) packets, (\S+) bytes\)"
    )
    rule_17472_re = re.compile(
        r"\s*(\S+)\s+(\S+)\s+ACCEPT\s+tcp\b.*tcp dpt:17472"
    )

    for line in raw.splitlines():
        if "IPv6 Firewall:" in line:
            family = "ipv6"
            continue
        if "IPv4 Firewall:" in line:
            family = "ipv4"
            continue

        m = chain_re.match(line)
        if m:
            current_chain = m.group(1)
            key = f"{family}_{current_chain}_default"
            out[key] = {
                "packets": _iptables_count(m.group(2)),
                "bytes": _iptables_count(m.group(3)),
            }
            continue

        m = rule_17472_re.match(line)
        if m and current_chain:
            key = f"{family}_{current_chain}_dpt_17472"
            out[key] = {
                "packets": _iptables_count(m.group(1)),
                "bytes": _iptables_count(m.group(2)),
            }
    return out


# --- TS /metrics sampler ---------------------------------------------------

class MetricsSampler(threading.Thread):
    def __init__(self, ts_url: str, token: str, outpath: Path, interval: float):
        super().__init__(daemon=True)
        self.ts_url = ts_url
        self.token = token
        self.outpath = outpath
        self.interval = interval
        # NB: do NOT name this `self._stop` — threading.Thread already uses
        # that name as an internal method, and overriding it breaks
        # `thread.join()`.
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        with self.outpath.open("w", buffering=1) as fp:
            fp.write("epoch_ms_local,metric_line\n")
            while not self._stop_event.is_set():
                ts_ms = int(time.time() * 1000)
                try:
                    status, body = http_request(
                        f"{self.ts_url}/metrics",
                        token=self.token,
                        timeout=max(2, int(self.interval)),
                    )
                except (urllib.error.URLError, socket.timeout, TimeoutError):
                    self._stop_event.wait(self.interval)
                    continue
                if status != 200:
                    self._stop_event.wait(self.interval)
                    continue
                for line in body.decode("utf-8", errors="replace").splitlines():
                    if line.startswith("#") or not line.strip():
                        continue
                    if METRIC_PATTERN.match(line):
                        fp.write(f"{ts_ms},{line}\n")
                # Always sleep exactly the interval rather than "interval - elapsed"
                # — drift is tolerated; timestamps are recorded per-sample.
                self._stop_event.wait(self.interval)


# --- Action orchestration --------------------------------------------------

def get_all_computers_action_group_id(ts_url: str, token: str) -> int:
    """Find the 'Default - All Computers' action_group.

    After Default Content import there are two stock action_groups:
        id=3 'Default'                  -> computer group 2
        id=4 'Default - All Computers'  -> computer group 1 (every machine)

    We want id=4 — runs an action against every registered client.
    """
    status, body = http_request(f"{ts_url}/api/v2/action_groups", token=token)
    if status != 200:
        raise RuntimeError(
            f"GET /action_groups failed: status={status} body={body[:200]!r}"
        )
    for ag in json.loads(body).get("data", []):
        if ag.get("name") == "Default - All Computers":
            return ag["id"]
    raise RuntimeError(
        "action_group 'Default - All Computers' not found — has Default "
        "Content been imported on this TS?"
    )


def deploy_package(ts_url: str, token: str, package_id: int, name: str,
                   action_group_id: int) -> dict:
    """POST a saved_action that deploys the package via the action_group.

    Returns the response data (includes id + last_action.id).
    """
    payload = {
        "name": name,
        "action_group": {"id": action_group_id},
        "package_spec": {"id": package_id},
        "distribute_seconds": 60,
        "expire_seconds": 7200,
        "start_now_flag": True,
        "approved_flag": True,
    }
    status, body = http_request(
        f"{ts_url}/api/v2/saved_actions",
        token=token, method="POST",
        body=json.dumps(payload).encode(),
        content_type="application/json",
    )
    if status not in (200, 201):
        raise RuntimeError(f"saved_action POST failed: status={status} body={body!r}")
    return json.loads(body)["data"]


def get_action(ts_url: str, token: str, action_id: int) -> dict:
    """Get the action's metadata. Status field shows Open/Closed."""
    status, body = http_request(f"{ts_url}/api/v2/actions/{action_id}", token=token)
    if status == 200:
        return json.loads(body).get("data", {})
    return {"_http_status": status, "_body": body[:500]}


def count_clients_with_cached_file(file_name: str) -> dict:
    """For each bwt-tc-XX, check if /opt/Tanium/TaniumClient/Downloads/<file_name>
    exists and report its size. Returns {vmid: {present: bool, size: int|None}}."""
    result = {}
    for vmid in CLIENT_VMIDS:
        node = PVE_NODE_FOR_VMID[vmid]
        try:
            raw = pct_exec(
                node, vmid,
                f"stat -c%s /opt/Tanium/TaniumClient/Downloads/{file_name} 2>/dev/null || echo MISSING",
                timeout=10,
            )
            raw = raw.strip()
            if raw == "MISSING" or not raw:
                result[vmid] = {"present": False, "size": None}
            else:
                try:
                    result[vmid] = {"present": True, "size": int(raw.splitlines()[-1])}
                except ValueError:
                    result[vmid] = {"present": False, "size": None, "raw": raw}
        except subprocess.TimeoutExpired:
            result[vmid] = {"present": False, "size": None, "error": "timeout"}
    return result


# --- Per-client snapshot ---------------------------------------------------

def pct_exec(node: str, vmid: int, cmd: str, timeout: int = 30) -> str:
    # Two-hop SSH: control machine -> PVE_JUMP -> $node -> `pct exec`.
    # We invoke the outer ssh as a list (no shell on our side), but the
    # *inner* remote command is necessarily a single shell-quoted string
    # — the remote sshd parses argv[1] through /bin/sh. Quote each layer
    # so an attacker-controlled `cmd` cannot break out (e.g. embedded
    # quotes, backticks, or `;`). The inputs in this script are all
    # internally generated (vmid/node from inventory, cmd from a fixed
    # set), but defense-in-depth is cheap.
    inner = f"pct exec {shlex.quote(str(vmid))} -- {cmd}"
    middle = f"ssh -o StrictHostKeyChecking=no {shlex.quote(node)} {shlex.quote(inner)}"
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", PVE_JUMP, middle],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    return proc.stdout


def client_cache_snapshot() -> dict:
    """For each bwt-tc-XX, ls the Downloads dir and return file→size map."""
    out = {}
    for vmid in CLIENT_VMIDS:
        node = PVE_NODE_FOR_VMID[vmid]
        try:
            raw = pct_exec(node, vmid, "ls -la /opt/Tanium/TaniumClient/Downloads/ 2>/dev/null || true")
        except subprocess.TimeoutExpired:
            out[vmid] = {"error": "timeout"}
            continue
        out[vmid] = {"raw": raw}
    return out


# --- Run -------------------------------------------------------------------

def utc_iso(): return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def run_experiment(args):
    ts_url = args.ts_url
    token = args.api_token
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    outdir = Path(args.outdir_base) / run_id
    outdir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": run_id,
        "start_utc": utc_iso(),
        "ts_url": ts_url,
        "package_id": args.package_id,
        "action_name": args.action_name,
        "interval_sec": args.interval,
        "max_duration_sec": args.max_duration,
        "zone_servers": ZONE_SERVERS,
        "client_vmids": CLIENT_VMIDS,
    }
    print(f"[bwt-run] outdir={outdir}")
    print(f"[bwt-run] run_id={run_id}")

    # Step 1: pre-snapshot.
    print("[bwt-run] T-0: capturing pre-run snapshot...")
    pre_metrics = http_request(f"{ts_url}/metrics", token=token)
    (outdir / "metrics-pre.txt").write_bytes(pre_metrics[1])

    pre_fw = {}
    for zs in ZONE_SERVERS:
        raw = zs_firewall_snapshot(zs)
        (outdir / f"firewall-pre-{zs}.txt").write_text(raw)
        pre_fw[zs] = parse_firewall_chains(raw)

    # Step 2: start sampler.
    print(f"[bwt-run] starting /metrics sampler @ {args.interval}s interval")
    sampler = MetricsSampler(ts_url, token, outdir / "metrics.csv", args.interval)
    sampler.start()

    # Step 3: post saved_action.
    ag_id = get_all_computers_action_group_id(ts_url, token)
    print(f"[bwt-run] deploying package_id={args.package_id} via action_group_id={ag_id}")
    sa = deploy_package(ts_url, token, args.package_id, args.action_name, ag_id)
    print(f"[bwt-run] saved_action.id={sa.get('id')} action.id={sa.get('action_group',{}).get('id')}")
    manifest["saved_action"] = sa

    # In 7.8 the saved_action response embeds last_action.id immediately.
    action_id = sa.get("last_action", {}).get("id")
    if not action_id:
        # Fallback: poll briefly for the issued action.
        sa_id = sa.get("id")
        for _ in range(20):
            st, body = http_request(
                f"{ts_url}/api/v2/actions?saved_action_id={sa_id}",
                token=token,
            )
            if st == 200:
                actions = json.loads(body).get("data", [])
                if actions:
                    action_id = actions[0]["id"]
                    break
            time.sleep(1)
    print(f"[bwt-run] issued action.id={action_id}")
    manifest["action_id"] = action_id

    # Step 4: poll per-client cache-file presence until all 8 have the
    # file OR deadline expires. The file lands at
    #   /opt/Tanium/TaniumClient/Downloads/Action_<id>/<file_name>
    # We pull the file_name out of the package_spec the saved_action
    # already gave us back.
    pkg_files = sa.get("package_spec", {}).get("files", [])
    if not pkg_files:
        # Older response shape may omit files; re-fetch.
        pkg_files = http_request(
            f"{ts_url}/api/v2/packages/{args.package_id}",
            token=token,
        )
        try:
            pkg_files = json.loads(pkg_files[1]).get("data", {}).get("files", [])
        except (ValueError, KeyError):
            pkg_files = []
    file_name = pkg_files[0]["name"] if pkg_files else None
    expected_size = pkg_files[0].get("size") if pkg_files else None
    print(f"[bwt-run] target file_name={file_name} size={expected_size}")
    manifest["target_file"] = {"name": file_name, "size": expected_size}

    # The cache path includes Action_<id>/<file>. Try a couple of common
    # shapes; the first poll round will tell us which works.
    candidate_paths = []
    if file_name:
        candidate_paths = [
            f"Action_{action_id}/{file_name}",
            f"Action_{action_id}/Payload/{file_name}",
            file_name,
        ]

    deadline = time.time() + args.max_duration
    last_log = 0.0
    final_status = None
    cache_progress: dict = {}
    while time.time() < deadline:
        # Probe per-client. Use the first candidate path that any client
        # has present, then stick with it.
        for path in candidate_paths:
            cache_progress = count_clients_with_cached_file(path)
            if any(v.get("present") for v in cache_progress.values()):
                manifest.setdefault("cache_path_used", path)
                break
        n_present = sum(1 for v in cache_progress.values() if v.get("present"))
        if time.time() - last_log >= 5:
            sizes = [v.get("size") for v in cache_progress.values() if v.get("present")]
            print(f"[bwt-run] poll: {n_present}/{len(CLIENT_VMIDS)} clients have file, sizes={sizes}")
            last_log = time.time()
        if n_present >= len(CLIENT_VMIDS):
            print(f"[bwt-run] all {n_present} clients have the file")
            final_status = {"clients_cached": n_present, "cache_progress": cache_progress}
            break
        time.sleep(args.interval * 3)

    if not final_status:
        print(f"[bwt-run] WARNING: deadline reached; "
              f"{sum(1 for v in cache_progress.values() if v.get('present'))}/{len(CLIENT_VMIDS)} cached")
        final_status = {"deadline_exceeded": True, "cache_progress": cache_progress}

    # Step 5: stop sampler.
    print("[bwt-run] stopping sampler")
    sampler.stop()
    sampler.join(timeout=5)

    # Step 6: post-snapshot.
    print("[bwt-run] T-end: capturing post-run snapshot...")
    post_metrics = http_request(f"{ts_url}/metrics", token=token)
    (outdir / "metrics-post.txt").write_bytes(post_metrics[1])

    post_fw = {}
    for zs in ZONE_SERVERS:
        raw = zs_firewall_snapshot(zs)
        (outdir / f"firewall-post-{zs}.txt").write_text(raw)
        post_fw[zs] = parse_firewall_chains(raw)

    # Step 7: per-client cache verification.
    print("[bwt-run] capturing per-client cache state")
    clients = client_cache_snapshot()
    (outdir / "clients-state.json").write_text(json.dumps(clients, indent=2))

    # Manifest deltas.
    manifest["end_utc"] = utc_iso()
    manifest["firewall_delta"] = {}
    for zs in ZONE_SERVERS:
        pre = pre_fw.get(zs, {})
        post = post_fw.get(zs, {})
        deltas = {}
        for key in set(pre) | set(post):
            p_pkts = pre.get(key, {}).get("packets", 0)
            p_bts = pre.get(key, {}).get("bytes", 0)
            q_pkts = post.get(key, {}).get("packets", 0)
            q_bts = post.get(key, {}).get("bytes", 0)
            deltas[key] = {"packets": q_pkts - p_pkts, "bytes": q_bts - p_bts,
                           "pre": pre.get(key, {}), "post": post.get(key, {})}
        manifest["firewall_delta"][zs] = deltas
    if final_status:
        manifest["final_status"] = final_status
    else:
        manifest["final_status"] = "deadline_exceeded"

    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(f"[bwt-run] DONE. Artifacts: {outdir}")
    return outdir


def main():
    ap = argparse.ArgumentParser(description="BWT throttle measurement orchestrator")
    ap.add_argument("--package-id", type=int, required=True, help="package_id to deploy")
    ap.add_argument("--action-name", required=True, help="saved_action.name")
    ap.add_argument("--outdir-base", required=True, help="directory to dump runs under")
    ap.add_argument("--ts-url", default=DEFAULT_TS_URL)
    ap.add_argument("--api-token", default=DEFAULT_API_TOKEN)
    ap.add_argument("--interval", type=float, default=1.0, help="sample interval in seconds")
    ap.add_argument("--max-duration", type=int, default=9000, help="hard cap in seconds")
    args = ap.parse_args()
    run_experiment(args)


if __name__ == "__main__":
    main()
