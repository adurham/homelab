#!/usr/bin/env python3
"""pet-accident-detector v4

Event-driven pet-accident detector for the Frigate cameras.

Flow:
  Frigate MQTT event (a cat LEAVES a monitored camera)
    -> optional local pre-gate (floor change vs clean baseline)
    -> VLM verdict on a fresh frame (gemma4 by default)
    -> multi-frame consensus
    -> annotated frame uploaded to HA + rich iOS push

The VLM is reached over the Ollama HTTP API.  Point ``analyzer.base_url`` at
https://ollama.com for the cloud model (the same gemma4 the Hermes vision tool
uses) or at a local ollama for a fully local detector.

Run ``detector.py --check foyer`` for a one-shot verdict, or let the systemd
unit run the daemon.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import random
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from logging.handlers import RotatingFileHandler
from pathlib import Path

import paho.mqtt.client as mqtt
import yaml
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localgate import GateResult, score_change  # noqa: E402

LOG = logging.getLogger("petdetector")

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.yaml"

PROMPT = (
    "Inspect the floor in this image for a genuine pet accident (urine, feces, or vomit). "
    "IGNORE all of the following normal things, which are NOT accidents: water bowls and "
    "food bowls (round dishes, sometimes shiny), litter boxes, scattered litter, toys, pet "
    "beds, mats, rugs, cat trees, furniture, and pets. "
    "CRITICAL: bright sunlight, window light pools, glare, sheen, and reflections on "
    "tile/hardwood/laminate floors are NOT puddles - hard floors are shiny and reflect "
    "light normally. Do NOT report a puddle just because the floor looks bright, shiny, or "
    "reflective. "
    "A dark or irregular shape is almost always a SHADOW (from a cat, furniture, or the "
    "camera) or a darker floor tile/seam, not liquid. Demand positive evidence of WETNESS: "
    "a glossy sheen with a specular highlight, a meniscus or sharp edge, or a spreading "
    "stain. For solid waste, demand a distinct three-dimensional shape with its own "
    "highlight and shadow, not a flat dark patch. "
    "Answer exactly in this format and nothing else: "
    "ACCIDENT: yes|no | WHY: <one short sentence> | CONFIDENCE: high|medium|low"
)

BBOX_PROMPT = (
    "There is a suspected pet accident (urine, feces, or vomit) on the floor in this image. "
    "Give the tightest bounding box around the single most suspicious area. "
    "Use normalized coordinates from 0 to 1000 in the order [x1, y1, x2, y2], where "
    "(x1,y1) is the TOP-LEFT corner and (x2,y2) is the BOTTOM-RIGHT corner. "
    "Answer exactly: BBOX: [x1, y1, x2, y2], or BBOX: none if you cannot localize it."
)

VERDICT_RE = re.compile(r"ACCIDENT:\s*(yes|no)", re.IGNORECASE)
WHY_RE = re.compile(r"WHY:\s*(.+?)(?:\s*\|\s*CONFIDENCE:|$)", re.IGNORECASE | re.DOTALL)
CONF_RE = re.compile(r"CONFIDENCE:\s*(high|medium|low)", re.IGNORECASE)
BBOX_RE = re.compile(r"BBOX:\s*\[([^\]]+)\]", re.IGNORECASE)


# --------------------------------------------------------------------------
# config / env / logging
# --------------------------------------------------------------------------


def load_env_file(path: Path, override: bool = False) -> None:
    try:
        text = path.read_text()
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = val


def expand(p: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(p))))


def setup_logging(log_file: Path, verbose: bool = False) -> None:
    LOG.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    LOG.addHandler(sh)
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=2)
        fh.setFormatter(fmt)
        LOG.addHandler(fh)
    except OSError as exc:
        LOG.warning("file logging disabled: %s", exc)


# --------------------------------------------------------------------------
# data types
# --------------------------------------------------------------------------


@dataclass
class Verdict:
    accident: bool = False
    confidence: str = "low"
    reason: str = ""
    raw: str = ""
    ok: bool = False


@dataclass
class CheckResult:
    camera: str
    verdict: Verdict
    frame: bytes | None
    gate: GateResult | None = None
    frames: list[bytes] = field(default_factory=list)
    votes: list[Verdict] = field(default_factory=list)
    alert: bool = False


@dataclass
class CameraState:
    last_cat_seen: float = field(default_factory=time.time)
    active_events: set[str] = field(default_factory=set)
    last_alert: float = 0.0
    last_verdict: str = ""
    last_check: float = 0.0
    last_error: str = ""
    check_lock: threading.Lock = field(default_factory=threading.Lock)
    pending_timer: threading.Timer | None = None


# --------------------------------------------------------------------------
# detector
# --------------------------------------------------------------------------


class Detector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mqtt_cfg = cfg["mqtt"]
        self.frigate = cfg["frigate"]["base_url"].rstrip("/")
        self.frame_height = int(cfg["frigate"].get("frame_height", 1080))
        self.frame_timeout = float(cfg["frigate"].get("frame_timeout", 15))
        self.analyzer_cfg = cfg["analyzer"]
        self.timing = cfg["timing"]
        self.gate_cfg = cfg.get("gate", {})
        self.notify_cfg = cfg.get("notify", {})
        self.cameras = cfg["cameras"]
        self.trigger_labels = set(cfg.get("triggers", {}).get("labels", ["cat"]))

        paths = cfg.get("paths", {})
        self.data_dir = expand(paths.get("data_dir", "~/.local/share/pet-accident-detector"))
        self.evidence_dir = self.data_dir / "evidence"
        self.baseline_dir = self.data_dir / "baselines"
        for d in (self.data_dir, self.evidence_dir, self.baseline_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "state.json"
        self.state_lock = threading.Lock()
        self.evidence_keep_days = int(paths.get("evidence_keep_days", 14))
        self.negative_sample_rate = float(paths.get("negative_sample_rate", 0.10))

        self.states = {cam: CameraState() for cam in self.cameras}
        self.vlm_lock = threading.Lock()
        self.client: mqtt.Client | None = None
        self.stop = threading.Event()
        self._load_state()

    # -- state ------------------------------------------------------------
    def _load_state(self) -> None:
        try:
            data = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return
        for cam, st in self.states.items():
            d = data.get(cam, {})
            st.last_alert = float(d.get("last_alert", 0))
            st.last_verdict = str(d.get("last_verdict", ""))
            st.last_check = float(d.get("last_check", 0))

    def _save_state(self) -> None:
        with self.state_lock:
            data = {
                cam: {
                    "last_alert": st.last_alert,
                    "last_verdict": st.last_verdict,
                    "last_check": st.last_check,
                    "last_error": st.last_error,
                }
                for cam, st in self.states.items()
            }
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self.state_file)

    # -- frames -----------------------------------------------------------
    def fetch_frame(self, cam: str) -> bytes:
        url = f"{self.frigate}/api/{cam}/latest.jpg?h={self.frame_height}"
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "pet-detector/4"})
                with urllib.request.urlopen(req, timeout=self.frame_timeout) as r:
                    data = r.read()
                if len(data) < 5000:
                    raise ValueError(f"frame too small ({len(data)} bytes)")
                img = Image.open(BytesIO(data))
                gray = img.convert("L")
                mean = sum(i * n for i, n in enumerate(gray.histogram())) / (gray.width * gray.height)
                if mean < 6:
                    raise ValueError(f"frame is black (mean luma {mean:.1f}) - camera offline?")
                return data
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < 2:
                    time.sleep(3)
        raise RuntimeError(f"{cam}: no usable frame from Frigate: {last_exc}")

    # -- VLM --------------------------------------------------------------
    def _vlm_request(self, image: bytes, prompt: str, max_tokens: int, cfg: dict | None = None) -> str:
        cfg = cfg or self.analyzer_cfg
        backend = cfg.get("backend", "ollama")
        base = cfg["base_url"].rstrip("/")
        model = cfg["model"]
        timeout = float(cfg.get("timeout", 90))
        b64 = base64.b64encode(image).decode("ascii")

        if backend == "ollama":
            body = {
                "model": model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt, "images": [b64]}],
                "options": {"temperature": 0, "num_predict": max_tokens},
            }
            url = f"{base}/api/chat"
            headers = {"Content-Type": "application/json"}
            key_env = cfg.get("api_key_env")
            if key_env and os.environ.get(key_env):
                headers["Authorization"] = f"Bearer {os.environ[key_env]}"
        elif backend in ("openai", "openai-compatible"):
            body = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    }
                ],
            }
            url = f"{base}/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            key_env = cfg.get("api_key_env")
            if key_env and os.environ.get(key_env):
                headers["Authorization"] = f"Bearer {os.environ[key_env]}"
        else:
            raise ValueError(f"unknown analyzer backend: {backend}")

        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
        if backend == "ollama":
            return (payload.get("message") or {}).get("content", "") or ""
        return payload["choices"][0]["message"]["content"] or ""

    def _ask(self, image: bytes, prompt: str, max_tokens: int) -> str:
        """Primary analyzer, then the optional fallback (e.g. cloud after a
        local VLM on a machine that went to sleep)."""
        try:
            with self.vlm_lock:
                return self._vlm_request(image, prompt, max_tokens)
        except Exception as exc:  # noqa: BLE001
            fallback = self.analyzer_cfg.get("fallback")
            if not fallback:
                raise
            LOG.warning("primary VLM failed (%s); trying fallback", exc)
            with self.vlm_lock:
                return self._vlm_request(image, prompt, max_tokens, cfg=fallback)

    def analyze(self, image: bytes, prompt: str = PROMPT) -> Verdict:
        try:
            text = self._ask(image, prompt, int(self.analyzer_cfg.get("max_tokens", 160)))
        except Exception as exc:  # noqa: BLE001
            LOG.warning("VLM error: %s", exc)
            return Verdict(ok=False, reason=f"VLM error: {exc}", raw="")
        m = VERDICT_RE.search(text)
        if not m:
            LOG.warning("unparseable VLM answer: %r", text[:200])
            return Verdict(ok=False, reason="unparseable answer", raw=text)
        why = WHY_RE.search(text)
        conf = CONF_RE.search(text)
        return Verdict(
            accident=m.group(1).lower() == "yes",
            confidence=(conf.group(1).lower() if conf else "low"),
            reason=(why.group(1).strip() if why else ""),
            raw=text.strip(),
            ok=True,
        )

    def get_bbox(self, image: bytes) -> tuple[float, float, float, float] | None:
        try:
            text = self._ask(image, BBOX_PROMPT, 80)
        except Exception as exc:  # noqa: BLE001
            LOG.info("bbox pass failed: %s", exc)
            return None
        m = BBOX_RE.search(text)
        if not m:
            return None
        try:
            nums = [float(x) for x in re.split(r"[,\s]+", m.group(1).strip()) if x]
        except ValueError:
            return None
        if len(nums) != 4:
            return None
        x1, y1, x2, y2 = nums
        # gemma4 answers in 0..1000 normalized coordinates; accept 0..1 too.
        if any(v > 1 for v in nums):
            if not all(0 <= v <= 1000 for v in nums):
                return None
            x1, y1, x2, y2 = (v / 1000.0 for v in nums)
        if not all(0 <= v <= 1 for v in (x1, y1, x2, y2)):
            return None
        if x2 <= x1 or y2 <= y1 or (x2 - x1) * (y2 - y1) < 0.0005:
            return None
        return x1, y1, x2, y2

    # -- local gate -------------------------------------------------------
    def baseline_path(self, cam: str) -> Path:
        return self.baseline_dir / f"{cam}.jpg"

    def gate_score(self, cam: str, current: bytes) -> GateResult | None:
        if not self.gate_cfg.get("enabled"):
            return None
        bp = self.baseline_path(cam)
        if not bp.exists():
            return None
        try:
            base = bp.read_bytes()
        except OSError:
            return None
        return score_change(
            base,
            current,
            ignore_top=float(self.gate_cfg.get("ignore_top", 0.12)),
            de_threshold=float(self.gate_cfg.get("de_threshold", 12)),
            chroma_threshold=float(self.gate_cfg.get("chroma_threshold", 8)),
        )

    def refresh_baselines(self) -> None:
        if not self.gate_cfg.get("enabled"):
            return
        quiet = float(self.gate_cfg.get("baseline_quiet", 300))
        now = time.time()
        for cam, st in self.states.items():
            if st.check_lock.locked():
                continue
            if st.last_verdict == "accident":
                continue
            if self.cameras[cam].get("mode") == "periodic":
                # The cat room is never empty, so the "quiet room" rule would
                # never let a baseline exist. Refresh only after a clean check
                # (so an accident cannot be baked into the baseline).
                if st.last_verdict not in ("clean", ""):
                    continue
            elif st.active_events or (now - st.last_cat_seen) < quiet:
                continue
            try:
                frame = self.fetch_frame(cam)
            except Exception as exc:  # noqa: BLE001
                LOG.debug("baseline skip %s: %s", cam, exc)
                continue
            tmp = self.baseline_path(cam).with_suffix(".tmp")
            tmp.write_bytes(frame)
            tmp.replace(self.baseline_path(cam))
            LOG.debug("baseline refreshed for %s", cam)

    # -- analysis / alert -------------------------------------------------
    def check_camera(self, cam: str, reason: str, settle: float = 0, force: bool = False) -> CheckResult | None:
        st = self.states[cam]
        if not st.check_lock.acquire(blocking=False):
            LOG.info("[%s] check already running (%s) - skip", cam, reason)
            return None
        try:
            if settle > 0:
                time.sleep(settle)
            st.last_check = time.time()
            LOG.info("[%s] checking (%s)", cam, reason)
            try:
                frame = self.fetch_frame(cam)
            except Exception as exc:  # noqa: BLE001
                st.last_error = str(exc)
                LOG.warning("[%s] %s", cam, exc)
                return CheckResult(cam, Verdict(ok=False, reason=str(exc)), None)

            gate = self.gate_score(cam, frame)
            if gate is not None:
                LOG.info("[%s] gate score=%.5f (dE %.1f) %s", cam, gate.score, gate.mean_delta_e, gate.detail)
            mode = self.gate_cfg.get("mode", "shadow")
            threshold = float(self.gate_cfg.get("threshold", 0.0025))
            if gate is not None and mode == "enforce" and gate.score < threshold:
                LOG.info("[%s] gate: no floor change -> skip VLM", cam)
                st.last_verdict = "clean"
                self._save_evidence(cam, "negative", [frame], [Verdict(ok=True, reason="gate clean")], gate)
                self._save_state()
                return CheckResult(cam, Verdict(ok=True, reason="gate clean"), frame, gate)

            verdict = self.analyze(frame)
            votes = [verdict]
            frames = [frame]
            LOG.info(
                "[%s] verdict: %s (%s) %s",
                cam,
                "ACCIDENT" if verdict.accident else ("error" if not verdict.ok else "clean"),
                verdict.confidence,
                verdict.reason,
            )
            if not verdict.ok:
                st.last_verdict = "error"
                self._save_state()
                return CheckResult(cam, verdict, frame, gate, frames, votes)

            if not verdict.accident:
                st.last_verdict = "clean"
                self._save_evidence(cam, "negative", frames, votes, gate)
                self._save_state()
                return CheckResult(cam, verdict, frame, gate, frames, votes)

            # Candidate: multi-frame consensus.
            n = int(self.timing.get("consensus_frames", 3))
            gap = float(self.timing.get("consensus_gap", 4))
            for _ in range(max(0, n - 1)):
                time.sleep(gap)
                try:
                    f2 = self.fetch_frame(cam)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("[%s] consensus frame failed: %s", cam, exc)
                    continue
                frames.append(f2)
                votes.append(self.analyze(f2))
            yes = sum(1 for v in votes if v.ok and v.accident)
            needed = int(self.timing.get("consensus_needed", n))
            LOG.info("[%s] candidate: %d/%d agreed (%s)", cam, yes, len(votes), verdict.reason)

            if yes < needed:
                st.last_verdict = "rejected"
                self._save_evidence(cam, "rejected", frames, votes, gate)
                self._save_state()
                return CheckResult(cam, verdict, frame, gate, frames, votes, alert=False)

            # Confirmed. Cooldown?
            cooldown = float(self.timing.get("cooldown", 3600))
            if not force and (time.time() - st.last_alert) < cooldown:
                LOG.info("[%s] confirmed but in cooldown - not notifying", cam)
                self._save_evidence(cam, "suppressed", frames, votes, gate)
                self._save_state()
                return CheckResult(cam, verdict, frame, gate, frames, votes, alert=False)

            self._alert(cam, frames[-1], verdict, gate)
            st.last_alert = time.time()
            st.last_verdict = "accident"
            self._save_evidence(cam, "alert", frames, votes, gate)
            self._save_state()
            return CheckResult(cam, verdict, frame, gate, frames, votes, alert=True)
        finally:
            st.check_lock.release()

    def _alert(self, cam: str, frame: bytes, verdict: Verdict, gate: GateResult | None) -> None:
        label = self.cameras[cam].get("label", cam)
        box = self.get_bbox(frame) if self.notify_cfg.get("draw_bbox", True) else None
        annotated = self.annotate(frame, box, "ACCIDENT")
        image_url = None
        if self.notify_cfg.get("ha_ssh_host"):
            try:
                self.upload_to_ha(annotated, cam)
                tmpl = self.notify_cfg.get("image_url_template", "/local/accident_{cam}.jpg")
                image_url = tmpl.format(cam=cam)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("[%s] image upload failed: %s", cam, exc)
        title = f"Pet Accident? - {label}"
        msg = verdict.reason or "A pet accident may be on the floor."
        if verdict.confidence:
            msg = f"{msg} ({verdict.confidence} confidence)"
        try:
            self.notify(title, msg, image_url)
            LOG.info("[%s] ALERT sent img=%s: %s", cam, bool(image_url), verdict.reason)
        except Exception as exc:  # noqa: BLE001
            LOG.error("[%s] notify failed: %s", cam, exc)

    def annotate(self, frame: bytes, box: tuple[float, float, float, float] | None, label: str) -> bytes:
        img = Image.open(BytesIO(frame)).convert("RGB")
        if box:
            w, h = img.size
            x1, y1, x2, y2 = box
            draw = ImageDraw.Draw(img)
            pad = 6
            draw.rectangle(
                [max(0, x1 * w - pad), max(0, y1 * h - pad), min(w, x2 * w + pad), min(h, y2 * h + pad)],
                outline=(255, 0, 0),
                width=max(3, w // 400),
            )
            draw.text((max(0, x1 * w), max(0, y1 * h - 18)), label, fill=(255, 0, 0))
        out = BytesIO()
        img.save(out, "JPEG", quality=88)
        return out.getvalue()

    def upload_to_ha(self, jpg: bytes, cam: str) -> None:
        key = expand(self.notify_cfg["ha_ssh_key"])
        host = self.notify_cfg["ha_ssh_host"]
        port = str(self.notify_cfg.get("ha_ssh_port", 2222))
        www = self.notify_cfg.get("ha_www", "/config/www")
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as fh:
            fh.write(jpg)
            tmp = fh.name
        try:
            cmd = [
                "scp",
                "-q",
                "-P",
                port,
                "-i",
                str(key),
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                tmp,
                f"root@{host}:{www}/accident_{cam}.jpg",
            ]
            subprocess.run(cmd, check=True, timeout=30)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def notify(self, title: str, message: str, image_url: str | None) -> None:
        ha_url = os.environ[self.notify_cfg.get("ha_url_env", "HASS_URL")].rstrip("/")
        token = os.environ[self.notify_cfg.get("ha_token_env", "HASS_TOKEN")]
        data: dict[str, object] = {"push": {"category": "camera"}}
        if image_url:
            data["image"] = image_url
        for svc in self.notify_cfg.get("services", []):
            body = json.dumps({"title": title, "message": message, "data": data}).encode()
            req = urllib.request.Request(
                f"{ha_url}/api/services/notify/{svc}",
                data=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
            LOG.info("notified %s", svc)

    # -- evidence ---------------------------------------------------------
    def _save_evidence(
        self, cam: str, kind: str, frames: list[bytes], votes: list[Verdict], gate: GateResult | None
    ) -> None:
        if kind == "negative" and random.random() > self.negative_sample_rate:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self.evidence_dir / f"{ts}_{cam}_{kind}"
        lines = [f"camera: {cam}", f"kind: {kind}", f"time: {ts}"]
        if gate is not None:
            lines.append(f"gate: score={gate.score} dE={gate.mean_delta_e} bbox={gate.bbox} ({gate.detail})")
        for i, (fr, v) in enumerate(zip(frames, votes, strict=False)):
            try:
                (self.evidence_dir / f"{base.name}_f{i}.jpg").write_bytes(fr)
            except OSError:
                pass
            tag = "trigger" if i == 0 else "vote"
            lines.append(
                f"frame {i} ({tag}): ACCIDENT: {'yes' if v.accident else 'no'} | "
                f"WHY: {v.reason} | CONFIDENCE: {v.confidence} | raw: {v.raw[:300]}"
            )
        try:
            (self.evidence_dir / f"{base.name}.txt").write_text("\n".join(lines) + "\n")
        except OSError:
            pass
        self.prune_evidence()

    def prune_evidence(self) -> None:
        cutoff = time.time() - self.evidence_keep_days * 86400
        for p in self.evidence_dir.iterdir():
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass

    # -- MQTT -------------------------------------------------------------
    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            LOG.info("MQTT connected to %s:%s", self.mqtt_cfg["host"], self.mqtt_cfg["port"])
            client.subscribe(self.mqtt_cfg.get("topic", "frigate/events"))
        else:
            LOG.error("MQTT connect failed: %s", reason_code)

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if not self.stop.is_set():
            LOG.warning("MQTT disconnected (%s); paho will retry", reason_code)

    def on_message(self, client, userdata, msg):
        try:
            event = json.loads(msg.payload)
        except ValueError:
            return
        etype = event.get("type")
        after = event.get("after") or {}
        cam = after.get("camera")
        label = after.get("label")
        eid = after.get("id") or event.get("before", {}).get("id")
        if not cam or cam not in self.states or label not in self.trigger_labels:
            return
        st = self.states[cam]
        now = time.time()
        st.last_cat_seen = now
        if etype == "new":
            if eid:
                st.active_events.add(eid)
            return
        if etype == "end":
            if eid:
                st.active_events.discard(eid)
            if st.active_events:
                LOG.debug("[%s] cat event %s ended, %d still active", cam, eid, len(st.active_events))
                return
            if self.cameras[cam].get("mode") != "periodic":
                self.schedule_check(cam, "cat left")

    def schedule_check(self, cam: str, reason: str) -> None:
        st = self.states[cam]
        settle = float(self.timing.get("settle", 30))
        debounce = float(self.timing.get("debounce", 8))
        if st.pending_timer:
            st.pending_timer.cancel()
        delay = settle + debounce
        LOG.info("[%s] scheduling check in %.0fs (%s)", cam, delay, reason)
        t = threading.Timer(delay, lambda: self.check_camera(cam, reason))
        t.daemon = True
        st.pending_timer = t
        t.start()

    def periodic_loop(self) -> None:
        """Per-camera fixed-interval checks for rooms that are never empty."""
        next_run = {}
        now = time.time()
        for cam, c in self.cameras.items():
            if c.get("mode") == "periodic":
                next_run[cam] = now + 60  # first check a minute after start
        while not self.stop.is_set():
            now = time.time()
            for cam, due in list(next_run.items()):
                if now >= due:
                    interval = float(self.cameras[cam].get("interval", 900))
                    next_run[cam] = now + interval
                    threading.Thread(
                        target=self.check_camera,
                        args=(cam, "periodic check"),
                        daemon=True,
                    ).start()
            self.stop.wait(5)

    def baseline_loop(self) -> None:
        interval = float(self.gate_cfg.get("baseline_interval", 60))
        while not self.stop.is_set():
            try:
                self.refresh_baselines()
            except Exception as exc:  # noqa: BLE001
                LOG.warning("baseline refresh failed: %s", exc)
            self.stop.wait(interval)

    # -- run --------------------------------------------------------------
    def run(self) -> None:
        LOG.info(
            "starting pet-accident-detector; cameras=%s model=%s backend=%s",
            ",".join(self.cameras),
            self.analyzer_cfg.get("model"),
            self.analyzer_cfg.get("backend"),
        )
        threading.Thread(target=self.periodic_loop, daemon=True).start()
        if self.gate_cfg.get("enabled"):
            threading.Thread(target=self.baseline_loop, daemon=True).start()

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"pet-detector-{os.uname().nodename}")
        pwd_env = self.mqtt_cfg.get("password_env", "FRIGATE_MQTT_PASSWORD")
        password = os.environ.get(pwd_env, "")
        if password:
            client.username_pw_set(self.mqtt_cfg.get("user", "frigate"), password)
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        self.client = client
        client.connect_async(self.mqtt_cfg["host"], int(self.mqtt_cfg.get("port", 1883)), 60)

        def _stop(signum, frame):
            LOG.info("signal %s - stopping", signum)
            self.stop.set()
            client.disconnect()

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        client.loop_forever(retry_first_connection=True)
        LOG.info("stopped")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="pet-accident-detector v4")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--check", metavar="CAM", help="run one check and print the verdict (no alert)")
    ap.add_argument("--notify-test", metavar="CAM", help="send a test notification with a live frame")
    ap.add_argument("--gate", metavar="CAM", help="print the local-gate score against the baseline")
    ap.add_argument("--fetch", nargs=2, metavar=("CAM", "OUT"), help="save a frame and exit")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    load_env_file(Path.home() / ".hermes" / ".env")
    load_env_file(Path.home() / ".config" / "pet-accident-detector" / "env", override=True)
    paths = cfg.get("paths", {})
    setup_logging(expand(paths.get("log_file", "~/.local/share/pet-accident-detector/detector.log")), args.verbose)
    det = Detector(cfg)

    if args.fetch:
        cam, out = args.fetch
        data = det.fetch_frame(cam)
        Path(out).write_bytes(data)
        print(f"saved {out} ({len(data)} bytes)")
        return 0

    if args.gate:
        cam = args.gate
        cur = det.fetch_frame(cam)
        g = det.gate_score(cam, cur)
        if g is None:
            print(f"{cam}: no baseline yet (or gate disabled)")
            return 1
        print(json.dumps(g.__dict__, indent=2))
        return 0

    if args.check:
        cam = args.check
        res = det.check_camera(cam, "manual check", force=True)
        if res is None:
            print("check skipped (already running)")
            return 1
        print(
            json.dumps(
                {
                    "camera": cam,
                    "accident": res.verdict.accident,
                    "confidence": res.verdict.confidence,
                    "reason": res.verdict.reason,
                    "ok": res.verdict.ok,
                    "gate": res.gate.__dict__ if res.gate else None,
                    "votes": [
                        {"accident": v.accident, "confidence": v.confidence, "reason": v.reason} for v in res.votes
                    ],
                },
                indent=2,
            )
        )
        return 0

    if args.notify_test:
        cam = args.notify_test
        frame = det.fetch_frame(cam)
        annotated = det.annotate(frame, None, "TEST")
        url = None
        if det.notify_cfg.get("ha_ssh_host"):
            det.upload_to_ha(annotated, cam)
            url = det.notify_cfg.get("image_url_template", "/local/accident_{cam}.jpg").format(cam=cam)
        det.notify("Pet detector test", f"Test notification from {cam}; pipeline is alive.", url)
        print("test notification sent")
        return 0

    det.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
