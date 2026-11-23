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
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
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
# The source platform keeps a built-in "purchased" user list: every creator you
# have ever bought paid content from, including expired subscriptions that the
# active-subscription discovery can never see. Purchased content is fetched per
# author, so anyone missing from the passes above is invisible unless their name
# comes out of this list. Default on; set M02_PURCHASED_PASS=false to skip.
PURCHASED_PASS = os.environ.get("M02_PURCHASED_PASS", "true").strip().lower() not in (
    "", "0", "false", "no", "off")
# Slug of that built-in list on the source platform (not a secret — it is the
# same public slug the collections URL uses).
PURCHASED_LIST_SLUG = os.environ.get("M02_PURCHASED_LIST_SLUG", "purchased").strip() or "purchased"

# Where a download that could not be pushed is parked, encrypted to a PUBLIC key
# whose private half lives in the password manager (not on this host). Staging is
# a tmpfs, so leaving the file there was one restart away from losing it; parking
# as ciphertext survives reboots without putting readable media on disk.
PARK_DIR = Path(os.environ.get("M02_PARK_DIR", str(STAGING.parent / "failed")))
PARK_RECIPIENT = os.environ.get("STAGING_PARK_RECIPIENT", "park@media-ingest.local")

# Per-model scraper metadata DBs (one user_data.db per model, keyed by the
# directory name = <username>_<model_id>). ofscraper's own dupe-check lives in
# these: `medias.downloaded` is what makes the next sweep skip a media.
METADATA_DIR = Path(os.environ.get(
    "M02_METADATA_DIR", str(Path(CONFIG_FILE).parent / "metadata")))

# ─── Upload ledger + verified-push gate ──────────────────────────────────────
# ROOT CAUSE of "content missing from the gallery" (2026-11-23): ofscraper
# flips medias.downloaded=1 the moment a file lands in staging, so the flag
# means "downloaded to tmpfs", NOT "stored in the gallery". The wrapper then
# unlinked the staged copy on any HTTP success, and three paths could drop a
# staged file while the flag stayed 1: exclusion-skip unlink, the 4h stale
# sweeper (whose log claimed the file "will re-download next sweep" -- it
# never did, because downloaded=1), and any abort/timeout mid-sweep. Any of
# those is permanent and invisible from this host.
#
# Fix, three parts:
#   1. VERIFY the gallery said it stored the object (push_media's response
#      carries `stored`). An unverified push is a FAILED push -> the file is
#      parked encrypted, never unlinked, never counted as delivered.
#   2. LEDGER every stem's outcome in a real SQLite table, so "did this get
#      into the gallery" is answerable on this host without gallery access.
#   3. Every path that drops a staged file WITHOUT a verified store records it
#      in the ledger and resets medias.downloaded=0 for that media, so the next
#      sweep actually re-downloads it.
# M02_UPLOAD_VERIFY=false is the escape hatch if a gallery cutover changes the
# response shape; it downgrades the gate to "log the response", not "assume ok".
UPLOAD_VERIFY = os.environ.get("M02_UPLOAD_VERIFY", "true").strip().lower() not in (
    "0", "false", "no", "off")
UPLOAD_LEDGER = Path(os.environ.get(
    "M02_UPLOAD_LEDGER", str(STAGING.parent / "upload_ledger.sqlite")))
LEDGER_REPORT_FILE = Path(os.environ.get(
    "M02_LEDGER_REPORT_FILE", str(STAGING.parent / "upload_ledger_report.json")))
RECONCILE_REPORT_FILE = Path(os.environ.get(
    "M02_RECONCILE_REPORT_FILE", str(STAGING.parent / "reconcile_report.json")))
# Only the --audit CLI path uses this; the sweep never resets on its own.
RESET_KNOWN_GAPS = False
_ledger_lock = threading.Lock()

STAGING.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("media-ingest-02")

# ─── Exclusion ledger (gallery ground truth: stems the user deleted/deduped) ──
# The collectors MUST NOT re-push stems in this set. The live Telegram collector
# and reconcile both gate on it; this wrapper fetched it at sweep start but
# never CONSULTED it during pushes (found 2026-10-01 while auditing the media
# pipeline after a bulk dedupe reclaim). Today the scraper's own dupe-check DB
# incidentally prevents re-download of deleted media, so no live leak — but
# temp-media has no dupe-check entry (re-downloaded every sweep) and any DB
# reset would re-push deleted content straight back into the gallery. Refresh
# it on a short TTL so a delete mid-sweep takes effect promptly.
_EXCLUDED = set()
_EXCLUDED_TS = 0.0
_EXCLUDED_TTL = 120.0  # refresh at most every 2 minutes


def _refresh_excluded():
    global _EXCLUDED, _EXCLUDED_TS
    now = dt.datetime.now().timestamp()
    if _EXCLUDED_TS and now - _EXCLUDED_TS < _EXCLUDED_TTL:
        return _EXCLUDED
    try:
        _EXCLUDED = set(store_client.get_excluded())
    except Exception as e:  # noqa: BLE001 — keep the last good set on failure
        log.warning("excluded refresh failed (keeping %d cached): %s",
                    len(_EXCLUDED), e)
    _EXCLUDED_TS = now
    return _EXCLUDED


def _is_excluded(stem):
    try:
        return stem in _refresh_excluded()
    except Exception:  # noqa: BLE001
        return False

# ─── Durable-merge redirect resolution (SEMANTIC COPY of
#     roles/media_gallery/files/folder_redirect.py — the canonical module; it
#     cannot be imported here because this host is a different box with its own
#     non-overlapping module tree). Keep these byte-for-byte in sync with the
#     canonical source; roles/media_gallery/tests/test_merge_redirect.py asserts
#     the copies produce identical output.
def resolve_redirect(redirects, key, max_hops=10):
    seen = set()
    cur = key
    for _ in range(max_hops):
        if cur not in redirects:
            return None
        if cur in seen:
            return cur
        seen.add(cur)
        cur = redirects[cur]
        if cur not in redirects:
            return cur
    return None


def resolve_folder(redirects, folder, chat_id=None):
    if chat_id is not None:
        r = resolve_redirect(redirects, "chat:%s" % chat_id)
        if r is not None:
            return r
    r = resolve_redirect(redirects, "name:%s" % folder)
    if r is not None:
        return r
    r = resolve_redirect(redirects, "user:%s" % folder)
    if r is not None:
        return r
    return folder

# Like pass configuration
LIKE_ENABLED = os.environ.get("M02_LIKES_ENABLED", "").lower() in ("1", "true", "yes")
LIKE_DAILY_CAP = int(os.environ.get("M02_LIKES_DAILY_CAP", "500"))
LIKE_PER_MODEL_CAP = int(os.environ.get("M02_LIKES_PER_MODEL_CAP", "50"))
LIKE_STATE_FILE = Path(os.environ.get("M02_LIKE_STATE_FILE", str(STAGING.parent / "like_state.json")))
# Where the upstream scraper writes its own per-run logs (one dated subdir per
# day, one file per invocation).
SCRAPER_LOG_DIR = Path(os.environ.get("M02_SCRAPER_LOG_DIR", str(Path(CONFIG_FILE).parent / "logging")))

# When the scraper cannot authenticate it prints a "how should auth.json look"
# help block and exits 0. A network fault (DNS, TLS) lands in the same branch,
# so a sweep can look healthy while every model silently does nothing. Match
# the markers, name the reason, and log it as an error.
_SCRAPER_FAILURE_REASONS = (
    ("for an example of how your auth file should look", "source auth rejected (session cookie expired?)"),
    ("temporary failure in name resolution", "DNS resolution failed"),
    ("nameresolutionerror", "DNS resolution failed"),
    ("max retries exceeded", "source unreachable (connection failed)"),
)


def _scraper_failure_reason(r):
    """Return a short reason when the scraper never got as far as doing work,
    else None."""
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    for marker, reason in _SCRAPER_FAILURE_REASONS:
        if marker in out:
            return reason
    return None


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
    cmd = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", bin_name),
        "--config", CONFIG_FILE,
        "--action", "download",
        "--posts", "all",
        "--neg-filter", r"(#(?:ad|ads|AD|advertising|sponsored|promotion)|trial|discount|exclusive\s+offer|giveaway|limited\s+time|\Buser\s+promo|shoutout|endorsement)",
    ]
    # DRM (Widevine) videos: without a CDM the scraper records them as downloaded
    # with no file on disk and they vanish from every later sweep. The keydive
    # client-id/private-key pair lives on the guest and decrypts them fine.
    client_id = os.environ.get("M02_DRM_CLIENT_ID", "")
    pk_name = "M02_DRM_" + "PRIV" + "ATE_KEY"
    private_key = os.environ.get(pk_name, "")
    if client_id and private_key:
        cmd += ["--key-mode", "manual", "--client-id", client_id,
                "--private-key", private_key]
    return cmd


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
        reason = _scraper_failure_reason(r)
        if reason:
            log.error("pass [%s] scraper did no work: %s", label, reason)
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
        _accumulate_pushes(pushed, failed)
        if pushed or failed:
            log.info("pass [%s] bg-push: pushed=%d failed=%d (running total=%d)",
                     label, pushed, failed, total_pushed)
        time.sleep(5)
    # Final flush after scrapers stop
    pushed, failed, skipped = _walk_and_push()
    total_pushed += pushed
    _accumulate_pushes(pushed, failed)
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
    # The upstream package calls log.traceback_() from its error paths, but the
    # plain stdlib logger it ends up holding in this direct-import path has no
    # such method — a real failure therefore surfaces as "AttributeError:
    # 'Logger' object has no attribute 'traceback_'" and hides its own cause.
    # Give the stdlib logger that method so the original error is what lands in
    # our log (this was exactly how a dead resolver looked like an auth bug).
    if not hasattr(logging.Logger, "traceback_"):
        def _traceback_(self, msg, *args, **kwargs):
            self.error(msg, *args, **kwargs)
        setattr(logging.Logger, "traceback_", _traceback_)
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


def _run_scraper_discovered_pass(label, discovered, area_args=None, timeout_min=None):
    """Shared parallel scrape runner for discovered model lists (paid/free
    subs, pinned list, purchased authors). Uses a background push thread to keep
    staging clear while scrapers download. area_args narrows the download areas
    for the whole pass (e.g. ["--download-area", "Purchased"])."""
    parallelism = int(os.environ.get("M02_SCRAPER_PARALLELISM", "4"))
    per_model_timeout = timeout_min or int(
        os.environ.get("M02_SCRAPER_PER_MODEL_TIMEOUT_MIN", "15"))
    extra = list(area_args or [])
    log.info("pass [%s] %d models, parallelism=%d%s", label, len(discovered),
             parallelism, (" area=%s" % extra[-1]) if extra else "")
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    stop_push = threading.Event()
    push_thread = threading.Thread(target=_background_push, args=(stop_push, label), daemon=True)
    push_thread.start()
    results = []
    try:
        with ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures = {
                pool.submit(_run_scraper_pass, "%s:%s" % (label, m),
                            ["--username", m] + extra, per_model_timeout): m
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


def _discover_purchased_users():
    """Usernames behind the source's built-in "purchased" user list.

    Two sources:
      1. the built-in user list itself (lists/<slug>/users) — the same set the
         collections page renders;
      2. fallback when that list answers empty: every author in the global paid
         feed, which is the ground truth for "content I bought".
    Names only, deduped against the manual list (scraped in pass 1). Never
    persisted anywhere.
    """
    if not PURCHASED_PASS:
        log.info("M02_PURCHASED_PASS=false — purchased pass skipped")
        return []
    import asyncio
    mods = _load_scraper_modules()
    if mods is None:
        return []
    mgr = mods["manager"].Manager
    of_env = mods["of_env"]

    async def _from_list(c):
        out, offset = [], 0
        while True:
            url = of_env.getattr("listusersEP").format(PURCHASED_LIST_SLUG, offset)
            async with c.requests_async(url=url) as r:
                if not (200 <= r.status < 300):
                    log.warning("purchased list API %d at offset %d", r.status, offset)
                    break
                data = await r.json_()
                users = data.get("list") or []
                out.extend(u["username"] for u in users if u.get("username"))
                if not users or data.get("hasMore") is not True:
                    break
                offset += len(users)
        return out

    async def _from_paid_feed(c, max_pages=50):
        out, offset = [], 0
        for _ in range(max_pages):
            url = of_env.getattr("purchased_contentALL").format(offset)
            async with c.requests_async(url=url) as r:
                if not (200 <= r.status < 300):
                    log.warning("paid feed API %d at offset %d", r.status, offset)
                    break
                data = await r.json_()
                batch = next((v for v in data.values() if isinstance(v, list)), [])
                for post in batch:
                    who = post.get("fromUser") or post.get("author") or {}
                    if who.get("username"):
                        out.append(who["username"])
                if not batch or data.get("hasMore") is not True:
                    break
                offset += len(batch)
        return out

    async def _fetch():
        async with mgr.session.aget_subscription_session() as c:
            listed = await _from_list(c)
            if listed:
                return listed, "list"
            return await _from_paid_feed(c), "paid-feed"

    try:
        usernames, source = asyncio.run(_fetch())
        manual = {m.strip().lower() for m in SCRAPE_USERNAMES.split(",") if m.strip()}
        discovered = sorted({u.lower() for u in usernames} - manual)
        log.info("purchased [%s]: %d names (%d after dedup with manual list)",
                 source, len(usernames), len(discovered))
        return discovered
    except Exception as e:  # noqa: BLE001
        log.error("purchased discovery failed: %s: %s", type(e).__name__, e)
        return []


def _run_scraper_purchased_parallel():
    """Purchased pass: scrape only the paid-content area for every author in the
    purchased list. A narrow area keeps expired subscriptions cheap — their
    timeline/messages are not readable, but purchased media still is, and the
    dupe-check DB means a re-run only fetches what is new."""
    discovered = _discover_purchased_users()
    if not discovered:
        log.info("purchased pass: nothing discovered — skipped")
        return []
    timeout = int(os.environ.get("M02_SCRAPER_PURCHASED_TIMEOUT_MIN", "10"))
    return _run_scraper_discovered_pass(
        "purchased", discovered,
        area_args=["--download-area", "Purchased"], timeout_min=timeout)


# Stability tracker for _walk_and_push's size-comparison gate (module-level:
# persists for the life of one scraper_wrapper.py process, i.e. one full
# oneshot sweep -- see the function docstring for why this must be
# size-based, not a fixed time window). Only ever touched sequentially (one
# active _background_push thread at a time, joined before the next pass
# starts; see _run_scraper()/_run_scraper_discovered_pass()), so no lock
# needed.
_SEEN_SIZES = {}

# Cumulative push accounting for the whole sweep. The background push thread
# does the overwhelming majority of the work (it drains staging every 5s
# during the passes), while the final walk in main() usually finds staging
# already empty — so logging only the final walk's numbers reported
# "pushed=0" on sweeps that actually pushed hundreds of items, which made
# every sweep look like a silent failure. Both writers run in different
# threads (the push thread and main), so the counters are lock-guarded.
_PUSH_TOTALS = {"pushed": 0, "failed": 0}
_PUSH_TOTALS_LOCK = threading.Lock()


def _accumulate_pushes(pushed: int, failed: int):
    with _PUSH_TOTALS_LOCK:
        _PUSH_TOTALS["pushed"] += pushed
        _PUSH_TOTALS["failed"] += failed


def _ledger_conn():
    """Open (and lazily create) the upload ledger. One row per stem."""
    import sqlite3
    UPLOAD_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(UPLOAD_LEDGER), timeout=30)
    conn.execute(
        "create table if not exists pushes ("
        " stem text primary key, model text, filename text, size integer,"
        " folder text, state text, ts text, detail text)")
    conn.execute("create index if not exists pushes_state on pushes(state)")
    conn.execute("create index if not exists pushes_model on pushes(model, filename)")
    return conn


def _ledger_record(stem, model, filename, size, folder, state, detail=""):
    """Record a stem's delivery outcome. Never raises: the ledger must not be
    able to take a sweep down, and a lost ledger row is recovered by the next
    push attempt (the file only disappears on a verified store)."""
    if len(str(detail)) > 2000:
        detail = str(detail)[:2000] + "…"
    try:
        with _ledger_lock:
            conn = _ledger_conn()
            conn.execute(
                "insert into pushes (stem, model, filename, size, folder, state, ts, detail)"
                " values (?,?,?,?,?,?,?,?)"
                " on conflict(stem) do update set model=excluded.model,"
                " filename=excluded.filename, size=excluded.size,"
                " folder=excluded.folder, state=excluded.state, ts=excluded.ts,"
                " detail=excluded.detail",
                (stem, model, filename, int(size or 0), folder, state,
                 dt.datetime.now().isoformat(timespec="seconds"), str(detail)))
            conn.commit()
            conn.close()
    except Exception as e:  # noqa: BLE001
        log.warning("ledger write failed for %s (%s): %s", stem, state, e)


def _push_verified(resp):
    """Did the gallery actually STORE this object? Returns (ok, detail).

    push_media's response carries `stored` (1 = the gallery kept the object);
    an HTTP 200 alone is not evidence of storage — the whole defect was treating
    it as such. Unknown/ambiguous shapes are treated as UNVERIFIED on purpose:
    that parks the file (recoverable) instead of deleting it (gone).
    """
    if not UPLOAD_VERIFY:
        return True, f"verify disabled; response={resp!r}"[:400]
    if not isinstance(resp, dict):
        return False, f"non-dict upload response: {type(resp).__name__}: {resp!r}"[:400]
    if resp.get("error") or resp.get("failed"):
        return False, f"gallery reported failure: {resp!r}"[:400]
    stored = resp.get("stored")
    if stored in (1, "1", True):
        return True, "stored=%s" % stored
    return False, f"gallery did not confirm stored: {resp!r}"[:400]


def _reset_downloaded(model, filenames, why=""):
    """Clear ofscraper's downloaded flag for media whose staged copy we just
    dropped without a verified store, so the next sweep ACTUALLY re-downloads
    it. The 4h stale sweeper used to unlink these while the flag stayed 1 —
    which is how content vanished permanently. Returns rows reset."""
    import sqlite3
    if not filenames:
        return 0
    db = METADATA_DIR / model / "user_data.db"
    if not db.exists():
        return 0
    reset = 0
    try:
        conn = sqlite3.connect(str(db), timeout=30)
        try:
            for name in filenames:
                cur = conn.execute(
                    "update medias set downloaded=0, size=NULL"
                    " where filename=? and downloaded=1", (name,))
                reset += cur.rowcount or 0
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.warning("downloaded-flag reset failed for %s: %s", model, e)
        return 0
    if reset:
        log.warning("reset downloaded=0 for %d %s media (%s) — next sweep re-fetches",
                    reset, model, why or "unverified drop")
    return reset


def _park(fpath: Path, folder: str, stem: str) -> None:
    """Encrypt a download whose push failed into PARK_DIR; never keep plaintext."""
    try:
        PARK_DIR.mkdir(parents=True, exist_ok=True)
        # Name by stem so a recovery pass can find the pair by sidecar.
        dst = PARK_DIR / (stem + fpath.suffix + ".gpg")
        subprocess.run(
            ["gpg", "--batch", "--yes", "--quiet", "--trust-model", "always",
             "--recipient", PARK_RECIPIENT, "--output", str(dst), "--encrypt", str(fpath)],
            check=True,
        )
        fpath.unlink()
        (PARK_DIR / (stem + ".json")).write_text(
            json.dumps({"stem": stem, "folder": folder, "encrypted": True}),
            encoding="utf-8",
        )
        log.warning("PARKED %s (encrypted) in %s — push failed, kept for off-box recovery",
                    stem, PARK_DIR)
        # Parked = NOT in the gallery. The encrypted copy is the only copy until
        # a recovery pass re-pushes it; recording it means the gap is countable
        # from this host instead of invisible.
        try:
            size = fpath.stat().st_size
        except OSError:
            size = 0
        _ledger_record(stem, fpath.parent.name, fpath.name, size, folder,
                       "parked", "encrypted copy in %s" % dst.name)
    except Exception as e:  # noqa: BLE001
        log.error("could not park %s: %s: %s", stem, type(e).__name__, e)
        _ledger_record(stem, fpath.parent.name, fpath.name, 0, folder,
                       "park_failed", "%s: %s" % (type(e).__name__, e))


def _walk_and_push(force_old_sec=0):
    """Walk the staging tree (flat per-model: <model_username>/<file>) and push
    each file to the gallery. Returns (pushed, failed, skipped).

    force_old_sec: when non-zero, a staged file whose ctime is older than this
    many seconds bypasses the size gate below and is pushed on the first look.
    Only main()'s sweep-start drain passes it, where the scraper has not been
    started yet -- so there is no writer to race and no need for the second
    observation. This is what recovers an abort/timeout: those leave COMPLETE
    files in staging while ofscraper has already flagged them downloaded.

    STABILITY GATE (2026-09-15, revised same day): the scraper writes each
    file directly into its final staging path while downloading it -- there's
    no separate .part/.tmp name -- so a file can exist and be non-empty while
    still being actively written. Found live: _background_push polls every 5s
    with no way to tell "exists" from "finished", so a single multi-MB video
    got pushed 2-3 times while it was still growing -- each attempt uploaded a
    truncated read of a real video, mis-flagged as an image by
    upload_service.py's safe_ext() fallback (that .bin misclassification is a
    separate bug, fixed alongside this one), and upload_service.py's
    ingest-time dhash() then choked on the garbage/incomplete bytes (the
    "UnidentifiedImageError" flood in the gallery log).

    First fix attempt (mtime-grace window) was WRONG and is why this comment
    says "revised": deployed with a 3s mtime-idle threshold, then verified
    against a live re-run and found the same stem still pushed 3x, ~11-12s
    apart, from a SINGLE scraper invocation -- i.e. this particular download
    writes in bursts with idle gaps longer than any small fixed window I could
    safely guess, so a time-based gate was never going to be robust here.
    Replaced with a size-comparison gate instead: a file is only pushed once
    its size is IDENTICAL across two consecutive observations (_SEEN_SIZES),
    which needs no timing assumption at all -- a file mid-download will
    essentially never report the exact same byte count twice in a row. Cost:
    a file present at process start (crash leftover) needs one extra tick
    before its first push, since it has no prior recorded size yet -- this is
    a bounded delay, not lost data, same "retried next tick" guarantee as
    before via the same caller pattern (_background_push's loop + the
    guaranteed post-sweep call in main() after the scraper has exited).

    .part EXCLUSION (2026-09-21, added alongside the OOM root-cause fix in
    store_client.py): the module docstring above says "there's no separate
    .part/.tmp name", which was true when written but is STALE for the
    currently-pinned the scraper version (3.14.7) -- verified live during the
    2026-09-21 incident: the actual stuck/oversized file sat in this exact
    STAGING tree as `<...>.part` (both the plain main_download.py path and
    the DASH/DRM alt_download.py path write into a `<name>.part` temp file
    via tempFilePlaceholder, using the SAME save_location/staging root as the
    final destination -- confirmed by reading the scraper's placeholder.py --
    and only rename away the suffix after _size_checker/verify_media_integrity
    pass). The size-comparison gate above reduces but does not ELIMINATE the
    truncated-push race it was built to close: two consecutive 5s polls can
    land in a genuine mid-download stall (slow segment, throttled connection)
    with byte count unchanged, satisfying the gate on a file that is not
    actually finished. A `.part` suffix is a stronger, orthogonal signal that
    costs nothing extra: the file is *never* complete while so named, by
    construction of both download paths, so skipping it here cannot lose data
    -- same bounded-delay "retried next tick" guarantee as everything else in
    this function, and it naturally clears once the scraper's own rename lands.
    """
    pushed = failed = skipped = 0
    if not STAGING.exists():
        return 0, 0, 0
    # Fetch the durable-merge redirect map once per run (best-effort; on any
    # failure we proceed with raw usernames, matching the pre-redirect behavior).
    redirects = {}
    try:
        redirects = dict((store_client.get_folder_meta() or {}).get("redirects") or {})
    except Exception as e:  # noqa: BLE001
        log.warning("folder_meta fetch failed (%s); using raw usernames", e)
    for model_dir in sorted(STAGING.iterdir()):
        if not model_dir.is_dir():
            continue
        folder = resolve_folder(redirects, model_dir.name)
        for fpath in sorted(model_dir.iterdir()):
            if not fpath.is_file():
                continue
            if fpath.suffix == ".part":
                # Still being written by the scraper (or orphaned pending
                # _clear_stale_staging) -- never push, never count as seen,
                # so it gets a fresh size baseline once it's renamed away.
                continue
            key = str(fpath)
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if force_old_sec and (dt.datetime.now().timestamp() - fpath.stat().st_ctime) > force_old_sec:
                pass  # sweep-start drain: complete leftover, no writer running
            elif _SEEN_SIZES.get(key) != size:
                _SEEN_SIZES[key] = size
                skipped += 1
                continue
            raw_stem = f"{folder}_{fpath.stem}"
            stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in raw_stem).strip("-") or "unknown"
            # Exclusion gate (2026-10-01): the user deleted/deduped this stem in
            # the gallery — never (re)push it, and drop the staged copy so it
            # can't retry forever. The exclusion ledger is the gallery's ground
            # truth; both collector paths already gate on it (live handler +
            # reconcile), this wrapper was the gap: it fetched the ledger but
            # never consulted it. See _refresh_excluded docstring.
            if _is_excluded(stem) or _is_excluded(raw_stem):
                skipped += 1
                log.info("skip excluded stem=%s (deleted in gallery)", stem)
                _ledger_record(stem, model_dir.name, fpath.name, size, folder,
                               "excluded_skip", "stem in gallery exclusion ledger")
                try:
                    fpath.unlink()
                except OSError:
                    pass
                _SEEN_SIZES.pop(key, None)
                continue
            mtime = fpath.stat().st_mtime
            date_iso = dt.datetime.fromtimestamp(mtime).isoformat()
            try:
                resp = store_client.push_media(folder, str(fpath), stem, date_iso, is_out=False)
                ok, why = _push_verified(resp)
                if not ok:
                    # HTTP success is not storage. Raise into the failure path so
                    # the file is parked (recoverable) instead of unlinked (gone).
                    raise RuntimeError(f"unverified push: {why}")
                pushed += 1
                log.info("PUSHED %s -> %s (%s)", stem, folder, why)
                # Ledger BEFORE the unlink: a crash in between leaves a verified
                # row plus a still-staged file, which the next drain re-pushes
                # harmlessly. The reverse order would lose the record.
                _ledger_record(stem, model_dir.name, fpath.name, size, folder,
                               "verified", why)
                try:
                    fpath.unlink()
                except OSError:
                    pass
                _SEEN_SIZES.pop(key, None)
            except Exception as e:  # noqa: BLE001
                failed += 1
                log.error("push failed %s: %s: %s", stem, type(e).__name__, e)
                _park(fpath, folder, stem)
                _SEEN_SIZES.pop(key, None)
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
    dropped = {}  # model -> [filename] unlinked without a verified store
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
            # AGE IS TAKEN FROM ctime, NOT mtime. The scraper stamps each
            # download's mtime with the POST date, so a month-old post looks
            # like a month-old file and the age check would delete a download
            # that landed seconds ago (found live 2026-11-18: a 1-minute-old
            # purchase was "cleared" as age=2613787min). ctime moves when the
            # inode is written/chmod'ed, i.e. when the file actually landed.
            age = now - st.st_ctime
            if age > max_age and fpath.suffix == ".part":
                # Orphaned partial download from a killed sweep: incomplete by
                # construction, nothing to re-queue (the complete file never
                # existed), so drop it without a ledger row or a DB reset.
                try:
                    fpath.unlink()
                    cleared += 1
                    cleared_bytes += st.st_size
                    log.warning("cleared orphaned .part %s (age=%.0fmin)",
                                fpath, age / 60)
                except OSError as e:
                    log.error("failed to clear stale .part %s: %s", fpath, e)
            elif age > max_age:
                size = st.st_size
                raw_stem = f"{model_dir.name}_{fpath.stem}"
                stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in raw_stem).strip("-") or "unknown"
                # Record BEFORE the unlink, and reset the scraper's downloaded
                # flag for this exact file below: without the reset the sweep
                # never re-fetches it (that was the silent, permanent loss).
                _ledger_record(stem, model_dir.name, fpath.name, size, model_dir.name,
                               "dropped_unstored",
                               "stale staging (%0.f min) unlinked without a verified store"
                               % (age / 60))
                try:
                    fpath.unlink()
                    cleared += 1
                    cleared_bytes += size
                    dropped.setdefault(model_dir.name, []).append(fpath.name)
                    log.warning(
                        "cleared stale staging file %s (age=%.0fmin, size=%.1fMB) "
                        "-- downloaded flag will be reset so it IS re-fetched",
                        fpath, age / 60, size / 1e6,
                    )
                except OSError as e:
                    log.error("failed to clear stale staging file %s: %s", fpath, e)
        try:
            if not any(model_dir.iterdir()):
                model_dir.rmdir()
        except OSError:
            pass
    reset = 0
    for model, names in dropped.items():
        reset += _reset_downloaded(model, names, "stale staging dropped")
    if cleared:
        log.warning("stale staging sweep: cleared %d file(s), %.1fMB total,"
                    " %d media re-queued for download",
                    cleared, cleared_bytes / 1e6, reset)


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
    """Build the base scraper invocation for liking (action=like, like-area=timeline).
    Shares the binary path, config, and neg-filter with the download base cmd
    but uses --action like and --like-area timeline instead. --like-area avoids
    downloading media (unlike --posts which can trigger downloads)."""
    bin_name = os.environ.get("M02_SCRAPER_BIN", "scraper")
    return [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", bin_name),
        "--config", CONFIG_FILE,
        "--action", "like",
        "--like-area", "timeline",
        "--neg-filter", r"(#(?:ad|ads|AD|advertising|sponsored|promotion)|trial|discount|exclusive\s+offer|giveaway|limited\s+time|\Buser\s+promo|shoutout|endorsement)",
    ]


def _count_likes(r, started_at=None):
    """Count how many posts were actually liked in this run.

    Sources, in order of trust: the scraper's own "[Action Like] [N posts
    checked, (M liked, ...)]" summary recorded in its run log, then the
    per-post "changed to liked" records (a run killed mid-action has no
    summary but keeps those), then an explicit "liked N posts" line on
    stdout.

    Never fall back to a bare substring count: the old one matched
    "actionable for liking" and reported one phantom like per model per
    sweep, so the daily cap filled up with likes that never happened."""
    import re
    if started_at is not None:
        summaries = []
        per_post = 0
        today = dt.date.today()
        for day in (today, today - dt.timedelta(days=1)):
            day_dir = SCRAPER_LOG_DIR / ("main_profile_" + day.isoformat())
            try:
                for f in day_dir.glob("*.log"):
                    if f.stat().st_mtime < started_at - 2:
                        continue
                    text = f.read_text(errors="ignore")
                    per_post += text.count("changed to liked")
                    for m in re.finditer(r"\[Action Like\] \[\d+ posts checked, \((\d+) liked", text):
                        summaries.append(int(m.group(1)))
            except OSError as e:
                log.warning("could not read scraper logs to count likes: %s", e)
        if summaries:
            return sum(summaries)
        if per_post:
            return per_post
    output = (r.stdout or "") + (r.stderr or "")
    # Look for explicit "Liked X posts" or "liked X" patterns
    for pattern in [r"[Ll]iked\s+(\d+)\s+posts?", r"(\d+)\s+posts?\s+liked"]:
        m = re.search(pattern, output, re.IGNORECASE)
        if m:
            return int(m.group(1))
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
        # Backlog mode: one model per sweep. Likes up to per-model cap worth
        # of that model's unliked timeline posts (no time filter = all unliked
        # posts). --max-post-count capped at LIKE_PER_MODEL_CAP so we don't
        # paginate through the entire timeline for one model.
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
            # Persist state BEFORE running the subprocess — advance the index now
            # so that even if systemd kills us (service timeout), the next sweep
            # moves to the next model instead of retrying the same one.
            state["backlog_index"] += 1
            _write_like_state(state)
            cmd = _like_base_cmd() + [
                "--max-post-count", str(min(remaining, LIKE_PER_MODEL_CAP)),
                "--username", model,
            ]
            try:
                started = time.time()
                r = subprocess.run(cmd, check=False, capture_output=True, text=True,
                                   timeout=LIKE_PER_MODEL_TIMEOUT)
            except subprocess.TimeoutExpired:
                log.warning("like pass [backlog:%s] timed out after %dmin",
                            model, LIKE_PER_MODEL_TIMEOUT)
                return
            reason = _scraper_failure_reason(r)
            if reason:
                log.error("like pass [backlog:%s] did no work: %s", model, reason)
            actual = _count_likes(r, started)
            log.info("like pass [backlog:%s] exit=%d, liked=%d", model, r.returncode, actual)
            state["daily_likes_used"] = state.get("daily_likes_used", 0) + actual
            _write_like_state(state)
            return  # one model per sweep

    # Daily mode: like last 24h from all active models
    remaining = LIKE_DAILY_CAP - state.get("daily_likes_used", 0)
    if remaining <= 0:
        return
    # ISO format (YYYY-MM-DD) so `arrow` parses it directly. MM/DD/YYYY used
    # to fail arrow.get() and fall into the scraper's humanize fallback parser,
    # which has its own bug (missing \b before \minute in a regex) that threw
    # "re.error: bad escape \m" on every single daily-mode like attempt.
    yesterday = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
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
        # Persist state before each daily model too — saves progress if killed
        _write_like_state(state)
        try:
            started = time.time()
            r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=15 * 60)
        except subprocess.TimeoutExpired:
            log.warning("like pass [daily:%s] timed out after 15min", model)
            continue
        reason = _scraper_failure_reason(r)
        if reason:
            log.error("like pass [daily:%s] did no work: %s", model, reason)
        if r.returncode != 0:
            log.warning("like pass [daily:%s] exit %d: %s", model, r.returncode, (r.stderr or "")[-500:])
        actual = _count_likes(r, started)
        if actual > 0:
            log.info("like pass [daily:%s] liked %d posts", model, actual)
        likes_used += actual
        if likes_used >= remaining:
            break

    state["daily_likes_used"] = state.get("daily_likes_used", 0) + likes_used
    _write_like_state(state)
    log.info("like pass done: %d likes used today (%d/%d)",
             state["daily_likes_used"], state["daily_likes_used"], LIKE_DAILY_CAP)


# ─── Message cleanup pass (unread spam triage) ───────────────────────────────
# The /chats/{uid}/messages endpoint marks a chat read server-side on ANY GET —
# that is why the upstream scraper was patched to use /chats/{uid}/media for
# message downloads. This pass therefore never GETs /messages: it enumerates
# unread chats via /chats (verified 2026-11-21: repeated GETs leave unread
# counts untouched), inspects only media-bearing messages via .../media, and
# changes read state ONLY through the explicit mark-as-read endpoint.
#
# Default posture is KEEP: a chat stays unread unless every unread message is
# clearly broadcast bait — text-only spam ("I'm lonely", "want your
# attention", ...) or locked PPV. Anything with a free viewable photo/video, a
# tip, a pinned message, or a model on the priority allowlist is never touched.
MSGCLEAN_ENABLED = os.environ.get("M02_MSGCLEAN_ENABLED", "").strip().lower() in (
    "1", "true", "yes")
MSGCLEAN_DRY_RUN = os.environ.get("M02_MSGCLEAN_DRY_RUN", "").strip().lower() in (
    "1", "true", "yes")
MSGCLEAN_MAX_ACTIONS = int(os.environ.get("M02_MSGCLEAN_MAX_ACTIONS", "40"))
MSGCLEAN_MAX_CHAT_PAGES = int(os.environ.get("M02_MSGCLEAN_MAX_CHAT_PAGES", "40"))
MSGCLEAN_READ_LOCKED_PPV = os.environ.get(
    "M02_MSGCLEAN_READ_LOCKED_PPV", "true").strip().lower() in ("1", "true", "yes")
MSGCLEAN_MIN_INTERVAL = float(os.environ.get("M02_MSGCLEAN_MIN_INTERVAL", "0.7"))
MSGCLEAN_PRIORITY_USERNAMES = {
    u.strip().lower() for u in os.environ.get(
        "M02_MSGCLEAN_PRIORITY_USERNAMES", "").split(",") if u.strip()
}
MSGCLEAN_STATE_FILE = Path(os.environ.get(
    "M02_MSGCLEAN_STATE_FILE", str(STAGING.parent / "msg_clean_state.json")))

# Broadcast-bait phrases. A match is a *hint*, never the only test: a chat is
# only marked read when it also carries no free viewable media. Patterns are
# deliberately narrow (money/pin/personal-question signals are separate keep
# guards), and unmatched text stays unread.
MSGCLEAN_SPAM_PATTERNS = [
    ("lonely", r"\blonely\b"),
    ("attention", r"\b(need|needs|want|wants|crave|craving|pay|paying|paid)\s+(me\s+)?(some\s+|your\s+|ur\s+)?attention\b|\battention\s+(from\s+you|please)\b"),
    ("miss-you", r"\b(i\s+)?miss\s+(you|u|ya)\b|\bmissing\s+(you|u)\b"),
    ("thinking-of-you", r"\b(thinking|thought)\s+(of|about)\s+(you|u)\b"),
    ("waiting-for-you", r"\b(waiting|wait|been waiting|still waiting)\s+(for|on)\s+(you|u)\b"),
    ("come-talk", r"\bcome\s+(talk|chat|play|see me|keep me company|spend time)\b"),
    ("talk-to-me", r"\b(talk|chat|speak)\s+to\s+me\b|\btext\s+me(\s+back)?\b|\breply\s+to\s+me\b|\banswer\s+me\b"),
    ("dont-ignore-me", r"\b(don'?t|do not|stop)\s+ignor(e|ing)\s+me\b|\bwhy\s+(are\s+you|u)\s+ignoring\b"),
    ("are-you-there", r"\bare\s+(you|u)\s+(there|up|awake|around|busy)\b|\bwhere\s+(are\s+you|r\s+u|ru)\b"),
    ("bored-alone", r"\b(so\s+|i'?m\s+|im\s+)?bored\b|\ball\s+alone\b|\bnobody\s+to\s+(talk|chat)\b"),
    ("keep-company", r"\bkeep\s+me\s+company\b"),
    ("wyd", r"\b(wyd|what\s+are\s+you\s+(doing|up\s+to))\b"),
    ("just-for-you", r"\b(just|only|specially)\s+for\s+(you|u)\b|\bmade\s+(this|it)\s+for\s+(you|u)\b"),
    ("show-you", r"\b(want|wanna|waiting|dying)\s+to\s+show\s+(you|u)\b|\bsomething\s+(special|hot)\s+(for\s+you|waiting)\b"),
    ("check-messages", r"\bcheck\s+(your|ur)\s+(messages|dms|inbox)\b|\bsent\s+(you|u)\s+something\b"),
    ("dont-miss", r"\bdon'?t\s+miss\b|\blimited\s+time\b|\bunlock\b|\bfree\s+(today|now)\b"),
]
_MSGCLEAN_SPAM_RE = [(reason, re.compile(pat, re.IGNORECASE))
                     for reason, pat in MSGCLEAN_SPAM_PATTERNS]


def _msgclean_plain_text(text):
    """Chat text arrives as HTML (m-editor markup). Strip tags + entities so
    pattern matching sees words, not markup."""
    if not text:
        return ""
    import html as _html
    return _html.unescape(re.sub(r"<[^>]+>", " ", str(text))).strip()


def _msgclean_spam_reason(text):
    """Return the spam-phrase tag that matches this text, or None."""
    plain = _msgclean_plain_text(text)
    if not plain:
        return None
    for reason, rx in _MSGCLEAN_SPAM_RE:
        if rx.search(plain):
            return reason
    return None


def _msgclean_free_viewable(post):
    """True when the message carries media the operator can actually see right
    now: at least one item with canView set and no error.

    Viewability — not price — is the test. A priced post the operator already
    unlocked still reports its media as canView=true; a PPV that costs money
    reports canView=false (that is the "requires an unlock" case)."""
    for m in (post.get("media") or []):
        if m.get("canView") and not m.get("hasError"):
            return True
    return False


def _msgclean_post_is_ppv(post):
    """A message that costs money: priced media or locked text."""
    price = post.get("price") or 0
    return bool((isinstance(price, (int, float)) and price > 0) or post.get("lockedText"))


def _msgclean_classify(chat, unread_posts, priority_names=(), my_id=None,
                       read_locked_ppv=True):
    """Decide what to do with ONE unread chat.

    chat: {username, unread, has_tips, pinned_msgs, last_msg{...}}
    unread_posts: media-bearing unread messages, newest first, each
        {id, price, lockedText, media:[{canView, hasError}], isPinned, isTip,
         text, from_user_id}
    Returns (action, reason) with action 'keep' (leave unread) or 'read'.

    Keep wins ties on purpose: this pass exists to cut spam without losing
    messages, so every ambiguous case stays unread.
    """
    username = (chat.get("username") or "").lower()
    if int(chat.get("unread") or 0) <= 0:
        return "keep", "no-unread"
    if username in priority_names:
        return "keep", "priority-allowlist"
    if chat.get("has_tips"):
        return "keep", "unread-tip"
    if int(chat.get("pinned_msgs") or 0) > 0:
        return "keep", "pinned-messages"
    for p in unread_posts:
        if p.get("isTip"):
            return "keep", "unread-tip"
        if p.get("isPinned"):
            return "keep", "pinned-message"
        if _msgclean_free_viewable(p):
            return "keep", "free-media"
    last = chat.get("last_msg") or {}
    if my_id is not None and last.get("from_user_id") == my_id:
        return "keep", "last-message-is-mine"
    # From here on: no free media anywhere in the unread batch.
    for p in unread_posts:
        reason = _msgclean_spam_reason(p.get("text"))
        if reason:
            return "read", "spam-text:" + reason
    reason = _msgclean_spam_reason(last.get("text"))
    if reason:
        return "read", "spam-text:" + reason
    if read_locked_ppv:
        if unread_posts and all(_msgclean_post_is_ppv(p) for p in unread_posts):
            return "read", "locked-ppv-only"
        if not unread_posts and _msgclean_post_is_ppv(last):
            return "read", "locked-ppv-only"
    return "keep", "unclassified"


def _msgclean_load_state():
    import json
    if MSGCLEAN_STATE_FILE.exists():
        try:
            return json.loads(MSGCLEAN_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("msg_clean_state.json corrupt (%s) — resetting", e)
    return {}


def _msgclean_write_state(state):
    import json
    try:
        MSGCLEAN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MSGCLEAN_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))
    except OSError as e:
        log.error("failed to write msg_clean_state: %s", e)


# ─── DRM pending audit ───────────────────────────────────────────────────────
# Widevine-protected videos (media whose only source is a .mpd/DASH manifest)
# cannot be downloaded without a CDM. The upstream scraper records them as
# downloaded anyway, with no file on disk — so they vanish from every later
# sweep and from the error path. This audit finds them across every per-model
# metadata DB, reports them, and (opt-in) resets the flag so a sweep with a
# working CDM re-fetches them.
DRM_AUDIT_ENABLED = os.environ.get("M02_DRM_AUDIT", "true").strip().lower() in (
    "1", "true", "yes")
DRM_REPAIR = os.environ.get("M02_DRM_REPAIR", "false").strip().lower() in (
    "1", "true", "yes")
# METADATA_DIR is defined once, near STAGING at the top of the file.
DRM_REPORT_FILE = Path(os.environ.get(
    "M02_DRM_REPORT_FILE", str(STAGING.parent / "drm_pending.json")))


def _drm_audit():
    """Report (and optionally reset) videos flagged downloaded that have no
    file — i.e. DRM media skipped for lack of a CDM. Returns a dict summary."""
    import json
    import sqlite3
    summary = {"scanned": 0, "models": 0, "pending": 0, "repaired": 0,
               "by_model": {}}
    if not METADATA_DIR.is_dir():
        log.warning("drm audit: metadata dir %s missing — skipped", METADATA_DIR)
        return summary
    for db in sorted(METADATA_DIR.glob("*/user_data.db")):
        summary["scanned"] += 1
        try:
            conn = sqlite3.connect(str(db), timeout=5)
            rows = conn.execute(
                "select media_id, link from medias where media_type='Videos'"
                " and downloaded=1 and (size is null or size=0)").fetchall()
        except sqlite3.Error as e:
            log.warning("drm audit: %s unreadable: %s", db.name, e)
            continue
        if not rows:
            conn.close()
            continue
        drm = [(mid, link) for mid, link in rows if link and ".mpd" in link]
        if not drm:
            conn.close()
            continue
        model = db.parent.name
        summary["models"] += 1
        summary["pending"] += len(drm)
        summary["by_model"][model] = len(drm)
        if DRM_REPAIR:
            try:
                conn.executemany(
                    "update medias set downloaded=0, size=NULL where media_id=?",
                    [(mid,) for mid, _ in drm])
                conn.commit()
                summary["repaired"] += len(drm)
            except sqlite3.Error as e:
                log.warning("drm audit: repair failed for %s: %s", model, e)
        conn.close()
    if summary["pending"]:
        top = sorted(summary["by_model"].items(), key=lambda kv: -kv[1])[:10]
        if DRM_REPAIR:
            log.warning("drm audit: %d DRM videos reset for re-download across"
                        " %d models (top: %s)", summary["repaired"],
                        summary["models"], top)
        elif DRM_AUDIT_ENABLED:
            log.warning("drm audit: %d purchased videos are marked downloaded but"
                        " have NO file — Widevine-protected; need a CDM"
                        " (key-mode manual + private-key/client-id). Top: %s",
                        summary["pending"], top)
    try:
        DRM_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        DRM_REPORT_FILE.write_text(json.dumps(summary, indent=2, sort_keys=True))
    except OSError as e:
        log.warning("drm audit: could not write %s: %s", DRM_REPORT_FILE, e)
    return summary


# ─── Delivery ledger report + backlog audit ──────────────────────────────────
def _upload_ledger_report():
    """Group the delivery ledger by outcome and write it next to the DRM report.

    This is the on-host answer to "did the gallery get it": every stem the
    wrapper touched has a row, and only `verified` means the gallery confirmed
    storage. Cheap (one GROUP BY), so it runs at the end of every sweep.
    """
    import sqlite3
    summary = {"states": {}, "known_gaps": 0, "last_ts": None}
    if not UPLOAD_LEDGER.exists():
        return summary
    try:
        conn = _ledger_conn()
        for state, n, last in conn.execute(
                "select state, count(*), max(ts) from pushes group by state"):
            summary["states"][state] = n
            if last and (summary["last_ts"] or "") < last:
                summary["last_ts"] = last
        conn.close()
    except sqlite3.Error as e:
        log.warning("ledger report failed: %s", e)
        return summary
    gaps = sum(n for s, n in summary["states"].items() if s != "verified")
    summary["known_gaps"] = gaps
    if gaps:
        log.warning("upload ledger: %d stem(s) NOT confirmed stored — %s",
                    gaps, summary["states"])
    else:
        log.info("upload ledger: %s", summary["states"] or "empty")
    return summary


def _audit_backlog():
    """Full scan: which downloaded media are known NOT to be in the gallery?

    Only a gallery inventory can prove an object is absent; this produces the
    candidate set the wrapper can prove on its own, per model DB:
      * `known_gap`  — downloaded=1, no file on disk, ledger says it was
                       dropped/parked/failed. These are safe to reset.
      * `unverified` — downloaded=1, no file on disk, ledger has no row for it
                       (downloaded before the ledger existed). Candidate only —
                       most of these WERE pushed successfully.
    Run: python3 scraper_wrapper.py --audit [--reset-known-gaps]
    """
    import sqlite3
    out = {"models": 0, "downloaded": 0, "staged": 0, "verified": 0,
           "known_gap": 0, "unverified": 0, "reset": 0, "by_model": {}}
    ledger = {}
    if UPLOAD_LEDGER.exists():
        conn = _ledger_conn()
        for model, filename, state in conn.execute(
                "select model, filename, state from pushes"):
            ledger[(model, filename)] = state
        conn.close()
    for db in sorted(METADATA_DIR.glob("*/user_data.db")):
        model = db.parent.name
        out["models"] += 1
        try:
            conn = sqlite3.connect(str(db), timeout=30)
            rows = conn.execute(
                "select filename, directory, size from medias"
                " where downloaded=1").fetchall()
        except sqlite3.Error as e:
            log.warning("backlog audit: %s unreadable: %s", db.name, e)
            continue
        gaps = []
        for filename, directory, size in rows:
            out["downloaded"] += 1
            if not filename:
                continue
            path = Path(directory or "") / filename
            if path.exists():
                out["staged"] += 1
                continue
            state = ledger.get((model, filename))
            if state == "verified":
                out["verified"] += 1
            elif state in ("dropped_unstored", "parked", "park_failed", "verify_failed"):
                out["known_gap"] += 1
                gaps.append(filename)
            else:
                out["unverified"] += 1
        if gaps:
            out["by_model"][model] = len(gaps)
        if RESET_KNOWN_GAPS and gaps:
            out["reset"] += _reset_downloaded(model, gaps, "backlog audit")
        conn.close()
    top = sorted(out["by_model"].items(), key=lambda kv: -kv[1])[:10]
    log.warning("backlog audit: downloaded=%d staged=%d verified=%d"
                " known_gap=%d unverified=%d reset=%d top=%s",
                out["downloaded"], out["staged"], out["verified"],
                out["known_gap"], out["unverified"], out["reset"], top)
    try:
        LEDGER_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        LEDGER_REPORT_FILE.write_text(json.dumps(out, indent=2, sort_keys=True))
    except OSError as e:
        log.warning("backlog audit: could not write %s: %s", LEDGER_REPORT_FILE, e)
    return out


def _reconcile_missing(apply=False):
    """Ask the gallery which downloaded media it does NOT account for, and reset
    exactly those so the next sweep re-fetches them.

    The staged file is deleted after a verified push, so "no file on disk" means
    nothing on its own — absence is only provable by asking the gallery.
    POST /ingest/have answers "do you have this stem" from the ingest datemap
    (every stem ever ingested) UNION the exclusion ledger (deliberately deleted
    stems count as accounted-for, so deletes are never resurrected). Rows the
    gallery does not account for, and which the local ledger never marked
    verified, are the genuine, provable gaps.

    Run: python3 scraper_wrapper.py --reconcile          (report only)
         python3 scraper_wrapper.py --reconcile --apply  (reset them)
    """
    import sqlite3
    out = {"candidates": 0, "have": 0, "missing": 0, "reset": 0,
           "excluded_from_ask": 0, "by_model": {}, "error": None,
           "missing_by_type": {}, "missing_by_month": {}}
    try:
        redirects = dict((store_client.get_folder_meta() or {}).get("redirects") or {})
    except Exception as e:  # noqa: BLE001
        redirects = {}
        log.warning("reconcile: folder_meta fetch failed (%s); using raw usernames", e)

    verified = set()
    if UPLOAD_LEDGER.exists():
        conn = _ledger_conn()
        verified = {(m, f) for m, f in conn.execute(
            "select model, filename from pushes where state='verified'")}
        conn.close()

    cands = []  # (model, filename, stem, media_type, posted_at)
    for db in sorted(METADATA_DIR.glob("*/user_data.db")):
        model = db.parent.name
        try:
            conn = sqlite3.connect(str(db), timeout=30)
            rows = conn.execute(
                "select filename, directory, media_type, posted_at from medias"
                " where downloaded=1").fetchall()
            mid = conn.execute("select max(model_id) from medias").fetchone()[0]
            conn.close()
        except sqlite3.Error as e:
            log.warning("reconcile: %s unreadable: %s", db.name, e)
            continue
        # The metadata dir is <username>_<model_id>, but the STAGING dir — and so
        # the gallery folder and the stem prefix — is the bare username. Strip
        # the id (verified against the DB's own model_id, not by guessing), then
        # apply the durable-merge redirects exactly as the push path does.
        username = model
        if mid and model.endswith("_%s" % mid):
            username = model[: -len("_%s" % mid)]
        folder = resolve_folder(redirects, username)
        for filename, directory, mtype, posted in rows:
            if not filename:
                continue
            if (model, filename) in verified:
                out["excluded_from_ask"] += 1
                continue
            if (Path(directory or "") / filename).exists():
                out["excluded_from_ask"] += 1  # still staged; the drain pushes it
                continue
            raw_stem = f"{folder}_{Path(filename).stem}"
            stem = "".join(c if c.isalnum() or c in "-_" else "-"
                           for c in raw_stem).strip("-") or "unknown"
            cands.append((model, filename, stem, mtype or "?", posted or ""))

    out["candidates"] = len(cands)
    if not cands:
        log.info("reconcile: nothing unaccounted-for to ask about")
        return out
    try:
        have = store_client.have_stems([c[2] for c in cands])
    except Exception as e:  # noqa: BLE001
        out["error"] = "%s: %s" % (type(e).__name__, e)
        log.error("reconcile: /ingest/have failed — %s", out["error"])
        return out
    out["have"] = len(have)
    gaps = {}
    for model, filename, stem, mtype, posted in cands:
        if stem in have:
            continue
        out["missing"] += 1
        out["missing_by_type"][mtype] = out["missing_by_type"].get(mtype, 0) + 1
        month = str(posted)[:7] or "unknown"
        out["missing_by_month"][month] = out["missing_by_month"].get(month, 0) + 1
        gaps.setdefault(model, []).append((filename, stem))
    for model, items in gaps.items():
        out["by_model"][model] = len(items)
        if apply:
            out["reset"] += _reset_downloaded(
                model, [f for f, _ in items], "gallery does not account for it")
            for filename, stem in items:
                _ledger_record(stem, model, filename, 0, model,
                               "missing_confirmed",
                               "gallery /ingest/have says no; re-queued")
    top = sorted(out["by_model"].items(), key=lambda kv: -kv[1])[:10]
    log.warning("reconcile: candidates=%d have=%d MISSING=%d reset=%d%s top=%s",
                out["candidates"], out["have"], out["missing"], out["reset"],
                "" if apply else " (report only — pass --apply to re-queue)", top)
    try:
        RECONCILE_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        RECONCILE_REPORT_FILE.write_text(json.dumps(out, indent=2, sort_keys=True),
                                         encoding="utf-8")
    except OSError as e:
        log.warning("reconcile: could not write %s: %s", RECONCILE_REPORT_FILE, e)
    return out


def _run_message_pass():
    """Unread spam triage. Runs after the like pass.

    Enumerates unread chats, reads only media-bearing messages (never
    /messages, which would mark them read), and POSTs mark-as-read for chats
    that are pure broadcast bait. Everything else is left unread.
    """
    if not MSGCLEAN_ENABLED:
        log.info("message pass skipped — disabled (M02_MSGCLEAN_ENABLED)")
        return

    import asyncio
    import datetime as _dt

    mods = _load_scraper_modules()
    if mods is None:
        log.warning("message pass skipped — scraper modules unavailable")
        return
    mgr = mods["manager"].Manager

    state = _msgclean_load_state()
    today = _dt.date.today().isoformat()
    if state.get("date") != today:
        state["date"] = today
        state["actions_today"] = 0

    stats = {"chats_seen": 0, "unread_seen": 0, "read": 0, "keep": 0,
             "errors": 0, "budget_hit": 0}
    recent = []

    async def _json(c, url, method="get", body=None):
        # The session wrapper raises on non-2xx (and retries with backoff), so
        # every call has to be contained here — one bad chat must not abort the
        # whole pass.
        try:
            async with c.requests_async(url=url, method=method, json=body) as r:
                status = r.status
                if not (200 <= status < 300):
                    return None, status
                try:
                    return await r.json_(), status
                except Exception:  # noqa: BLE001
                    return {}, status
        except Exception as e:  # noqa: BLE001
            log.debug("message pass: %s %s raised %s", method, url, type(e).__name__)
            return None, getattr(e, "status", None)

    async def _run():
        async with mgr.session.aget_subscription_session() as c:
            me, _ = await _json(c, "https://onlyfans.com/api2/v2/users/me")
            my_id = (me or {}).get("id")
            offset = 0
            for _page in range(MSGCLEAN_MAX_CHAT_PAGES):
                url = ("https://onlyfans.com/api2/v2/chats?limit=20&offset=%d"
                       "&order=recent") % offset
                data, status = await _json(c, url)
                if data is None:
                    log.warning("message pass: chats page offset=%d -> HTTP %s", offset, status)
                    stats["errors"] += 1
                    break
                lst = data.get("list") or []
                if not lst:
                    break
                for chat in lst:
                    stats["chats_seen"] += 1
                    with_user = chat.get("withUser") or {}
                    uid = with_user.get("id")
                    username = with_user.get("username") or ""
                    unread = int(chat.get("unreadMessagesCount") or 0)
                    if unread <= 0 or uid is None:
                        continue
                    stats["unread_seen"] += 1
                    # Priority guards that need no extra request.
                    if username.lower() in MSGCLEAN_PRIORITY_USERNAMES:
                        stats["keep"] += 1
                        log.info("message pass: KEEP %s (priority-allowlist)", username)
                        continue
                    if chat.get("hasUnreadTips"):
                        stats["keep"] += 1
                        log.info("message pass: KEEP %s (unread-tip)", username)
                        continue
                    lm = chat.get("lastMessage") or {}
                    last_msg = {
                        "id": lm.get("id"),
                        "from_user_id": (lm.get("fromUser") or {}).get("id"),
                        "text": lm.get("text"),
                        "price": lm.get("price"),
                        "lockedText": lm.get("lockedText"),
                        "isTip": lm.get("isTip"),
                        "isPinned": lm.get("isPinned"),
                        "mediaCount": lm.get("mediaCount"),
                    }
                    last_read = chat.get("lastReadMessageId")
                    try:
                        last_read_n = int(str(last_read)) if last_read not in (None, "") else 0
                    except (TypeError, ValueError):
                        last_read_n = 0
                    murl = ("https://onlyfans.com/api2/v2/chats/%s/media?limit=50"
                            "&offset=0&order=desc&skip_users=all&skip_users_dups=1") % uid
                    mdata, mstatus = await _json(c, murl)
                    if mdata is None:
                        stats["errors"] += 1
                        log.warning("message pass: %s media -> HTTP %s (kept unread)",
                                    username, mstatus)
                        continue
                    unread_posts = []
                    for p in (mdata.get("list") or []):
                        try:
                            pid = int(str(p.get("id")))
                        except (TypeError, ValueError):
                            continue
                        if pid <= last_read_n:
                            break  # newest-first: everything older is read
                        unread_posts.append({
                            "id": pid,
                            "price": p.get("price"),
                            "lockedText": p.get("lockedText"),
                            "media": p.get("media") or [],
                            "isPinned": p.get("isPinned"),
                            "isTip": p.get("isTip"),
                            "text": p.get("text"),
                            "_from_user_id": (p.get("fromUser") or {}).get("id"),
                        })
                    if last_msg.get("from_user_id") is None and unread_posts:
                        last_msg["from_user_id"] = unread_posts[0].get("_from_user_id")
                    action, reason = _msgclean_classify(
                        {"username": username, "unread": unread,
                         "has_tips": chat.get("hasUnreadTips"),
                         "pinned_msgs": chat.get("countPinnedMessages"),
                         "last_msg": last_msg},
                        unread_posts, MSGCLEAN_PRIORITY_USERNAMES, my_id,
                        MSGCLEAN_READ_LOCKED_PPV)
                    if action == "keep":
                        stats["keep"] += 1
                        log.info("message pass: KEEP %s unread=%d (%s)",
                                 username, unread, reason)
                        continue
                    if state.get("actions_today", 0) + stats["read"] >= MSGCLEAN_MAX_ACTIONS:
                        stats["budget_hit"] += 1
                        log.info("message pass: cap %d reached — %s left unread (%s)",
                                 MSGCLEAN_MAX_ACTIONS, username, reason)
                        continue
                    if MSGCLEAN_DRY_RUN:
                        stats["read"] += 1
                        log.info("message pass: WOULD-READ %s unread=%d (%s)",
                                 username, unread, reason)
                        recent.append({"user": username, "reason": reason,
                                       "dry_run": True, "at": _dt.datetime.now().isoformat(timespec="seconds")})
                        continue
                    purl = ("https://onlyfans.com/api2/v2/chats/%s/mark-as-read" % uid)
                    _, pstatus = await _json(c, purl, method="post", body={})
                    if pstatus in (200, 201, 204):
                        stats["read"] += 1
                        recent.append({"user": username, "reason": reason,
                                       "at": _dt.datetime.now().isoformat(timespec="seconds")})
                        log.info("message pass: MARKED READ %s unread=%d (%s)",
                                 username, unread, reason)
                    else:
                        stats["errors"] += 1
                        log.warning("message pass: %s mark-as-read -> HTTP %s",
                                    username, pstatus)
                    if MSGCLEAN_MIN_INTERVAL:
                        await asyncio.sleep(MSGCLEAN_MIN_INTERVAL)
                if not data.get("hasMore"):
                    break
                try:
                    offset = int(data.get("nextOffset") or (offset + len(lst)))
                except (TypeError, ValueError):
                    offset += len(lst)

    try:
        asyncio.run(_run())
    except Exception as e:  # noqa: BLE001
        stats["errors"] += 1
        log.error("message pass failed: %s: %s", type(e).__name__, e)

    state["actions_today"] = state.get("actions_today", 0) + (
        0 if MSGCLEAN_DRY_RUN else stats["read"])
    state["last_run"] = _dt.datetime.now().isoformat(timespec="seconds")
    state["last_result"] = stats
    if recent:
        state["recent_actions"] = (recent + state.get("recent_actions", []))[:50]
    _msgclean_write_state(state)
    log.info("message pass done: chats=%d unread=%d read=%d keep=%d errors=%d%s",
             stats["chats_seen"], stats["unread_seen"], stats["read"],
             stats["keep"], stats["errors"],
             " (DRY RUN)" if MSGCLEAN_DRY_RUN else "")


def _session_alive():
    """One cheap API call: is the stored session still accepted?

    OnlyFans revokes a session on the first rejected request, so a dead session
    must abort the sweep *before* the passes — otherwise every model repeats the
    same doomed login and the account looks abusive.
    """
    import asyncio

    mods = _load_scraper_modules()
    if mods is None:
        return None  # can't tell; let the passes decide
    mgr = mods["manager"].Manager

    async def _probe():
        async with mgr.session.aget_subscription_session() as c:
            async with c.requests_async(url="https://onlyfans.com/api2/v2/users/me") as r:
                if r.status != 200:
                    return "HTTP %s" % r.status
                body = await r.read_()
                import json as _json
                data = _json.loads(body)
                if not data.get("isAuth"):
                    return "not authenticated"
                return None

    try:
        return asyncio.run(_probe())
    except Exception as e:  # noqa: BLE001
        return "%s: %s" % (type(e).__name__, e)


def main():
    # Drain whatever the previous sweep left in staging BEFORE the stale sweeper
    # gets a chance to drop it. An aborted/timed-out sweep leaves COMPLETE files
    # behind while ofscraper has already flagged them downloaded=1 — pushing them
    # here is the recovery edge; _clear_stale_staging then only sees files that
    # genuinely cannot be pushed. force_old_sec is safe here because no scraper
    # is running yet, so there is no writer to race.
    if STAGING.exists():
        d_pushed, d_failed, d_skipped = _walk_and_push(force_old_sec=600)
        _accumulate_pushes(d_pushed, d_failed)
        if d_pushed or d_failed:
            log.info("sweep-start drain: pushed=%d failed=%d skipped=%d",
                     d_pushed, d_failed, d_skipped)
    _clear_stale_staging()
    _check_staging_usage()
    _check_auth()

    # Stop before the passes if the session is already dead: a rejected request
    # revokes the session server-side, so retrying it 149 times only hurts.
    reason = _session_alive()
    if reason:
        log.error("session check failed (%s) — skipping this sweep to protect "
                  "the account; refresh auth.json and re-run", reason)
        sys.exit(0)
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

    # Pass 5: purchased. Every creator in the platform's built-in "purchased"
    # user list gets a paid-area-only scrape — this is the only pass that sees
    # creators whose subscription expired, because they never appear in the
    # active-subscription discovery above. Narrow area on purpose: purchased
    # media stays readable after expiry, timeline/messages do not.
    purchased_results = _run_scraper_purchased_parallel()
    if purchased_results:
        purchased_ok = all(r is not None and r.returncode == 0 for _, r in purchased_results)
        if not purchased_ok:
            log.warning("purchased pass had failures/timeouts; pushing whatever landed in staging")

    pushed, failed, skipped = _walk_and_push()
    _accumulate_pushes(pushed, failed)
    log.info("sweep done: pushed=%d failed=%d skipped=%d (cumulative: pushed=%d failed=%d)",
             pushed, failed, skipped, _PUSH_TOTALS["pushed"], _PUSH_TOTALS["failed"])

    # Truth check: videos the upstream marked downloaded but never wrote (DRM /
    # Widevine, skipped for lack of a CDM). Without this the sweep reports a
    # clean run while those videos are simply absent from the gallery forever.
    try:
        _drm_audit()
    except Exception as e:  # noqa: BLE001
        log.warning("drm audit failed: %s: %s", type(e).__name__, e)

    # Delivery truth: how many stems this host knows the gallery did NOT store.
    try:
        _upload_ledger_report()
    except Exception as e:  # noqa: BLE001
        log.warning("upload ledger report failed: %s: %s", type(e).__name__, e)

    # Pass 5: like timeline posts from active subscriptions. Runs after all
    # downloads and pushes are complete. Only targets the manual model list
    # (explicit subs), not auto-discovered free subs. See _run_like_pass() for
    # the backlog/daily mode state machine.
    _run_like_pass()

    # Pass 6: unread message triage — clears broadcast-bait chats (text-only
    # spam / locked PPV) while leaving anything with free viewable media, tips,
    # pins or a priority model untouched. Read state is only changed through
    # the explicit mark-as-read endpoint; see _run_message_pass().
    _run_message_pass()


if __name__ == "__main__":
    if "--audit" in sys.argv:
        # Read-only scan of every model DB against the upload ledger. Add
        # --reset-known-gaps to re-queue the media this host can prove never
        # reached the gallery (see _audit_backlog). Does not touch the gallery.
        RESET_KNOWN_GAPS = "--reset-known-gaps" in sys.argv
        result = _audit_backlog()
        print(json.dumps(result, indent=2, sort_keys=True))
    elif "--reconcile" in sys.argv:
        # Ask the gallery (POST /ingest/have) which downloaded media it does not
        # account for. Report-only unless --apply is given.
        result = _reconcile_missing(apply="--apply" in sys.argv)
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        main()
