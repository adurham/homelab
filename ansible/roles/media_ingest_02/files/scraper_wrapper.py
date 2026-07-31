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
# Name of the upstream source's custom user-list whose members get a full
# backfill scrape each tick. Pin free-tier models to this list in the source
# UI. Empty = skip the pinned-list pass.
PINNED_LIST = os.environ.get("M02_PINNED_LIST", "").strip()

STAGING.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("media-ingest-02")

# Like pass configuration
LIKE_ENABLED = os.environ.get("M02_LIKES_ENABLED", "").lower() in ("1", "true", "yes")
LIKE_DAILY_CAP = int(os.environ.get("M02_LIKES_DAILY_CAP", "500"))
LIKE_PER_MODEL_CAP = int(os.environ.get("M02_LIKES_PER_MODEL_CAP", "50"))
LIKE_STATE_FILE = Path(os.environ.get("M02_LIKE_STATE_FILE", str(STAGING.parent / "like_state.json")))


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
    Returns the list of base args; callers append the model-selection args.
    --neg-filter excludes ad/promotional posts via regex (the --block-ads flag
    is defined but not wired in this scraper version, so we use --neg-filter
    with the ad pattern from the scraper docs)."""
    bin_name = os.environ.get("M02_SCRAPER_BIN", "scraper")
    return [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", bin_name),
        "--config", CONFIG_FILE,
        "--action", "download",
        "--posts", "all",
        "--neg-filter", r"(#(?:ad|ads|AD|advertising|sponsored|promotion)|trial|discount|exclusive\s+offer|giveaway|limited\s+time|\Buser\s+promo|shoutout|endorsement)",
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


def _background_push(stop_event, label):
    """Continuously push staging to the gallery while scrapers are running.
    Runs in a background thread, polling staging every 5s and pushing any
    complete files. This prevents the tmpfs from filling up when high-volume
    models download faster than the post-completion push can clear."""
    import time
    total_pushed = 0
    while not stop_event.is_set():
        pushed, failed, skipped = _walk_and_push()
        total_pushed += pushed
        if pushed or failed:
            log.info("pass [%s] bg-push: pushed=%d failed=%d (running total=%d)",
                     label, pushed, failed, total_pushed)
        time.sleep(5)
    # Final flush after scrapers stop
    pushed, failed, skipped = _walk_and_push()
    total_pushed += pushed
    if pushed or failed:
        log.info("pass [%s] bg-push final: pushed=%d failed=%d (total=%d)",
                 label, pushed, failed, total_pushed)


def _run_scraper():
    """Run the manual list pass with N models in parallel. Each model gets its
    own timeout so a single slow/stuck model doesn't kill the rest — the
    scraper's dupe-check DB means a timed-out model retries next tick.
    Concurrency is bounded by M02_SCRAPER_PARALLELISM (default 4) so we don't
    hammer the upstream API or exhaust the 8G RAM tmpfs staging.
    Returns a list of (model, CompletedProcess) tuples (None for timeouts)."""
    if not SCRAPE_USERNAMES:
        log.warning("M02_SCRAPE_USERNAMES empty — manual pass skipped")
        return []
    models = [m.strip() for m in SCRAPE_USERNAMES.split(",") if m.strip()]
    per_model_timeout = int(os.environ.get("M02_SCRAPER_PER_MODEL_TIMEOUT_MIN", "15"))
    parallelism = int(os.environ.get("M02_SCRAPER_PARALLELISM", "4"))
    log.info("pass [manual] %d models, parallelism=%d, per-model timeout=%dmin",
             len(models), parallelism, per_model_timeout)

    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    stop_push = threading.Event()
    push_thread = threading.Thread(target=_background_push, args=(stop_push, "manual"), daemon=True)
    push_thread.start()
    results = []
    try:
        with ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures = {
                pool.submit(_run_scraper_pass, "manual:%s" % m, ["--username", m], per_model_timeout): m
                for m in models
            }
            for fut in as_completed(futures):
                model = futures[fut]
                r = fut.result()
                results.append((model, r))
    finally:
        stop_push.set()
        push_thread.join(timeout=30)
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


# Upstream package identity (pip name) — SENSITIVE, from the vault via env.
# Used by importlib to load the scraper's internal modules for API discovery
# (subscriptions + custom-lists endpoints). Falls back gracefully if unset.
SCRAPER_PKG = os.environ.get("M02_SCRAPER_PKG", "").strip()


def _load_scraper_modules():
    """Load the upstream scraper's internal modules via importlib, using the
    vault-sourced package name (M02_SCRAPER_PKG) so the package identity isn't
    hardcoded in the working tree. Sets the config-path env vars BEFORE import
    so the scraper's config-reading-at-import-time picks up our config.json.
    Returns a dict of module refs, or None if the package name is unset / import
    fails."""
    import importlib
    if not SCRAPER_PKG:
        log.warning("M02_SCRAPER_PKG unset — discovery passes will be skipped")
        return None
    # Config path env vars must be set BEFORE importing the scraper package —
    # its import chain reads the config at import time.
    os.environ["OFSC_CONFIG_DIR"] = os.path.dirname(CONFIG_FILE)
    os.environ["OFSC_CONFIG_FILE_NAME"] = os.path.basename(CONFIG_FILE)
    venv_site = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "lib", "site-packages")
    sys.path.insert(0, venv_site)
    try:
        mods = {
            "read_args": importlib.import_module(f"{SCRAPER_PKG}.utils.args.accessors.read"),
            "write_args": importlib.import_module(f"{SCRAPER_PKG}.utils.args.mutators.write"),
            "manager": importlib.import_module(f"{SCRAPER_PKG}.managers.manager"),
            "of_env": importlib.import_module(f"{SCRAPER_PKG}.utils.of_env.of_env"),
            "settings": importlib.import_module(f"{SCRAPER_PKG}.utils.settings"),
        }
        # Point the scraper's arg parser at our config.json, then force a
        # settings reinit so the auth/signing machinery loads it.
        args = mods["read_args"].retriveArgs()
        args.config = CONFIG_FILE
        mods["write_args"].setArgs(args)
        mods["settings"].update_settings()
        # The manager global starts as None — instantiate it directly so we can
        # use its session machinery (the normal start path runs the CLI menu).
        if not isinstance(mods["manager"].Manager, mods["manager"].mainManager):
            mods["manager"].Manager = mods["manager"].mainManager()
        return mods
    except Exception as e:
        log.error("failed to load scraper modules: %s: %s", type(e).__name__, e)
        return None


def _discover_subs(price_filter, label):
    """Discover active subscriptions matching a price filter. Uses the scraper's
    own auth machinery (same venv, same auth.json). price_filter is a callable
    (price -> bool). label is a short tag for logging ('paid', 'free').
    Replicates final_current_price logic from the scraper's models module."""
    import asyncio
    mods = _load_scraper_modules()
    if mods is None:
        return []
    mgr = mods["manager"].Manager  # the mainManager instance (has .session)
    of_env = mods["of_env"]

    async def _fetch():
        usernames = []
        async with mgr.session.aget_subscription_session() as c:
            offset = 0
            while True:
                url = of_env.getattr("subscriptionsActiveEP").format(offset)
                async with c.requests_async(url=url) as r:
                    if not (200 <= r.status < 300):
                        log.error("subscriptions API error %d at offset %d", r.status, offset)
                        break
                    data = await r.json_()
                    subs = data.get("list", [])
                    if not subs:
                        break
                    for sub in subs:
                        sub_data = sub.get("subscribedByData") or {}
                        sub_price = sub_data.get("regularPrice")
                        promo = sub_data.get("lowestPromoClaim")
                        regular = sub_data.get("regularPrice") if sub_data else None
                        price = sub_price if sub_price is not None else (
                            promo if promo is not None else (regular if regular is not None else 0)
                        )
                        username = sub.get("username")
                        if username and price_filter(price):
                            usernames.append(username)
                    if data.get("hasMore") is not True:
                        break
                    offset += len(subs)
        return usernames

    try:
        usernames = asyncio.run(_fetch())
        # Dedup + strip the manual list (those are already scraped in pass 1)
        manual = {m.strip().lower() for m in SCRAPE_USERNAMES.split(",") if m.strip()}
        discovered = sorted({u.lower() for u in usernames} - manual)
        log.info("discovery [%s]: %d active subs (%d after dedup with manual list)",
                 label, len(usernames), len(discovered))
        return discovered
    except Exception as e:
        log.error("discovery [%s] failed: %s: %s", label, type(e).__name__, e)
        return []


def _discover_paid_subs():
    """Discover active paid subscriptions (price > 0, including temp trials
    where regularPrice > 0 but sub_price may be 0)."""
    return _discover_subs(lambda p: p > 0, "paid")


def _discover_free_subs():
    """Discover active free subscriptions (price == 0)."""
    return _discover_subs(lambda p: p == 0, "free")


def _run_scraper_filter_parallel():
    """Pass 2: discover active paid subs via the source API, then scrape them
    in parallel using the same ThreadPoolExecutor as the manual pass. Falls
    back to the old single-process filter pass if discovery fails (returns
    empty list)."""
    discovered = _discover_paid_subs()
    if not discovered:
        log.warning("discovery returned no subs — falling back to legacy filter pass")
        return _run_scraper_filter()
    return _run_scraper_discovered_pass("filter", discovered)


def _run_scraper_free_parallel():
    """Pass 4: discover active free subs via the source API, then scrape them
    in parallel. Same pattern as the paid-subs pass."""
    discovered = _discover_free_subs()
    if not discovered:
        log.info("free-subs discovery returned no subs — free pass skipped")
        return []
    return _run_scraper_discovered_pass("free", discovered)


def _run_scraper_discovered_pass(label, discovered):
    """Shared parallel scrape runner for discovered model lists (paid/free
    subs, pinned list). Uses a background push thread to keep staging clear
    while scrapers download."""
    parallelism = int(os.environ.get("M02_SCRAPER_PARALLELISM", "4"))
    per_model_timeout = int(os.environ.get("M02_SCRAPER_PER_MODEL_TIMEOUT_MIN", "15"))
    log.info("pass [%s] %d models, parallelism=%d", label, len(discovered), parallelism)
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    stop_push = threading.Event()
    push_thread = threading.Thread(target=_background_push, args=(stop_push, label), daemon=True)
    push_thread.start()
    results = []
    try:
        with ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures = {
                pool.submit(_run_scraper_pass, "%s:%s" % (label, m), ["--username", m], per_model_timeout): m
                for m in discovered
            }
            for fut in as_completed(futures):
                model = futures[fut]
                r = fut.result()
                results.append((model, r))
    finally:
        stop_push.set()
        push_thread.join(timeout=30)
    return results


def _discover_pinned_list():
    """Discover members of the configured custom user-list on the source
    platform. Returns a list of usernames. Uses the scraper's auth machinery —
    same as paid-sub discovery. The list name is matched case-insensitively
    against the user's custom lists (listEP -> find by name -> listusersEP ->
    enumerate users)."""
    if not PINNED_LIST:
        log.info("M02_PINNED_LIST empty — pinned-list pass skipped")
        return []
    import asyncio
    mods = _load_scraper_modules()
    if mods is None:
        return []
    mgr = mods["manager"].Manager  # the mainManager instance (has .session)
    of_env = mods["of_env"]

    async def _fetch():
        usernames = []
        async with mgr.session.aget_subscription_session() as c:
            # 1. Enumerate all custom lists, find the one matching PINNED_LIST
            list_id = None
            offset = 0
            target = PINNED_LIST.lower()
            while True:
                url = of_env.getattr("listEP").format(offset)
                async with c.requests_async(url=url) as r:
                    if not (200 <= r.status < 300):
                        log.error("lists API error %d at offset %d", r.status, offset)
                        break
                    data = await r.json_()
                    lists = data.get("list", [])
                    if not lists:
                        break
                    for lst in lists:
                        if (lst.get("name") or "").lower() == target:
                            list_id = lst.get("id")
                            break
                    if list_id or data.get("hasMore") is not True:
                        break
                    offset += len(lists)
            if list_id is None:
                log.error("pinned list %r not found in source custom lists", PINNED_LIST)
                return []
            # 2. Enumerate users in that list
            offset = 0
            while True:
                url = of_env.getattr("listusersEP").format(list_id, offset)
                async with c.requests_async(url=url) as r:
                    if not (200 <= r.status < 300):
                        log.error("list users API error %d at offset %d", r.status, offset)
                        break
                    data = await r.json_()
                    users = data.get("list", [])
                    if not users:
                        break
                    for u in users:
                        username = u.get("username")
                        if username:
                            usernames.append(username)
                    if data.get("hasMore") is not True:
                        break
                    offset += len(users)
        return usernames

    try:
        usernames = asyncio.run(_fetch())
        # Dedup against manual list (those are already scraped in pass 1)
        manual = {m.strip().lower() for m in SCRAPE_USERNAMES.split(",") if m.strip()}
        discovered = sorted({u.lower() for u in usernames} - manual)
        log.info("pinned list %r: %d members (%d after dedup with manual list)",
                 PINNED_LIST, len(usernames), len(discovered))
        return discovered
    except Exception as e:
        log.error("pinned list discovery failed: %s: %s", type(e).__name__, e)
        return []


def _run_scraper_pinned_parallel():
    """Pass 3: scrape members of the pinned custom user-list in parallel. Full
    backfill — the scraper's dupe-check DB means re-runs only fetch new content.
    Skipped if M02_PINNED_LIST is empty or the list isn't found."""
    discovered = _discover_pinned_list()
    if not discovered:
        return []
    return _run_scraper_discovered_pass("pinned", discovered)


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


def _clear_stale_staging():
    """Guard against the tmpfs-OOM trap: a file that fails to push (e.g. a
    connection timeout on an oversized download) is deliberately NOT deleted
    by _walk_and_push so it can retry next tick. But since tmpfs usage counts
    as cgroup memory, a single large orphaned file (seen: an 8.8GB stuck video
    that sat for 3+ days, 2026-07-15 to 2026-07-18) can push staging close to
    the memory ceiling, causing every subsequent tick to get OOM-killed within
    ~10s -- too fast for the retry logic (or even its own error log) to ever
    run, so the file never clears and the tick-kill loop repeats forever.
    Fix: at the START of every sweep, before anything else runs, delete any
    staging file older than MAX_STAGING_FILE_AGE_SEC (default 2x the timer
    interval). This is safe and lossless -- per this wrapper's own dupe-check
    contract (see module docstring), anything dropped here is simply
    re-downloaded on the next sweep."""
    max_age = int(os.environ.get("M02_MAX_STAGING_FILE_AGE_SEC", str(4 * 3600)))
    if not STAGING.exists():
        return
    now = dt.datetime.now().timestamp()
    cleared = 0
    cleared_bytes = 0
    for model_dir in sorted(STAGING.iterdir()):
        if not model_dir.is_dir():
            continue
        for fpath in sorted(model_dir.iterdir()):
            if not fpath.is_file():
                continue
            try:
                st = fpath.stat()
            except OSError:
                continue
            age = now - st.st_mtime
            if age > max_age:
                size = st.st_size
                try:
                    fpath.unlink()
                    cleared += 1
                    cleared_bytes += size
                    log.warning(
                        "cleared stale staging file %s (age=%.0fmin, size=%.1fMB) "
                        "-- will re-download next sweep",
                        fpath, age / 60, size / 1e6,
                    )
                except OSError as e:
                    log.error("failed to clear stale staging file %s: %s", fpath, e)
        try:
            if not any(model_dir.iterdir()):
                model_dir.rmdir()
        except OSError:
            pass
    if cleared:
        log.warning("stale staging sweep: cleared %d file(s), %.1fMB total",
                    cleared, cleared_bytes / 1e6)


def _check_staging_usage():
    """Log a loud warning if staging tmpfs usage is high enough to risk an
    OOM trap on the next sweep, so this shows up clearly in logs/monitoring
    instead of silently degrading for days (as happened 2026-07-15/18)."""
    import shutil
    if not STAGING.exists():
        return
    try:
        usage = shutil.disk_usage(STAGING)
    except OSError:
        return
    pct = usage.used / usage.total * 100 if usage.total else 0
    if pct >= 50:
        log.warning("staging tmpfs at %.1f%% (%.1fGB/%.1fGB) -- risk of OOM if this grows",
                    pct, usage.used / 1e9, usage.total / 1e9)
    else:
        log.info("staging tmpfs at %.1f%% (%.1fGB/%.1fGB)",
                  pct, usage.used / 1e9, usage.total / 1e9)


def _like_base_cmd():
    """Build the base scraper invocation for liking (action=like, posts=timeline).
    Shares the binary path, config, and neg-filter with the download base cmd
    but uses --action like and --posts timeline instead."""
    bin_name = os.environ.get("M02_SCRAPER_BIN", "scraper")
    return [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", bin_name),
        "--config", CONFIG_FILE,
        "--action", "like",
        "--posts", "timeline",
        "--neg-filter", r"(#(?:ad|ads|AD|advertising|sponsored|promotion)|trial|discount|exclusive\s+offer|giveaway|limited\s+time|\Buser\s+promo|shoutout|endorsement)",
    ]


def _count_likes_from_output(r):
    """Try to count how many posts were actually liked by parsing the scraper's
    stdout/stderr output. Returns the number of likes performed, or 0 if
    undetermined."""
    import re
    output = (r.stdout or "") + (r.stderr or "")
    # Look for explicit "Liked X posts" or "liked X" patterns
    for pattern in [r"[Ll]iked\s+(\d+)\s+posts?", r"(\d+)\s+posts?\s+liked"]:
        m = re.search(pattern, output, re.IGNORECASE)
        if m:
            return int(m.group(1))
    # Fallback: count "Liking" action lines
    count = output.count("Liking") + output.count("liking")
    if count > 0:
        return count
    return 0


def _write_like_state(state):
    """Persist like state to JSON file."""
    import json
    try:
        LIKE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIKE_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))
    except OSError as e:
        log.error("failed to write like state: %s", e)


LIKE_PER_MODEL_TIMEOUT = int(os.environ.get("M02_LIKES_PER_MODEL_TIMEOUT", str(15 * 60)))


def _run_like_pass():
    """Like timeline posts from active subscriptions. Runs after all download
    passes. Works through one model's backlog per sweep (round-robin), up to
    the daily cap, then switches to daily mode (last 24h only) once all models'
    backlogs are caught up. Tracks state in LIKE_STATE_FILE so progress
    survives restarts and timer ticks."""
    if not LIKE_ENABLED:
        log.info("like pass skipped — disabled (M02_LIKES_ENABLED)")
        return

    import json

    # Read/init state
    state = {}
    if LIKE_STATE_FILE.exists():
        try:
            state = json.loads(LIKE_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("like_state.json corrupt (%s) — resetting", e)

    today = dt.date.today().isoformat()
    if state.get("date") != today:
        log.info("like state: new day %s (was %s), resetting daily counter",
                 today, state.get("date", "never"))
        state["date"] = today
        state["daily_likes_used"] = 0
        state.setdefault("backlog_mode", True)
        state.setdefault("backlog_index", 0)

    if state.get("daily_likes_used", 0) >= LIKE_DAILY_CAP:
        log.info("like pass skipped — daily cap %d already used", LIKE_DAILY_CAP)
        _write_like_state(state)
        return

    remaining = LIKE_DAILY_CAP - state.get("daily_likes_used", 0)

    # Build active model list (manual list only — explicit subs the user chose)
    models = [m.strip() for m in SCRAPE_USERNAMES.split(",") if m.strip()]
    if not models:
        log.info("like pass skipped — no models configured")
        return

    if state.get("backlog_mode", True):
        # Backlog mode: one model per sweep. Likes up to remaining cap worth
        # of that model's unliked timeline posts (no time filter = all unliked
        # posts). Once we've cycled through all models, switch to daily mode.
        idx = state.get("backlog_index", 0)
        if idx >= len(models):
            log.info("like pass: cycled through all models — switching to daily mode")
            state["backlog_mode"] = False
            state["backlog_index"] = 0
            _write_like_state(state)
        else:
            model = models[idx]
            log.info("like pass [backlog:%s] daily_used=%d/%d, idx=%d/%d",
                     model, state.get("daily_likes_used", 0), LIKE_DAILY_CAP,
                     idx + 1, len(models))
            cmd = _like_base_cmd() + [
                "--max-post-count", str(remaining),
                "--username", model,
            ]
            try:
                r = subprocess.run(cmd, check=False, capture_output=True, text=True,
                                   timeout=LIKE_PER_MODEL_TIMEOUT)
            except subprocess.TimeoutExpired:
                log.warning("like pass [backlog:%s] timed out after %dmin",
                            model, LIKE_PER_MODEL_TIMEOUT)
                return
            actual = _count_likes_from_output(r)
            log.info("like pass [backlog:%s] exit=%d, liked=%d", model, r.returncode, actual)
            state["daily_likes_used"] = state.get("daily_likes_used", 0) + actual
            # Advance to next model (even on failure) so we don't get stuck
            state["backlog_index"] += 1
            _write_like_state(state)
            return  # one model per sweep

    # Daily mode: like last 24h from all active models
    remaining = LIKE_DAILY_CAP - state.get("daily_likes_used", 0)
    if remaining <= 0:
        return
    yesterday = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%m/%d/%Y")
    per_model = max(1, remaining // len(models))
    likes_used = 0
    for model in models:
        if likes_used >= remaining:
            break
        cap = min(per_model, remaining - likes_used)
        cmd = _like_base_cmd() + [
            "--after", yesterday,
            "--max-post-count", str(cap),
            "--username", model,
        ]
        log.info("like pass [daily:%s] cap=%d, remaining=%d", model, cap, remaining - likes_used)
        try:
            r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=15 * 60)
        except subprocess.TimeoutExpired:
            log.warning("like pass [daily:%s] timed out after 15min", model)
            continue
        if r.returncode != 0:
            log.warning("like pass [daily:%s] exit %d: %s", model, r.returncode, (r.stderr or "")[-500:])
        actual = _count_likes_from_output(r)
        if actual > 0:
            log.info("like pass [daily:%s] liked %d posts", model, actual)
        likes_used += actual
        if likes_used >= remaining:
            break

    state["daily_likes_used"] = state.get("daily_likes_used", 0) + likes_used
    _write_like_state(state)
    log.info("like pass done: %d likes used today (%d/%d)",
             state["daily_likes_used"], state["daily_likes_used"], LIKE_DAILY_CAP)


def main():
    _clear_stale_staging()
    _check_staging_usage()
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

    # Pass 2: auto-discovery of active paid subs via the source API, then
    # scraped in parallel (same ThreadPoolExecutor as the manual pass). Replaces
    # the old single-process '--username ALL' filter pass which was the
    # bottleneck. Falls back to the legacy filter pass if discovery fails. Both
    # passes share the staging dir + dupe-check db, so overlap between the
    # manual list and the discovered subs is free — already-downloaded content
    # is skipped.
    filter_results = _run_scraper_filter_parallel()
    if isinstance(filter_results, list):
        filter_ok = all(r is not None and r.returncode == 0 for _, r in filter_results) if filter_results else True
        if not filter_ok:
            log.warning("filter pass had failures/timeouts; pushing whatever landed in staging")
    elif filter_results is not None and getattr(filter_results, "returncode", 0) != 0:
        log.warning("filter pass incomplete; pushing whatever landed in staging")

    # Pass 3: pinned custom user-list — free-tier models pinned for full
    # backfill. Skipped if M02_PINNED_LIST is empty or the list isn't found.
    # Shares the staging dir + dupe-check db, so overlap with passes 1+2 is free.
    pinned_results = _run_scraper_pinned_parallel()
    if pinned_results:
        pinned_ok = all(r is not None and r.returncode == 0 for _, r in pinned_results)
        if not pinned_ok:
            log.warning("pinned pass had failures/timeouts; pushing whatever landed in staging")

    # Pass 4: auto-discovery of active free subs (price == 0). Same parallel
    # pattern as paid subs. Shares staging + dupe-check db, so overlap with
    # passes 1-3 is free.
    free_results = _run_scraper_free_parallel()
    if free_results:
        free_ok = all(r is not None and r.returncode == 0 for _, r in free_results)
        if not free_ok:
            log.warning("free pass had failures/timeouts; pushing whatever landed in staging")

    pushed, failed, skipped = _walk_and_push()
    log.info("sweep done: pushed=%d failed=%d skipped=%d", pushed, failed, skipped)

    # Pass 5: like timeline posts from active subscriptions. Runs after all
    # downloads and pushes are complete. Only targets the manual model list
    # (explicit subs), not auto-discovered free subs. See _run_like_pass() for
    # the backlog/daily mode state machine.
    _run_like_pass()


if __name__ == "__main__":
    main()
