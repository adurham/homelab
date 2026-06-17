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
# Optional second pass: auto-discover models matching a filter (e.g. active paid
# subs). Space-separated scraper flags, e.g. "--current-price paid
# --active-subscription --username ALL". Empty = skip the auto-discovery pass
# (safe default — only the explicit SCRAPE_USERNAMES list is scraped). SENSITIVE
# — reveals the operator's subscription behavior, so it comes from the vault.
SCRAPE_FILTER_ARGS = os.environ.get("M02_SCRAPE_FILTER_ARGS", "").strip()

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


def _scraper_base_cmd():
    """Build the base scraper invocation (binary + config + action + posts).
    Returns the list of base args; callers append the model-selection args."""
    bin_name = os.environ.get("M02_SCRAPER_BIN", "scraper")
    return [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", bin_name),
        "--config", CONFIG_FILE,
        "--action", "download",
        "--posts", "all",
    ]


def _run_scraper_pass(label, model_args, timeout_min=90):
    """Invoke the scraper for one pass with the given model-selection args.
    label is a short tag for logging (e.g. 'manual', 'filter'). Returns the
    subprocess CompletedProcess or None on timeout/failure."""
    if not model_args:
        log.info("pass [%s] skipped — no model args", label)
        return None
    cmd = _scraper_base_cmd() + model_args
    log.info("pass [%s] invoking scraper: %s", label, " ".join(cmd))
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout_min * 60)
    except subprocess.TimeoutExpired:
        log.error("pass [%s] scraper timed out after %dmin", label, timeout_min)
        return None
    if r.returncode != 0:
        log.error("pass [%s] scraper exited %d: %s", label, r.returncode, (r.stderr or "")[-2000:])
    else:
        log.info("pass [%s] scraper exit 0. stdout tail: %s", label, (r.stdout or "")[-500:])
    return r


def _run_scraper():
    """Run the manual list pass, one model at a time. Each model gets its own
    timeout so a single slow/stuck model doesn't kill the rest of the list —
    the scraper's dupe-check DB means a timed-out model retries next tick.
    Returns a list of (model, CompletedProcess) tuples (None for timeouts)."""
    if not SCRAPE_USERNAMES:
        log.warning("M02_SCRAPE_USERNAMES empty — manual pass skipped")
        return []
    models = [m.strip() for m in SCRAPE_USERNAMES.split(",") if m.strip()]
    per_model_timeout = int(os.environ.get("M02_SCRAPER_PER_MODEL_TIMEOUT_MIN", "15"))
    results = []
    for i, model in enumerate(models, 1):
        log.info("pass [manual] model %d/%d: %s", i, len(models), model)
        r = _run_scraper_pass("manual:%s" % model, ["--username", model], timeout_min=per_model_timeout)
        results.append((model, r))
        # Push whatever has landed in staging so far — keeps staging from
        # filling up across many models and gives partial progress on each tick.
        pushed, failed, skipped = _walk_and_push()
        if pushed or failed:
            log.info("pass [manual] mid-pass push: pushed=%d failed=%d", pushed, failed)
    return results


def _run_scraper_filter():
    """Run the auto-discovery filter pass (e.g. --current-price paid
    --active-subscription --username ALL). Only runs if M02_SCRAPE_FILTER_ARGS
    is set (from the vault). Returns the CompletedProcess or None."""
    if not SCRAPE_FILTER_ARGS:
        log.info("M02_SCRAPE_FILTER_ARGS empty — filter pass skipped")
        return None
    # Split the filter args (space-separated scraper flags). shlex handles
    # quoted values if any.
    import shlex
    args = shlex.split(SCRAPE_FILTER_ARGS)
    return _run_scraper_pass("filter", args)


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

    # Pass 1: the explicit manual model list (always runs if set). Loops through
    # models one at a time, each with its own per-model timeout — a single stuck
    # model doesn't kill the rest. Mid-pass pushes keep staging from filling up.
    manual_results = _run_scraper()
    manual_ok = all(r is not None and r.returncode == 0 for _, r in manual_results) if manual_results else True
    if not manual_ok:
        log.warning("manual pass had failures/timeouts; continuing to filter pass")

    # Pass 2: auto-discovery via filter args (e.g. --current-price paid
    # --active-subscription --username ALL). Only runs if M02_SCRAPE_FILTER_ARGS
    # is set. Both passes share the staging dir + dupe-check db, so overlap
    # between the manual list and the filter-discovered models is free —
    # already-downloaded content is skipped.
    r2 = _run_scraper_filter()
    if r2 is not None and r2.returncode != 0:
        log.warning("filter pass incomplete; pushing whatever landed in staging")

    pushed, failed, skipped = _walk_and_push()
    log.info("sweep done: pushed=%d failed=%d skipped=%d", pushed, failed, skipped)


if __name__ == "__main__":
    main()
