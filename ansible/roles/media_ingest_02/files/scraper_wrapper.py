#!/usr/bin/env python3
"""
Secondary source gallery collector (scraper edition) — periodic sweep that runs
the upstream scraper for a configured list of models, then walks the staging tree
and PUSHES every downloaded file to the gallery platform via the authenticated
ingest API. Same gallery push path as the primary collector (store_client.py),
just a different upstream source and a pull-based (not push-based) capture model.

Flow per tick (oneshot service, timer-driven):
  1. invoke the scraper (download action, all post types) with --username pointing
     at the configured model list (M02_SCRAPE_USERNAMES env, comma-separated —
     SENSITIVE, comes from the vault). save_location = tmpfs staging,
     dir_format = {model_username}/ (flat per-model). The scraper's own metadata
     dupe-check db means re-runs only download NEW content — same idempotent
     overlap-the-gallery-stem-dedup contract as the primary's reconcile sweep.
     The scraper finds auth.json next to config.json (its get_auth_file() returns
     get_config_path().parent / <main_profile> / authFile), so auth.json lives in
     <state>/main_profile/auth.json.
  2. walk the staging tree. For each file under <model_username>/:
       stem   = <model_username>_<post_id>_<media_id>  (stable, gallery-dedup-able)
       folder = <model_username>                        (flat, one folder per model)
       date   = file mtime (the scraper sets this to the post date)
       push via store_client.push_media(folder, path, stem, date, is_out=False)
  3. delete the staging file after a successful push (tmpfs, so a crash naturally
     drops anything in flight — the next sweep re-downloads it).

Env (from scraper.env, rendered by ansible from vault + defaults):
  M02_STAGING, M02_LOG_FILE, M02_AUTH_FILE, M02_CONFIG_FILE, M02_METADATA_DIR,
  M02_SCRAPE_USERNAMES (vault), M02_SCRAPE_LOOKBACK, plus the gallery auth env
  (AUTHENTIK_TOKEN_URL, COLLECTOR_CLIENT_ID, COLLECTOR_CLIENT_SECRET, GALLERY_BASE)
  consumed by store_client.
"""
import datetime as dt
import logging
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store_client  # noqa: E402

STAGING = Path(os.environ["M02_STAGING"])
LOG_FILE = os.environ.get("M02_LOG_FILE", "/var/log/media-ingest-02/scraper.log")
AUTH_FILE = os.environ["M02_AUTH_FILE"]
CONFIG_FILE = os.environ["M02_CONFIG_FILE"]
# Comma-separated list of upstream models to scrape (SENSITIVE — from the vault
# via env, never hardcoded). Empty = scrape nothing (safe default).
SCRAPE_USERNAMES = os.environ.get("M02_SCRAPE_USERNAMES", "").strip()

STAGING.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("media-ingest-02")


def _check_auth():
    """Verify auth.json exists and is readable before invoking the scraper. The
    scraper would prompt interactively if auth.json is missing, which would hang
    a headless service. Fail fast instead."""
    p = Path(AUTH_FILE)
    if not p.exists() or p.stat().st_size == 0:
        log.error("auth.json missing or empty at %s — run assisted login first", p)
        sys.exit(2)


def _run_scraper():
    """Invoke the scraper for the configured model list, all post types, download
    action. Returns the subprocess CompletedProcess. The scraper's own dupe-check
    db (in M02_METADATA_DIR) means a run only downloads NEW content."""
    if not SCRAPE_USERNAMES:
        log.warning("M02_SCRAPE_USERNAMES empty — nothing to scrape this tick")
        return None
    # Binary name is the upstream package's console-script entry point; pull it
    # from env so the source tree doesn't hardcode the package identity.
    bin_name = os.environ.get("M02_SCRAPER_BIN", "scraper")
    cmd = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", bin_name),
        "--config", CONFIG_FILE,
        "--action", "download",
        "--posts", "all",
        "--username", SCRAPE_USERNAMES,
    ]
    log.info("invoking scraper: %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=90 * 60)
    except subprocess.TimeoutExpired:
        log.error("scraper timed out after 90min")
        return None
    if r.returncode != 0:
        log.error("scraper exited %d: %s", r.returncode, (r.stderr or "")[-2000:])
    else:
        log.info("scraper exit 0. stdout tail: %s", (r.stdout or "")[-500:])
    return r


def _walk_and_push():
    """Walk the staging tree (flat per-model: <model_username>/<file>) and push
    each file to the gallery. Returns (pushed, failed, skipped)."""
    pushed = failed = skipped = 0
    if not STAGING.exists():
        return 0, 0, 0
    for model_dir in sorted(STAGING.iterdir()):
        if not model_dir.is_dir():
            continue
        folder = model_dir.name
        for fpath in sorted(model_dir.iterdir()):
            if not fpath.is_file():
                continue
            raw_stem = f"{folder}_{fpath.stem}"
            stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in raw_stem).strip("-") or "unknown"
            mtime = fpath.stat().st_mtime
            date_iso = dt.datetime.fromtimestamp(mtime).isoformat()
            try:
                store_client.push_media(folder, str(fpath), stem, date_iso, is_out=False)
                pushed += 1
                log.info("PUSHED %s -> %s", stem, folder)
                try:
                    fpath.unlink()
                except OSError:
                    pass
            except Exception as e:  # noqa: BLE001
                failed += 1
                log.error("push failed %s: %s: %s", stem, type(e).__name__, e)
    return pushed, failed, skipped


def main():
    _check_auth()
    try:
        ex = store_client.get_excluded()
        log.info("gallery auth OK; %d excluded stems", len(ex))
    except Exception as e:  # noqa: BLE001
        log.error("gallery auth FAILED at startup: %s", e)
        sys.exit(3)

    r = _run_scraper()
    if r is None or r.returncode != 0:
        log.warning("scraper run incomplete; pushing whatever landed in staging")

    pushed, failed, skipped = _walk_and_push()
    log.info("sweep done: pushed=%d failed=%d skipped=%d", pushed, failed, skipped)


if __name__ == "__main__":
    main()
