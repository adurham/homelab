#!/usr/bin/env python3
"""ups_autoshutdown — orderly guest shutdown + auto-recovery for the lab-corner UPS.

WHY THIS EXISTS
  The lab corner (pve01/02/03 + GS108 + basement pod + amd-workstation) sits on a
  CyberPower GX1500U. Guests (LXCs/VMs) hard-dying on battery exhaustion is the
  expensive failure (fsck, corruption class seen on pve03 before), so this daemon
  watches the UPS and, when the battery is genuinely low and the corner is running
  on battery, stops every guest gracefully (with a bounded deadline), then
  restarts exactly what it stopped once mains is stable again.

SAFETY MODEL
  * It NEVER shuts down a node. Only guests. Nodes stay up on battery; if the
    battery exhausts, the UPS cuts them (the exact AC-loss path all three nodes
    already auto-recover from per BIOS settings).
  * It NEVER hard-stops a guest before its graceful window expires, except after
    the global sequence deadline (protects the battery window).
  * dry_run (config) = log/announce only, no state transitions. Used for field
    validation before arming.
  * A 'disabled' flag file makes every cycle a no-op.
  * Recovery restarts exactly the guests this daemon stopped (tracked in the
    state file), and only after mains has been stable for a configurable window.
  * Every failure to enumerate guests/UPS = no action (fail safe, log loudly).

OPERATOR COMMANDS
  ups-autoshutdown status                 # current mode/state + live evaluation
  ups-autoshutdown stop --only 302,105    # manual controlled stop (tracked)
  ups-autoshutdown recover                # restart everything the state file tracks
  ups-autoshutdown selftest               # scenario tests (no cluster access needed)
  ups-autoshutdown disable | enable       # toggle the disabled flag file

State:  /var/lib/ups-autoshutdown/state.json (atomic writes)
Config: /etc/ups-autoshutdown/config.json (re-read every cycle)
Metrics: textfile for Alloy's collector (ups_autoshutdown_*)
"""

import argparse
import fcntl
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time

LOG = logging.getLogger("ups-autoshutdown")

STATE_MONITORING = "monitoring"
STATE_STOPPING = "stopping"
STATE_STOPPED = "stopped"
STATE_RECOVERING = "recovering"
STATE_DISABLED = "disabled"

HA_SID_RE = re.compile(r"^(ct|vm):(\d+)$")
UPS_LINE_RE = re.compile(r"^([\w.]+):\s*(.*)$")

DEFAULT_CONFIG = {
    "dry_run": True,
    "poll_seconds": 5,
    "heartbeat_log_seconds": 300,
    # How often to refresh the guests_running metric (spawns pvesh ~0.9s CPU).
    "guests_metric_seconds": 60,
    "ob_sustain_seconds": 60,
    "stop_charge_percent": 20,
    "stop_runtime_seconds": 300,
    "phase1_name_regex": "^tc-",
    "graceful_timeout_seconds": 90,
    "hard_stop_grace_seconds": 30,
    "sequence_deadline_seconds": 480,
    "abort_online_seconds": 30,
    "recovery_ol_seconds": 300,
    "recovery_recent_extra_seconds": 300,
    "recovery_recent_window_seconds": 1800,
    "exclude_vmids": [],
    "state_dir": "/var/lib/ups-autoshutdown",
    "metrics_file": "/var/lib/node_exporter/textfile_collector/ups_autoshutdown.prom",
    "ups_name": "gx1500u",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def run_cmd(args, timeout=30):
    """Run a command list; return (rc, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ss: %s" % (timeout, " ".join(args))
    except OSError as exc:
        return 127, "", "exec failed: %s" % exc


def parse_ups_output(text):
    """Parse `upsc` key: value output into a dict."""
    out = {}
    for line in text.splitlines():
        m = UPS_LINE_RE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def read_ups(ups_name):
    """Read status/charge/runtime from NUT. Returns dict or None if unreadable.

    NB: must call `upsc <ups>` with NO variable arguments. `upsc <ups> var1
    var2` prints ONLY the raw values (no `key: value` prefixes), which cannot
    be parsed. The full dump always includes key: value lines. (Learned the
    hard way: the first deploy silently reported UPS UNREADABLE because of
    this.)
    """
    rc, out, _ = run_cmd(["upsc", ups_name], timeout=15)
    if rc != 0 or not out.strip():
        return None
    vals = parse_ups_output(out)
    status = vals.get("ups.status", "")
    if not status:
        return None

    def as_float(key):
        try:
            return float(vals[key])
        except (KeyError, ValueError):
            return None

    return {"status": status, "charge": as_float("battery.charge"), "runtime": as_float("battery.runtime")}


def is_on_battery(ups):
    return "OB" in ups["status"].upper().split()


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        LOG.warning("config %s missing; using defaults", path)
    except (OSError, ValueError) as exc:
        LOG.error("config %s unreadable (%s); using defaults", path, exc)
    return cfg


def atomic_write(path, text, mode=0o644):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------

class RealBackend:
    """Cluster access via pvesh / ha-manager (cluster-wide from any node)."""

    def list_running(self):
        rc, out, err = run_cmd(["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"],
                               timeout=30)
        if rc != 0:
            LOG.error("guest enumeration failed: %s", err.strip()[:300])
            return None
        try:
            res = json.loads(out)
        except ValueError as exc:
            LOG.error("guest enumeration parse failed: %s", exc)
            return None
        data = res.get("data", res) if isinstance(res, dict) else res
        rc2, out2, _ = run_cmd(["pvesh", "get", "/cluster/ha/resources", "--output-format", "json"], timeout=30)
        ha_sids = set()
        if rc2 == 0:
            try:
                hares = json.loads(out2)
                hadata = hares.get("data", hares) if isinstance(hares, dict) else hares
                ha_sids = {r.get("sid") for r in hadata if r.get("sid")}
            except ValueError:
                LOG.warning("HA resource list parse failed; treating guests as non-HA")

        guests = []
        for g in data:
            if g.get("type") not in ("lxc", "qemu"):
                continue
            if g.get("status") != "running" or g.get("template"):
                continue
            vmid = int(g.get("vmid"))
            sid = ("vm:%d" if g["type"] == "qemu" else "ct:%d") % vmid
            guests.append({
                "vmid": vmid,
                "type": g["type"],
                "node": g.get("node"),
                "name": g.get("name") or ("%s-%d" % (g["type"], vmid)),
                "sid": sid if sid in ha_sids else None,
            })
        return guests

    def stop(self, g, timeout):
        if g["sid"]:
            return run_cmd(["ha-manager", "crm-command", "stop", g["sid"], str(int(timeout))], timeout=30)[0] == 0
        return run_cmd(["pvesh", "create", "/nodes/%s/%s/%d/status/shutdown" % (g["node"], g["type"], g["vmid"]),
                        "--timeout", str(int(timeout))], timeout=30)[0] == 0

    def force_stop(self, g):
        if g["sid"]:
            return run_cmd(["ha-manager", "crm-command", "stop", g["sid"], "0"], timeout=30)[0] == 0
        return run_cmd(["pvesh", "create", "/nodes/%s/%s/%d/status/stop" % (g["node"], g["type"], g["vmid"])],
                       timeout=30)[0] == 0

    def start(self, g):
        if g["sid"]:
            return run_cmd(["ha-manager", "set", g["sid"], "--state", "started"], timeout=30)[0] == 0
        return run_cmd(["pvesh", "create", "/nodes/%s/%s/%d/status/start" % (g["node"], g["type"], g["vmid"])],
                       timeout=30)[0] == 0


class FakeBackend:
    """In-memory stand-in for tests. Guests stop after `stop_ticks`, or never
    if 'stubborn'."""

    def __init__(self, guests, stop_ticks=1):
        self.guests = {g["vmid"]: dict(g) for g in guests}
        self.running = set(self.guests)
        self.stop_ticks = stop_ticks
        self.stubborn = set()
        self.pending = {}   # vmid -> ticks remaining
        self.calls = []

    def list_running(self):
        return [g for vid, g in self.guests.items() if vid in self.running]

    def _schedule(self, vmid):
        if vmid in self.stubborn:
            self.pending[vmid] = 10 ** 9
        else:
            self.pending[vmid] = self.stop_ticks

    def stop(self, g, timeout):
        self.calls.append(("stop", g["vmid"], timeout))
        self._schedule(g["vmid"])
        return True

    def force_stop(self, g):
        self.calls.append(("force_stop", g["vmid"]))
        self.pending[g["vmid"]] = 1
        return True

    def start(self, g):
        self.calls.append(("start", g["vmid"]))
        self.running.add(g["vmid"])
        self.pending.pop(g["vmid"], None)
        return True

    def tick(self):
        for vmid, n in list(self.pending.items()):
            if n <= 1:
                self.running.discard(vmid)
                self.pending.pop(vmid, None)
            else:
                self.pending[vmid] = n - 1


# --------------------------------------------------------------------------
# engine
# --------------------------------------------------------------------------

class Engine:
    def __init__(self, cfg, backend, state, now=None):
        self.cfg = cfg
        self.backend = backend
        self.state = state
        self.now = now or time.time()
        self.ob_since = None
        self.online_since = None
        self.last_heartbeat = 0.0
        self.would_trigger = 0

    # -- state helpers ----------------------------------------------------
    def _transition(self, new_state, **extra):
        st = self.state
        if st.get("state") != new_state:
            LOG.info("state: %s -> %s %s", st.get("state"), new_state,
                     json.dumps(extra) if extra else "")
        st["state"] = new_state
        st["last_change"] = int(self.now)
        st.update(extra)
        self.persist()

    def persist(self):
        atomic_write(os.path.join(self.cfg["state_dir"], "state.json"),
                     json.dumps(self.state, indent=2, sort_keys=True) + "\n", mode=0o644)

    # -- evaluation -------------------------------------------------------
    def cycle(self, ups):
        cfg, st = self.cfg, self.state

        if os.path.exists(os.path.join(cfg["state_dir"], "disabled")):
            if st.get("state") != STATE_DISABLED:
                self._transition(STATE_DISABLED)
            return

        if ups is None:
            if st.get("state") == STATE_STOPPING:
                self._throttled_log("UPS unreadable during stop sequence; continuing (no abort evaluation)")
                self._advance_stopping(None, online=False)
            elif st.get("state") == STATE_RECOVERING:
                self._throttled_log("UPS unreadable during recovery; continuing")
                self._advance_recovery(None, online=False)
            else:
                self._throttled_log("UPS unreadable; no action")
            return

        online = not is_on_battery(ups)
        if online:
            self.ob_since = None
            if self.online_since is None:
                self.online_since = self.now
        else:
            self.online_since = None
            if self.ob_since is None:
                self.ob_since = self.now

        st["ob_seconds"] = int(self.now - self.ob_since) if self.ob_since else 0

        cur = st.get("state", STATE_MONITORING)
        if cur == STATE_DISABLED:
            self._transition(STATE_MONITORING)
            cur = STATE_MONITORING

        if cur == STATE_MONITORING:
            self._evaluate_trigger(ups, online)
        elif cur == STATE_STOPPING:
            self._advance_stopping(ups, online)
        elif cur == STATE_STOPPED:
            self._stopped_tick(ups, online)
        elif cur == STATE_RECOVERING:
            self._advance_recovery(ups, online)

        self._heartbeat()

    def _is_tripped(self, ups):
        charge = ups.get("charge")
        runtime = ups.get("runtime")
        return (charge is not None and charge <= self.cfg["stop_charge_percent"]) or \
               (runtime is not None and runtime <= self.cfg["stop_runtime_seconds"])

    def _evaluate_trigger(self, ups, online):
        cfg = self.cfg
        self.would_trigger = 0
        if online or self.ob_since is None:
            return
        ob_for = self.now - self.ob_since
        if ob_for < cfg["ob_sustain_seconds"]:
            return
        if not self._is_tripped(ups):
            return
        charge = ups.get("charge")
        runtime = ups.get("runtime")
        reason = "on battery %.0fs, charge=%s%% runtime=%ss" % (ob_for, charge, runtime)
        if cfg["dry_run"]:
            self.would_trigger = 1
            guests = self.backend.list_running()
            self._throttled_log("DRY RUN: would stop %s guests (%s)"
                                % (len(guests) if guests is not None else "?", reason))
            return
        # Armed mode: this metric is dry-run-only, keep it at 0 so the
        # dry-run alert can never fire from an armed deployment.
        self.would_trigger = 0
        LOG.warning("TRIGGER: %s — stopping guests", reason)
        self._begin_stop(ups, reason)

    # -- stop sequence ----------------------------------------------------
    def _begin_stop(self, ups, reason, only=None):
        cfg = self.cfg
        guests = self.backend.list_running()
        if guests is None:
            LOG.error("cannot enumerate guests; NOT stopping anything this cycle")
            return
        exclude = set(cfg.get("exclude_vmids", []))
        guests = [g for g in guests if g["vmid"] not in exclude]
        if only is not None:
            guests = [g for g in guests if g["vmid"] in only]
            phase1, phase2 = guests, []
        else:
            rx = re.compile(cfg["phase1_name_regex"])
            phase1 = [g for g in guests if rx.search(g["name"])]
            phase2 = [g for g in guests if not rx.search(g["name"])]
        if not guests:
            LOG.warning("trigger fired but no running guests to stop")
            if only is None:
                self._transition(STATE_MONITORING, history=self._hist("trigger-no-guests"))
            return
        tgt = {str(g["vmid"]): {"vmid": g["vmid"], "type": g["type"], "node": g["node"],
                                "name": g["name"], "sid": g["sid"], "stopped": False}
               for g in guests}
        LOG.warning("stopping %d guests (phase1=%d phase2=%d; %s)", len(guests), len(phase1), len(phase2), reason)
        self._transition(STATE_STOPPING, mode=("manual" if only is not None else "auto"),
                         triggered_at=int(self.now), reason=reason, targets=tgt,
                         phase=1, phase1=[g["vmid"] for g in phase1], phase2=[g["vmid"] for g in phase2],
                         issued={}, aborted=False)
        self._issue_phase([g["vmid"] for g in phase1])

    def _issue_phase(self, vmids):
        st = self.state
        running_list = self.backend.list_running()
        if running_list is None:
            self._throttled_log("guest enumeration failed while issuing stops; retrying next cycle")
            return
        guests = {g["vmid"]: g for g in running_list}
        for vmid in vmids:
            g = guests.get(vmid)
            if g is None:
                st["targets"][str(vmid)]["stopped"] = True
                continue
            ok = self.backend.stop(g, self.cfg["graceful_timeout_seconds"])
            st["issued"][str(vmid)] = int(self.now)
            LOG.info("stop requested: %s (%s) ok=%s", g["name"], g.get("sid") or g.get("type"), ok)

    def _advance_stopping(self, ups, online):
        """Drive the stop sequence.

        Correctness rules (learned from the selftest that caught two bugs):
          * 'pending' means ISSUED and not yet stopped. Phase 2 targets are NOT
            pending until they are issued — counting un-issued targets as
            pending deadlocks the sequence (phase 2 waits for itself).
          * The abort check runs BEFORE issuing the next phase: if mains has
            been back for abort_online_seconds, stop issuing (in-flight stops
            complete naturally; nothing is force-stopped) and go to STOPPED,
            letting the normal recovery path restart what was stopped.
        """
        cfg, st = self.cfg, self.state
        running_list = self.backend.list_running()
        if running_list is None:
            # pvesh unavailable — we do NOT know what is stopped. Freezing the
            # sequence beats falsely concluding "all stopped" and clearing
            # targets while guests still drain the battery.
            self._throttled_log("guest enumeration failed during stop sequence; freezing sequence this cycle")
            return
        running = {g["vmid"] for g in running_list}
        for t in st["targets"].values():
            if t["vmid"] not in running:
                t["stopped"] = True

        issued = {int(k) for k in st.get("issued", {})}
        pending = [t for t in st["targets"].values() if t["vmid"] in issued and not t["stopped"]]

        osince = self.online_since
        mains_back = bool(online and osince is not None and
                          (self.now - osince) >= cfg["abort_online_seconds"])

        if mains_back and not st.get("aborted"):
            LOG.warning("mains stable for %.0fs mid-sequence; aborting remaining stops",
                        self.now - osince)
            st["aborted"] = True
            self.persist()

        if st.get("aborted"):
            # Do not issue further phases, do not force-stop. Wait out whatever
            # is in flight, then hand over to the recovery path.
            if not pending:
                self._transition(STATE_STOPPED, stopped_at=int(self.now))
                LOG.warning("sequence aborted; %d of %d guests stopped",
                            sum(1 for t in st["targets"].values() if t["stopped"]), len(st["targets"]))
            return

        if pending:
            # per-guest deadline -> force stop
            for t in pending:
                issued_at = st["issued"].get(str(t["vmid"]))
                if issued_at and (self.now - issued_at) > (cfg["graceful_timeout_seconds"] + cfg["hard_stop_grace_seconds"]):
                    LOG.warning("graceful stop timed out for %s (vmid %d); forcing hard stop", t["name"], t["vmid"])
                    self.backend.force_stop(t)
                    st["issued"][str(t["vmid"])] = int(self.now)
            # global deadline -> force everything still pending
            if (self.now - st["triggered_at"]) > cfg["sequence_deadline_seconds"]:
                for t in pending:
                    LOG.warning("sequence deadline exceeded; forcing hard stop for %s", t["name"])
                    self.backend.force_stop(t)
                    st["issued"][str(t["vmid"])] = int(self.now)
            return

        # All issued guests are stopped. Issue the next phase, if any.
        if st.get("phase") == 1 and st.get("phase2"):
            st["phase"] = 2
            self.persist()
            self._issue_phase(st["phase2"])
            return

        self._transition(STATE_STOPPED, stopped_at=int(self.now), issued={})
        LOG.warning("all %d targeted guests stopped", len(st["targets"]))

    # -- recovery ---------------------------------------------------------
    def _stopped_tick(self, ups, online):
        """In STATE_STOPPED: decide whether to begin recovery. Also verifies
        (at most every 60s — each check is a cluster API call) that everything
        we stopped stays stopped; nobody restarts the lab while the battery is
        still low."""
        st = self.state
        now = self.now
        if (now - getattr(self, "_last_stopped_check", 0)) >= 60:
            self._last_stopped_check = now
            running_list = self.backend.list_running()
            if running_list is not None:
                running = {g["vmid"] for g in running_list}
                for t in st.get("targets", {}).values():
                    if t["vmid"] in running:
                        # Something brought a guest back while we're still in
                        # the low-battery window (HA recovery, manual start,
                        # operator). Log loudly but do not fight it: re-stopping
                        # on every cycle would flap. The operator can re-stop
                        # explicitly with `ups-autoshutdown stop --only N`.
                        LOG.warning("guest %s (vmid %d) is running again while battery-low; leaving it alone",
                                    t["name"], t["vmid"])
        self._maybe_recover(online)

    def _maybe_recover(self, online):
        cfg = self.cfg
        st = self.state
        if st.get("mode") == "manual":
            self._throttled_log("manual stop is in effect; use `ups-autoshutdown recover` to restore")
            return
        if not online or self.online_since is None:
            return
        need = cfg["recovery_ol_seconds"]
        last = st.get("last_recovery_at")
        if last and (self.now - last) < cfg["recovery_recent_window_seconds"]:
            need += cfg["recovery_recent_extra_seconds"]
        if (self.now - self.online_since) >= need:
            self._begin_recovery(reason="mains stable %.0fs" % need)

    def _begin_recovery(self, reason):
        LOG.warning("recovery starting: %s", reason)
        self._transition(STATE_RECOVERING, recovery_reason=reason)

    def _advance_recovery(self, ups=None, online=True):
        """Issue starts for every target not yet running; complete when all are
        running. Pauses while the UPS is unreadable or back on battery — we
        never restart the lab unless mains is verifiably stable."""
        st = self.state
        if ups is None:
            self._throttled_log("recovery paused: UPS unreadable")
            return
        if not online:
            LOG.warning("recovery paused: UPS on battery again")
            return
        targets = st.get("targets", {})
        running_list = self.backend.list_running()
        if running_list is None:
            self._throttled_log("guest enumeration failed during recovery; retrying next cycle")
            return
        running = {g["vmid"] for g in running_list}
        attempts = getattr(self, "_start_attempts", None)
        if attempts is None:
            attempts = self._start_attempts = {}
        for t in targets.values():
            if t["vmid"] in running:
                continue
            last_try = attempts.get(t["vmid"], 0)
            if (self.now - last_try) < 30:
                continue  # don't spam starts for a guest that is still booting
            attempts[t["vmid"]] = self.now
            ok = self.backend.start(t)
            LOG.info("start requested: %s ok=%s", t["name"], ok)
        remaining = [t for t in targets.values() if t["vmid"] not in running]
        if not remaining:
            self.state.setdefault("history", []).append(self._hist("recovered", count=len(targets)))
            self._transition(STATE_MONITORING, targets={}, mode=None, last_recovery_at=int(self.now),
                             phase=None, phase1=[], phase2=[], issued={}, reason=None, aborted=False)

    # -- misc -------------------------------------------------------------
    def _hist(self, what, **kw):
        h = {"at": int(self.now), "what": what}
        h.update(kw)
        return h

    def _throttled_log(self, msg):
        if (self.now - getattr(self, "_last_warn", 0)) > 60:
            LOG.warning(msg)
            self._last_warn = self.now

    def _heartbeat(self):
        if (self.now - self.last_heartbeat) >= self.cfg["heartbeat_log_seconds"]:
            st = self.state
            LOG.info("heartbeat: state=%s mode=%s ob=%ss targets=%d", st.get("state"), st.get("mode"),
                     st.get("ob_seconds", 0), len(st.get("targets", {})))
            self.last_heartbeat = self.now


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

def write_metrics(cfg, state, guests_running, would_trigger, ob_seconds):
    auto = state.get("mode") == "auto" and state.get("state") in (STATE_STOPPING, STATE_STOPPED, STATE_RECOVERING)
    lab_stopped = 1 if (state.get("state") in (STATE_STOPPING, STATE_STOPPED) and state.get("mode") == "auto") else 0
    triggered = 1 if auto or (state.get("state") == STATE_RECOVERING and state.get("mode") == "auto") else 0
    lines = [
        "# HELP ups_autoshutdown_lab_stopped 1 when guests were auto-stopped due to low battery.",
        "# TYPE ups_autoshutdown_lab_stopped gauge",
        "# HELP ups_autoshutdown_triggered 1 from trigger until recovery completes (auto mode).",
        "# TYPE ups_autoshutdown_triggered gauge",
        "# HELP ups_autoshutdown_would_trigger 1 when trigger conditions are met but dry-run is active.",
        "# TYPE ups_autoshutdown_would_trigger gauge",
        "# HELP ups_autoshutdown_guests_running Running guests (LXCs+VMs) on the cluster.",
        "# TYPE ups_autoshutdown_guests_running gauge",
        "# HELP ups_autoshutdown_ob_seconds Seconds the UPS has been continuously on battery (0 = on line).",
        "# TYPE ups_autoshutdown_ob_seconds gauge",
        "# HELP ups_autoshutdown_state_info Current state machine state (value is always 1).",
        "# TYPE ups_autoshutdown_state_info gauge",
        "# HELP ups_autoshutdown_last_change_timestamp Last state transition (epoch seconds).",
        "# TYPE ups_autoshutdown_last_change_timestamp gauge",
        "ups_autoshutdown_lab_stopped %d" % lab_stopped,
        "ups_autoshutdown_triggered %d" % triggered,
        "ups_autoshutdown_would_trigger %d" % (1 if would_trigger else 0),
        "ups_autoshutdown_guests_running %d" % (guests_running if guests_running is not None else -1),
        "ups_autoshutdown_ob_seconds %d" % ob_seconds,
        'ups_autoshutdown_state_info{state="%s",mode="%s"} 1' % (
            state.get("state", "unknown"), state.get("mode") or "none"),
        "ups_autoshutdown_last_change_timestamp %d" % state.get("last_change", 0),
    ]
    try:
        atomic_write(cfg["metrics_file"], "\n".join(lines) + "\n")
    except OSError as exc:
        LOG.error("metrics write failed: %s", exc)


# --------------------------------------------------------------------------
# daemon
# --------------------------------------------------------------------------

def load_state(cfg):
    path = os.path.join(cfg["state_dir"], "state.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    st.setdefault("state", STATE_MONITORING)
    st.setdefault("targets", {})
    st.setdefault("issued", {})
    st.setdefault("history", [])
    st.setdefault("phase1", [])
    st.setdefault("phase2", [])
    return st


def daemon(config_path):
    cfg = load_config(config_path)
    os.makedirs(cfg["state_dir"], exist_ok=True)
    lock_path = os.path.join(cfg["state_dir"], "daemon.lock")
    lock = open(lock_path, "w", encoding="utf-8")
    LOG.info("ups-autoshutdown daemon starting (dry_run=%s)", cfg["dry_run"])
    engine = None
    while True:
        cfg = load_config(config_path)
        state = load_state(cfg)
        if engine is None:
            engine = Engine(cfg, RealBackend(), state)
        else:
            engine.cfg = cfg
            engine.state = state
            engine.now = time.time()
        # Per-cycle lock: the daemon holds it only while working, so operator
        # commands (`stop`/`recover`) can take it between cycles instead of
        # deadlocking against a lock held forever.
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            LOG.info("operator command in progress; skipping this cycle")
            time.sleep(cfg["poll_seconds"])
            continue
        try:
            ups = read_ups(cfg["ups_name"])
            try:
                engine.cycle(ups)
            except Exception as exc:  # noqa: BLE001 — a crash here must never kill the daemon
                LOG.exception("cycle failed: %s", exc)
            # The guests_running metric does NOT need per-cycle freshness — it
            # is a coarse context gauge, not a control signal. Spawning pvesh
            # every poll (measured ~0.9s CPU each) just to count guests was
            # burning ~18% of a core continuously. Refresh it on a slow cadence
            # instead; the state machine above already enumerates guests
            # whenever it actually needs to act.
            _refresh_guests_running(engine, state)
            write_metrics(cfg, state, state.get("guests_running"),
                          engine.would_trigger, state.get("ob_seconds", 0))
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
        time.sleep(cfg["poll_seconds"])


def _refresh_guests_running(engine, state):
    """Update state['guests_running'] at most every
    ups_autoshutdown_guests_metric_seconds (default 60)."""
    cfg = engine.cfg
    now = engine.now
    last = getattr(engine, "_guests_metric_at", 0)
    if (now - last) < cfg.get("guests_metric_seconds", 60):
        return
    engine._guests_metric_at = now
    running = engine.backend.list_running()
    if running is not None:
        state["guests_running"] = len(running)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def ups_from_status_text(text):
    """Normalize raw `upsc` output (or a fake) into {status, charge, runtime}."""
    vals = parse_ups_output(text or "")
    status = vals.get("ups.status", "")
    if not status:
        return None

    def as_float(key):
        try:
            return float(vals[key])
        except (KeyError, ValueError):
            return None

    return {"status": status, "charge": as_float("battery.charge"), "runtime": as_float("battery.runtime")}


def cmd_status(config_path, test_ups=None):
    cfg = load_config(config_path)
    state = load_state(cfg)
    if test_ups:
        ups = ups_from_status_text(test_ups)
    else:
        ups = read_ups(cfg["ups_name"])
    if ups is None:
        print("UPS: UNREADABLE")
        ups = {"status": "", "charge": None, "runtime": None}
    else:
        print("UPS: status=%s charge=%s%% runtime=%ss" % (ups["status"], ups.get("charge"), ups.get("runtime")))
    print("state=%s mode=%s dry_run=%s" % (state.get("state"), state.get("mode"), cfg["dry_run"]))
    print("targets=%d history=%d" % (len(state.get("targets", {})), len(state.get("history", []))))
    if state.get("targets"):
        for t in state["targets"].values():
            print("  - %(name)s vmid=%(vmid)s %(type)s@%(node)s sid=%(sid)s stopped=%(stopped)s" % t)
    if ups["status"]:
        ob = is_on_battery(ups)
        charge = ups.get("charge")
        runtime = ups.get("runtime")
        tripped = (charge is not None and charge <= cfg["stop_charge_percent"]) or \
                  (runtime is not None and runtime <= cfg["stop_runtime_seconds"])
        print("on_battery=%s would_trip_now=%s (needs OB>=%ss and charge<=%s%% or runtime<=%ss)" %
              (ob, bool(ob and tripped), cfg["ob_sustain_seconds"], cfg["stop_charge_percent"],
               cfg["stop_runtime_seconds"]))


def _with_lock(cfg, fn):
    """Blocking lock shared with the daemon's per-cycle lock — operator
    commands run atomically with respect to the daemon's cycles."""
    os.makedirs(cfg["state_dir"], exist_ok=True)
    lock = open(os.path.join(cfg["state_dir"], "daemon.lock"), "w", encoding="utf-8")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        return fn()
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)


def cmd_stop(config_path, only):
    cfg = load_config(config_path)
    state = load_state(cfg)
    engine = Engine(cfg, RealBackend(), state)
    engine.now = time.time()
    ups = read_ups(cfg["ups_name"]) or {"status": "", "charge": None, "runtime": None}
    only_set = {int(v) for v in only} if only else None

    def run_sequence():
        engine._begin_stop(ups, "manual stop %s" % sorted(only_set or []), only=only_set)
        # Drive to completion while HOLDING the lock, so the daemon cannot
        # interleave a cycle against this same sequence (double-issue risk).
        deadline = time.time() + cfg["sequence_deadline_seconds"] + 60
        online = False
        while state.get("state") == STATE_STOPPING and time.time() < deadline:
            time.sleep(cfg["poll_seconds"])
            engine.now = time.time()
            engine._advance_stopping(None, online)
        engine.persist()

    _with_lock(cfg, run_sequence)
    print("state=%s targets=%d" % (state.get("state"), len(state.get("targets", {}))))


def cmd_recover(config_path, only):
    cfg = load_config(config_path)
    state = load_state(cfg)
    if not state.get("targets"):
        print("nothing to recover (no targets in state)")
        return
    if only:
        only_set = {int(v) for v in only}
        state["targets"] = {k: t for k, t in state["targets"].items() if t["vmid"] in only_set}
    engine = Engine(cfg, RealBackend(), state)
    engine.now = time.time()

    def run_recovery():
        engine._transition(STATE_RECOVERING, recovery_reason="manual recover")
        deadline = time.time() + 600
        while True:
            engine.now = time.time()
            engine._advance_recovery({"status": "OL", "charge": None, "runtime": None}, online=True)
            if state.get("state") == STATE_MONITORING or time.time() > deadline:
                break
            time.sleep(cfg["poll_seconds"])
        engine.persist()

    _with_lock(cfg, run_recovery)
    print("state=%s" % state.get("state"))


def cmd_flag(config_path, disable):
    cfg = load_config(config_path)
    os.makedirs(cfg["state_dir"], exist_ok=True)
    path = os.path.join(cfg["state_dir"], "disabled")
    if disable:
        atomic_write(path, "disabled by operator\n")
        print("disabled flag set: %s" % path)
    else:
        try:
            os.unlink(path)
            print("disabled flag removed")
        except FileNotFoundError:
            print("already enabled")


# --------------------------------------------------------------------------
# selftest — scenario coverage with FakeBackend (no cluster needed)
# --------------------------------------------------------------------------

def selftest():
    failures = []

    def scenario(name, fn):
        try:
            fn()
            print("[ok] %s" % name)
        except AssertionError as exc:
            failures.append(name)
            print("[FAIL] %s: %s" % (name, exc))

    base_cfg = dict(DEFAULT_CONFIG)
    base_cfg["state_dir"] = tempfile.mkdtemp(prefix="ups-autoshutdown-test-")
    base_cfg["metrics_file"] = os.path.join(base_cfg["state_dir"], "m.prom")
    base_cfg["dry_run"] = False
    base_cfg["poll_seconds"] = 1

    def guests():
        return [
            {"vmid": 301, "type": "lxc", "node": "pve01", "name": "tc-ubuntu22", "sid": None},
            {"vmid": 116, "type": "lxc", "node": "pve02", "name": "media-ingest-01", "sid": None},
            {"vmid": 105, "type": "lxc", "node": "pve01", "name": "ntp-01", "sid": "ct:105"},
        ]

    def fresh(guests_list=None, stop_ticks=1, **cfg_over):
        cfg = dict(base_cfg)
        cfg.update(cfg_over)
        be = FakeBackend(guests_list or guests(), stop_ticks=stop_ticks)
        st = {"state": STATE_MONITORING, "targets": {}, "issued": {}, "history": []}
        eng = Engine(cfg, be, st)
        return eng, be, st

    def advance(eng, be, ups, seconds, step=1):
        t = eng.now
        end = t + seconds
        while t < end:
            be.tick()
            t += step
            eng.now = t
            eng.cycle(ups)

    ob_low = {"status": "OB", "charge": 20.0, "runtime": 400.0}
    ob_ok = {"status": "OB", "charge": 60.0, "runtime": 2400.0}
    ol = {"status": "OL", "charge": 60.0, "runtime": 2400.0}

    def s1():
        eng, be, st = fresh()
        advance(eng, be, ob_low, 5)
        assert st["state"] == STATE_MONITORING, st["state"]
        assert not be.calls, be.calls

    def s2():
        eng, be, st = fresh()
        advance(eng, be, ob_ok, 300)
        assert st["state"] == STATE_MONITORING
        assert not be.calls

    def s3():
        eng, be, st = fresh(stop_ticks=1)
        advance(eng, be, ob_low, 120)
        assert st["state"] in (STATE_STOPPED, STATE_RECOVERING), st["state"]
        assert be.running == set(), "all should be stopped: %s" % be.running
        advance(eng, be, ol, 600)
        assert st["state"] == STATE_MONITORING, st["state"]
        assert be.running == {301, 116, 105}, be.running
        assert [c for c in be.calls if c[0] == "start"], be.calls

    def s4():
        eng, be, st = fresh()
        advance(eng, be, {"status": "OB", "charge": 90.0, "runtime": 280.0}, 120)
        assert st["state"] != STATE_MONITORING

    def s5():
        # abort: mains returns during phase1 -> phase2 must not be issued
        # stop_ticks=45 keeps the phase-1 guest in flight long enough for the
        # abort window (30s of stable mains) to elapse before phase1 finishes.
        eng, be, st = fresh(guests_list=[
            {"vmid": 301, "type": "lxc", "node": "pve01", "name": "tc-ubuntu22", "sid": None},
            {"vmid": 116, "type": "lxc", "node": "pve02", "name": "media-ingest-01", "sid": None},
        ], stop_ticks=45)
        advance(eng, be, ob_low, 61 + 2)
        assert st["state"] == STATE_STOPPING, st["state"]
        advance(eng, be, ol, 90)
        assert st.get("aborted"), "should abort remaining stops when mains returns: %s" % st
        assert 116 in be.running, "phase2 guest must not be stopped: %s" % be.running
        assert ("stop", 116, 90) not in be.calls, "phase2 must not be issued: %s" % be.calls

    def s6():
        eng, be, st = fresh(dry_run=True)
        advance(eng, be, ob_low, 120)
        assert st["state"] == STATE_MONITORING, st["state"]
        assert not be.calls, be.calls
        assert eng.would_trigger == 1

    def s7():
        eng, be, st = fresh()
        os.makedirs(eng.cfg["state_dir"], exist_ok=True)
        atomic_write(os.path.join(eng.cfg["state_dir"], "disabled"), "x\n")
        advance(eng, be, ob_low, 120)
        assert st["state"] == STATE_DISABLED, st["state"]
        assert not be.calls
        os.unlink(os.path.join(eng.cfg["state_dir"], "disabled"))

    def s8():
        # stubborn guest -> forced hard stop after deadline
        eng, be, st = fresh(stop_ticks=1)
        be.stubborn = {302}
        eng2, be2, st2 = fresh()
        be2.stubborn = {301}
        advance(eng2, be2, ob_low, 60 + 120 + 40 + 200)
        forced = [c for c in be2.calls if c[0] == "force_stop"]
        assert forced, "stubborn guest should be force-stopped: %s" % be2.calls

    def s9():
        # Regression guard: read_ups must call `upsc <name>` with NO variable
        # arguments. Passing variable names makes upsc print bare values and
        # the daemon silently reads "UNREADABLE" (real bug, first deploy).
        captured = {}
        g = globals()

        def fake_run(args, timeout=30):
            captured["args"] = args
            full = ("battery.charge: 55\nbattery.runtime: 1800\nups.status: OL\n")
            return 0, full, ""

        orig = g["run_cmd"]
        g["run_cmd"] = fake_run
        try:
            got = read_ups("gx1500u")
        finally:
            g["run_cmd"] = orig
        assert captured["args"] == ["upsc", "gx1500u"], "upsc must be called with no var args: %s" % captured["args"]
        assert got is not None and got["status"] == "OL", got
        assert got["charge"] == 55.0 and got["runtime"] == 1800.0, got

    scenario("short sag does not trigger", s1)
    scenario("high charge + long runtime does not trigger", s2)
    scenario("full stop then auto-recovery after stable mains", s3)
    scenario("low runtime triggers even at high charge", s4)
    scenario("mains return during phase1 aborts phase2", s5)
    scenario("dry run announces but never acts", s6)
    scenario("disabled flag blocks everything", s7)
    scenario("stubborn guest gets force-stopped", s8)
    scenario("upsc is called without variable args (UNREADABLE regression guard)", s9)

    if failures:
        print("\n%d FAILURES: %s" % (len(failures), failures))
        return 1
    print("\nall scenarios passed")
    return 0


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="UPS-driven guest autoshutdown for the lab corner")
    ap.add_argument("--config", default="/etc/ups-autoshutdown/config.json")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("run", help="run the daemon")
    p_status = sub.add_parser("status", help="show state and live evaluation")
    p_status.add_argument("--test-ups-status", default=None,
                          help="fake `upsc` output for testing (e.g. 'ups.status: OB')")
    p_stop = sub.add_parser("stop", help="manual controlled stop of specific guests")
    p_stop.add_argument("--only", required=True, help="comma-separated vmids")
    p_rec = sub.add_parser("recover", help="restart tracked guests")
    p_rec.add_argument("--only", default=None, help="comma-separated vmids (subset)")
    sub.add_parser("disable", help="set the operator disabled flag")
    sub.add_parser("enable", help="clear the operator disabled flag")
    sub.add_parser("selftest", help="run scenario tests")

    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "run":
        daemon(args.config)
    elif args.cmd == "status":
        cmd_status(args.config, args.test_ups_status)
    elif args.cmd == "stop":
        cmd_stop(args.config, [v for v in args.only.split(",") if v])
    elif args.cmd == "recover":
        cmd_recover(args.config, [v for v in args.only.split(",") if v] if args.only else None)
    elif args.cmd == "disable":
        cmd_flag(args.config, True)
    elif args.cmd == "enable":
        cmd_flag(args.config, False)
    elif args.cmd == "selftest":
        sys.exit(selftest())
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
