"""Grafana Discord Ack Bot.

Standalone service (deliberately NOT part of hermes-agent) that:
  1. Receives Grafana alertmanager webhook POSTs on a local HTTP port.
  2. Posts a formatted alert message to #infra-alerts via the Hermes
     Discord bot's existing webhook, then adds two reaction emoji: a
     plain ack (eyes) and a single silence-menu trigger (mute). Reacting
     to the mute emoji expands the message with three duration reactions
     (1h/4h/24h) instead of cluttering every alert with all three
     up front -- see "Two-step silence menu" below.
  3. Listens for reaction-add events on those messages (via the SAME bot
     token's Gateway connection -- reactions are broadcast Gateway
     events, NOT routed through Discord's single global Interactions
     Endpoint URL, so this cannot conflict with hermes-agent's own
     button/slash-command interaction handling on the same bot).
  4. Two DISTINCT reaction outcomes, deliberately kept separate (modeled
     on ScienceLogic EM7's ack semantics -- ack suppresses NEW
     notifications but the alert stays live and updates until it
     actually resolves, not until a fixed timer expires):
       - Ack (eyes emoji): creates a LONG (30-day) Alertmanager silence
         with EXACT matchers on every current label (so a severity
         change, e.g. warning->critical, is a genuinely new alert
         instance that is NOT covered by the old ack and notifies
         again -- deliberate, matches EM7 behavior), plus a permanent
         Grafana annotation for the record. A background watcher polls
         Grafana's active-alerts API; the moment this specific alert
         instance is no longer active, the watcher deletes the silence
         EARLY (well before the 30-day ceiling) and posts a synthesized
         "resolved" message to Discord -- because Grafana's own
         resolved-notification would otherwise be swallowed by the same
         silence that's suppressing the firing notifications.
       - Timed silence (1h/4h/24h emoji): a plain fixed-duration
         Alertmanager silence, no watcher, no synthesized resolution
         message -- "stop telling me about this for exactly N hours,
         I don't need Grafana to track when it actually clears."
     These are different operations because they answer different
     questions -- "suppress until this is actually fixed" vs. "suppress
     for a fixed window regardless of state" -- and Grafana has no
     native ack primitive, only time-boxed silences (deletable early),
     so the ack path above is the closest honest approximation of EM7
     semantics achievable on Grafana's real API surface.
  5. Two-step silence menu: the message is posted with only 👀 (ack) and
     🔇 (open silence menu) reactions. Reacting 🔇 adds the 1️⃣/4️⃣/📅
     duration reactions to the SAME message and edits it with a "pick a
     duration" prompt; reacting one of those then behaves exactly like
     the old flat 4-emoji design. This keeps the steady-state message
     uncluttered (2 reactions instead of 4) while still surfacing the
     durations for anyone who actually wants a timed silence instead of
     an EM7-style ack.

Why a separate service instead of extending hermes-agent's Discord
adapter: Discord interactions (message components / buttons) are routed
via ONE global per-application "Interactions Endpoint URL" setting.
hermes-agent already owns that for its own approval-button UI; pointing
it at a new receiver would silently redirect ALL of Hermes's Discord
interactions here and break existing hermes-agent features. Reactions
carry no such global routing conflict -- they're just Gateway events any
connected session for the bot token receives -- so a second, fully
separate process on the same bot token is safe and additive.

Config: all via environment variables, see grafana-ack-bot.env.j2 in the
homelab repo (ansible/roles/grafana_ack_bot/templates/).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("grafana_ack_bot")

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
DISCORD_CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
GRAFANA_URL = os.environ["GRAFANA_URL"].rstrip("/")
GRAFANA_SA_TOKEN = os.environ["GRAFANA_SA_TOKEN"]
# Comma-separated Discord user IDs allowed to ack/silence. Reactions from
# anyone else (including the bot's own reaction-priming) are ignored.
ALLOWED_USER_IDS = {
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip()
}
HTTP_LISTEN_PORT = int(os.environ.get("HTTP_LISTEN_PORT", "8990"))
# Where pending-alert state (message_id -> ack/silence context) is
# persisted to disk. Without this, a service restart (deploy, crash,
# OOM, host reboot) wipes _pending and every previously-posted alert
# message becomes permanently un-actionable via reaction -- Discord
# shows the reactions were added, a user reacts, and the bot silently
# no-ops with "Reaction on unknown/expired message, ignoring" because
# it has no memory the message ever existed. Observed in practice
# 2026-08-09: 6 restarts happened between posting 4 alert messages and
# the user acking them; only the 2 messages posted after the LAST
# restart were still tracked, so 4 "acks" silently did nothing.
STATE_PATH = os.environ.get("STATE_PATH", "/opt/grafana-ack-bot/state.json")

# Plain ack: "a human has seen this", suppresses re-notification UNTIL
# the alert actually resolves (not a fixed timer) -- EM7-style.
ACK_ONLY_EMOJI = "\N{EYES}"
# Ack's underlying silence is a long ceiling, not the real expiry
# mechanism -- the resolution watcher deletes it early in the vastly
# common case. This ceiling only matters if the watcher itself is down
# (service crash-looped, host down) for the whole window, in which case
# the alert will start renotifying again after 30 days rather than
# staying silently acked forever.
ACK_SILENCE_CEILING = timedelta(days=30)
# How often the resolution watcher polls Grafana's active-alerts API per
# acked alert. Short enough that "resolved" shows up promptly, long
# enough not to hammer Grafana with N concurrent acked-alert pollers.
ACK_WATCH_POLL_INTERVAL_SEC = 30
# Number of consecutive polls where an acked alert's fingerprint must be
# absent from the active-alerts list before it's treated as genuinely
# resolved. A single miss is not trusted -- Grafana can return a 200
# with a transiently incomplete list (mid-restart, brief backend hiccup)
# that looks identical to real resolution. 2 misses = ~60s of confirmed
# absence at the default 30s poll interval.
RESOLUTION_MISS_THRESHOLD = 2
# Give up watching (leave the silence in place until its 30-day ceiling)
# after this long -- a safety valve so a permanently-stuck alert
# (Grafana can't tell it's resolved, or the matchers stop matching for
# some other reason) doesn't spin a watcher task forever.
ACK_WATCH_MAX_DURATION = timedelta(days=7)

# Timed silence options: actually suppresses re-firing/re-notification.
# Order matters: this is also the order reactions get added once the
# silence menu is opened.
SILENCE_OPTIONS: list[tuple[str, timedelta]] = [
    ("1\N{combining enclosing keycap}", timedelta(hours=1)),
    ("4\N{combining enclosing keycap}", timedelta(hours=4)),
    ("\N{CALENDAR}", timedelta(hours=24)),
]
SILENCE_EMOJI = {emoji: duration for emoji, duration in SILENCE_OPTIONS}

# Single reaction that opens the silence-duration menu (see "Two-step
# silence menu" in the module docstring). Using the mute speaker instead
# of one of the duration emoji so it reads unambiguously as "pick a
# silence length" rather than looking like a 4th duration option.
SILENCE_MENU_EMOJI = "\N{SPEAKER WITH CANCELLATION STROKE}"

# Reactions added when an alert is first posted: just ack + open-menu.
# The three duration emoji are added on-demand when the menu is opened,
# not up front -- keeps the steady-state message to 2 reactions instead
# of 4.
INITIAL_REACTION_EMOJI: list[str] = [ACK_ONLY_EMOJI, SILENCE_MENU_EMOJI]

# In-memory map of Discord message_id -> alert context, populated when we
# post an alert and mirrored to STATE_PATH after every mutation so a
# service restart can reload it (see STATE_PATH comment above for why
# this matters -- losing this silently breaks every already-posted
# alert's reactions).
_pending: dict[int, dict] = {}


def _load_pending() -> None:
    if not os.path.exists(STATE_PATH):
        return
    try:
        with open(STATE_PATH, "r") as f:
            raw = json.load(f)
    except Exception:
        log.exception("Failed to load persisted state from %s, starting empty", STATE_PATH)
        return
    for key, value in raw.items():
        _pending[int(key)] = value
    log.info("Loaded %d pending alert(s) from %s", len(_pending), STATE_PATH)


def _save_pending() -> None:
    tmp_path = STATE_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump({str(k): v for k, v in _pending.items()}, f)
        os.replace(tmp_path, STATE_PATH)
    except Exception:
        log.exception("Failed to persist state to %s", STATE_PATH)

# Discord's reaction-add endpoint has a tight per-channel rate limit that
# is SHARED across concurrent requests -- observed 429s when multiple
# alert messages in the same webhook batch each try to add their 4
# reactions concurrently (6 alerts x 4 emoji = 24 near-simultaneous PUTs
# blew through the bucket). A single process-wide lock serializes every
# reaction-add through one path so the retry/backoff logic below has a
# consistent view of the rate limit instead of racing itself.
_reaction_lock = asyncio.Lock()

# ── Grafana alertmanager webhook payload -> Discord message ──────────────


def _severity_and_summary(alert: dict) -> tuple[str, str]:
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    severity = labels.get("severity", "unknown")
    summary = annotations.get("summary") or labels.get("alertname", "alert")
    description = annotations.get("description", "")
    text = f"**{severity}** — {summary}"
    if description:
        text += f"\n{description}"
    return severity, text


def _matchers_for_alert(alert: dict) -> list[dict]:
    """Build Alertmanager silence matchers that uniquely target this one
    alert instance (alertname + every other label Grafana attached, e.g.
    instance/hostname) rather than the whole alert rule -- so silencing
    one down host doesn't silence the rule for every host it could ever
    fire on.
    """
    labels = alert.get("labels", {})
    matchers = []
    for name, value in labels.items():
        if not value:
            continue
        matchers.append({"name": name, "value": str(value), "isEqual": True, "isRegex": False})
    return matchers


async def _add_reaction_with_retry(
    session: aiohttp.ClientSession, message_id: int, emoji: str, max_attempts: int = 4
) -> None:
    """Add one reaction, retrying on 429 using Discord's own retry_after.
    Always runs under _reaction_lock so concurrent alert posts can't pile
    requests into the same rate-limit bucket at once.
    """
    async with _reaction_lock:
        for attempt in range(1, max_attempts + 1):
            async with session.put(
                f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}"
                f"/messages/{message_id}/reactions/{emoji}/@me",
                headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
            ) as resp:
                if resp.status < 300:
                    return
                if resp.status == 429:
                    try:
                        body = await resp.json()
                        retry_after = float(body.get("retry_after", 1.0))
                    except Exception:
                        retry_after = 1.0
                    log.warning(
                        "Reaction %s rate-limited (attempt %d/%d), retrying in %.2fs",
                        emoji, attempt, max_attempts, retry_after,
                    )
                    await asyncio.sleep(retry_after + 0.1)
                    continue
                body_text = await resp.text()
                log.warning("Failed to add reaction %s: %s %s", emoji, resp.status, body_text)
                return
        log.error("Giving up adding reaction %s to message %s after %d attempts", emoji, message_id, max_attempts)


async def _post_alert_message(session: aiohttp.ClientSession, alert: dict) -> None:
    severity, text = _severity_and_summary(alert)
    labels = alert.get("labels", {})
    alertname = labels.get("alertname", "alert")
    generator_url = alert.get("generatorURL", "")
    fingerprint = alert.get("fingerprint", "")
    lines = [text]
    if generator_url:
        lines.append(f"[View in Grafana]({generator_url})")
    lines.append(
        f"React: {ACK_ONLY_EMOJI}=ack (suppress until resolved)  "
        f"{SILENCE_MENU_EMOJI}=silence (opens duration menu)"
    )
    content = "\n".join(lines)

    async with session.post(
        f"{DISCORD_WEBHOOK_URL}?wait=true",
        json={"content": content, "username": "Grafana Alerts"},
    ) as resp:
        resp.raise_for_status()
        posted = await resp.json()
    message_id = int(posted["id"])

    for emoji in INITIAL_REACTION_EMOJI:
        await _add_reaction_with_retry(session, message_id, emoji)

    _pending[message_id] = {
        "alertname": alertname,
        "labels": labels,
        # Grafana's Alertmanager webhook payload gives us a stable
        # per-instance fingerprint that's identical on the firing and
        # resolved notification for the same alert instance -- use it to
        # correlate a resolved webhook back to this message instead of
        # exact label-dict equality. Label equality is what this used
        # before 2026-08-09 and is fragile: any difference in Grafana's
        # internal-label stripping/injection between the firing and
        # resolved payload (version-dependent, not something we control)
        # breaks the match and leaves the message stuck in Discord
        # forever with no way to know it resolved.
        "fingerprint": fingerprint,
        "matchers": _matchers_for_alert(alert),
        "content": content,
        "acked": False,
        "silenced": False,
        "menu_open": False,
    }
    _save_pending()
    log.info("Posted alert %s as message %s with %d matchers", alertname, message_id, len(_pending[message_id]["matchers"]))


def _pending_matches_alert(pending: dict, alert: dict) -> bool:
    """Correlate a Grafana webhook alert (firing or resolved) back to a
    _pending entry. Prefers the stable per-instance fingerprint Grafana
    attaches to both the firing and resolved notification for the same
    alert instance; falls back to exact label-dict equality only for
    older _pending entries persisted before the fingerprint field was
    captured (state.json survives service upgrades).
    """
    fingerprint = alert.get("fingerprint")
    pending_fp = pending.get("fingerprint")
    if fingerprint and pending_fp:
        return fingerprint == pending_fp
    return pending.get("labels", {}) == alert.get("labels", {})


async def handle_grafana_webhook(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=400, text="invalid json")

    alerts = payload.get("alerts", [])
    firing = [a for a in alerts if a.get("status") == "firing"]
    resolved = [a for a in alerts if a.get("status") != "firing"]

    async with aiohttp.ClientSession() as session:
        for alert in firing:
            try:
                await _post_alert_message(session, alert)
            except Exception:
                log.exception("Failed to post alert to Discord")

        # Delete the Discord message for any alert that resolved WITHOUT
        # the acked-resolution watcher already handling it (that path
        # covers acked alerts via its own polling loop in
        # _watch_for_resolution). This covers alerts that resolve on
        # their own before anyone reacts, AND silenced-but-not-acked
        # alerts (silences don't spin up a resolution watcher). Until
        # this fix (2026-08-09) resolved payloads were silently dropped
        # entirely ("Resolved-only batches: nothing to ack, just
        # acknowledge receipt"), so unacked resolved alerts piled up in
        # #infra-alerts forever until someone noticed and manually
        # purged them.
        #
        # Deletes ALL matching unacked/unresolved entries (not just the
        # first) -- a flapping alert whose earlier resolved webhook was
        # missed can leave more than one stale _pending entry with the
        # same fingerprint/labels.
        for alert in resolved:
            for message_id, pending in list(_pending.items()):
                if pending.get("resolved") or pending.get("acked"):
                    continue
                if not _pending_matches_alert(pending, alert):
                    continue
                log.info(
                    "Alert %s resolved (not ack-watched), deleting message %s",
                    pending.get("alertname"), message_id,
                )
                await _delete_via_webhook(session, message_id)
                # Re-check after the await: the user could have acked
                # this exact message while the delete was in flight
                # (e.g. rate-limited retry taking a few seconds), in
                # which case an ack watcher now owns this message_id and
                # popping it here would leak that watcher's silence
                # (nothing would ever delete it). Only pop if it's still
                # unacked post-delete.
                still_pending = _pending.get(message_id)
                if still_pending is not None and not still_pending.get("acked"):
                    _pending.pop(message_id, None)
                    _save_pending()

    return web.Response(status=200, text="ok")


# ── Discord reaction handling -> Grafana ack / silence ────────────────────


async def _create_silence(session: aiohttp.ClientSession, matchers: list[dict], duration: timedelta, created_by: str, comment: str) -> str | None:
    now = datetime.now(timezone.utc)
    body = {
        "matchers": matchers,
        "startsAt": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "endsAt": (now + duration).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "createdBy": created_by,
        "comment": comment,
    }
    async with session.post(
        f"{GRAFANA_URL}/api/alertmanager/grafana/api/v2/silences",
        headers={"Authorization": f"Bearer {GRAFANA_SA_TOKEN}"},
        json=body,
    ) as resp:
        if resp.status >= 300:
            text = await resp.text()
            log.error("Silence creation failed (%s): %s", resp.status, text)
            return None
        result = await resp.json()
        return result.get("silenceID")


async def _delete_silence(session: aiohttp.ClientSession, silence_id: str) -> bool:
    async with session.delete(
        f"{GRAFANA_URL}/api/alertmanager/grafana/api/v2/silence/{silence_id}",
        headers={"Authorization": f"Bearer {GRAFANA_SA_TOKEN}"},
    ) as resp:
        if resp.status >= 300:
            text = await resp.text()
            log.error("Silence deletion failed (%s) for %s: %s", resp.status, silence_id, text)
            return False
        return True


async def _alert_still_active(session: aiohttp.ClientSession, fingerprint: str) -> bool:
    """Check Grafana's Alertmanager active-alerts list for an entry with
    this fingerprint. Used by the ack watcher to detect resolution -- an
    acked alert instance disappearing from this list entirely means it
    resolved and the ack's silence can come down early instead of riding
    out its 30-day ceiling.

    Matches on fingerprint, NOT labels. Grafana's OUTGOING webhook
    payload (what _pending's labels were captured from at post time)
    strips server-injected labels like __alert_rule_uid__ and
    grafana_folder that the /api/v2/alerts REST API response DOES
    include for the same instance -- confirmed empirically 2026-08-09
    (webhook gave 6 labels, API gave 8 for the identical alert). Exact
    label-dict equality between the two therefore NEVER matches, which
    meant this check always returned False (alert not found -> treated
    as resolved) on the very first poll after every ack, regardless of
    whether the alert was still genuinely firing. fingerprint is
    computed from the full internal label set on both the webhook
    payload and the API response for the same alert instance, so it's
    stable and comparable across both surfaces.

    IMPORTANT: this must NOT filter on status.state == "active". Once an
    alert is acked, the ack's OWN silence matches its labels, which flips
    Alertmanager's status.state for that instance from "active" to
    "suppressed" almost immediately -- within one poll cycle in practice.
    An earlier version of this function checked for state == "active"
    and as a result declared nearly every acked alert "resolved" within
    ~30s of being acked (misreading its own silence as resolution),
    regardless of whether the underlying problem was still firing.
    Presence in this list at all -- active OR suppressed -- means the
    alert instance is still known to Alertmanager, i.e. NOT resolved;
    only its total absence from the list means resolved.
    """
    async with session.get(
        f"{GRAFANA_URL}/api/alertmanager/grafana/api/v2/alerts",
        headers={"Authorization": f"Bearer {GRAFANA_SA_TOKEN}"},
    ) as resp:
        if resp.status >= 300:
            # Fail safe: treat an API error as "still active" so a
            # transient Grafana hiccup doesn't cause a premature
            # resolved-message + early silence teardown.
            log.warning("Could not query active alerts (%s), assuming still active", resp.status)
            return True
        alerts = await resp.json()

    for a in alerts:
        if a.get("fingerprint") == fingerprint:
            return True
    return False


# Tasks currently watching for an acked alert's resolution, keyed by
# message_id. Held here (not just fire-and-forgotten via create_task)
# for two reasons: (1) asyncio only holds a weak reference to a task
# with no other referent, so an unreferenced task can be garbage
# collected mid-flight; (2) lets _resume_ack_watchers() and the ack
# handler check "is a watcher already running for this message" so a
# Gateway reconnect (on_ready can fire more than once per process) or a
# duplicate reaction doesn't spawn two watchers racing to tear down the
# same silence.
_ack_watchers: dict[int, asyncio.Task] = {}


def _spawn_ack_watcher(message_id: int, silence_id: str, alertname: str, fingerprint: str, pending: dict) -> None:
    existing = _ack_watchers.get(message_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(_watch_for_resolution(message_id, silence_id, alertname, fingerprint, pending))
    _ack_watchers[message_id] = task


async def _watch_for_resolution(
    message_id: int,
    silence_id: str,
    alertname: str,
    fingerprint: str,
    pending: dict,
) -> None:
    """Background task: poll until the acked alert is no longer active,
    then delete its silence early AND delete the Discord message itself
    -- per explicit direction, #infra-alerts shows ONLY currently-firing
    alerts; resolved/historical state belongs in Grafana, not piling up
    in Discord. `pending` is the SAME dict stored in _pending so state
    changes are reflected there too.

    Requires MISS_THRESHOLD consecutive polls where the fingerprint is
    absent from the active-alerts list before treating it as resolved,
    not a single miss. Without this debounce, one transient/incomplete
    API response (Grafana mid-restart, a slow query, momentary API
    hiccup that still returns 200 with a partial list) looks identical
    to genuine resolution and deletes a message for an alert that's
    still actually firing -- this exact failure mode deleted 3 live
    alerts' messages via the reconcile sweep on 2026-08-09 before this
    debounce was added.
    """
    deadline = datetime.now(timezone.utc) + ACK_WATCH_MAX_DURATION
    consecutive_misses = 0
    async with aiohttp.ClientSession() as session:
        while datetime.now(timezone.utc) < deadline:
            await asyncio.sleep(ACK_WATCH_POLL_INTERVAL_SEC)
            try:
                still_active = await _alert_still_active(session, fingerprint)
            except Exception:
                log.exception("Error polling active-alerts for %s, will retry", alertname)
                consecutive_misses = 0
                continue
            if still_active:
                consecutive_misses = 0
                continue

            consecutive_misses += 1
            if consecutive_misses < RESOLUTION_MISS_THRESHOLD:
                log.info(
                    "Alert %s not seen in active-alerts poll %d/%d, waiting for confirmation before treating as resolved",
                    alertname, consecutive_misses, RESOLUTION_MISS_THRESHOLD,
                )
                continue

            log.info("Alert %s (silence %s) resolved, tearing down ack silence and deleting message %s", alertname, silence_id, message_id)
            await _delete_silence(session, silence_id)
            await _delete_via_webhook(session, message_id)
            _pending.pop(message_id, None)
            _ack_watchers.pop(message_id, None)
            _save_pending()
            return

        log.warning(
            "Ack watcher for %s gave up after %s without seeing resolution; "
            "silence %s will ride out its ceiling instead of being lifted early",
            alertname, ACK_WATCH_MAX_DURATION, silence_id,
        )


async def _create_ack_annotation(session: aiohttp.ClientSession, alertname: str, labels: dict, discord_user_id: int) -> int | None:
    """Record a plain ack as a Grafana annotation -- visible in Grafana's
    UI/API, tagged for querying, but does NOT touch alert notification
    behavior (unlike a silence). No dashboardUID/panelId set, so this is
    an org-wide annotation (queryable via GET /api/annotations?tags=ack).
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    label_str = ", ".join(f"{k}={v}" for k, v in labels.items() if k != "alertname")
    text = f"Acked via Discord by user {discord_user_id}: {alertname}"
    if label_str:
        text += f" ({label_str})"
    body = {
        "time": now_ms,
        "tags": ["ack", "discord", alertname],
        "text": text,
    }
    async with session.post(
        f"{GRAFANA_URL}/api/annotations",
        headers={"Authorization": f"Bearer {GRAFANA_SA_TOKEN}"},
        json=body,
    ) as resp:
        if resp.status >= 300:
            text_body = await resp.text()
            log.error("Ack annotation failed (%s): %s", resp.status, text_body)
            return None
        result = await resp.json()
        return result.get("id")


async def _edit_via_webhook(
    session: aiohttp.ClientSession, message_id: int, new_content: str, max_attempts: int = 4
) -> None:
    # The alert message was posted via the raw Discord webhook, so it's
    # "authored by" that webhook identity, not the bot user -- Discord
    # only allows editing it through the webhook's own edit-message
    # endpoint (PATCH /webhooks/{id}/{token}/messages/{id}), NOT the
    # normal bot channel-message edit API (that 403s with "Cannot edit a
    # message authored by another user" even though it's the same
    # underlying application). DISCORD_WEBHOOK_URL already has the
    # {id}/{token} pair baked in.
    #
    # Retries on 429 the same way _add_reaction_with_retry does. Without
    # this, a rate-limited edit is just logged and dropped -- observed in
    # practice 2026-08-09: the resolution watcher's "torn down early"
    # edit for tms-02 hit a 429 during a burst of 6 simultaneous
    # teardowns and silently never landed, so the Discord message stayed
    # showing "Acked" forever even though the alert had genuinely
    # resolved and its silence was gone. No retry meant no second
    # chance -- the resolved checkmark was just lost.
    for attempt in range(1, max_attempts + 1):
        async with session.patch(
            f"{DISCORD_WEBHOOK_URL}/messages/{message_id}",
            json={"content": new_content},
        ) as edit_resp:
            if edit_resp.status < 300:
                return
            if edit_resp.status == 429:
                try:
                    body = await edit_resp.json()
                    retry_after = float(body.get("retry_after", 1.0))
                except Exception:
                    retry_after = 1.0
                log.warning(
                    "Edit rate-limited for message %s (attempt %d/%d), retrying in %.2fs",
                    message_id, attempt, max_attempts, retry_after,
                )
                await asyncio.sleep(retry_after + 0.1)
                continue
            body_text = await edit_resp.text()
            log.warning("Failed to edit message via webhook API: %s %s", edit_resp.status, body_text)
            return
    log.error("Giving up editing message %s after %d attempts", message_id, max_attempts)


async def _delete_via_webhook(
    session: aiohttp.ClientSession, message_id: int, max_attempts: int = 4
) -> None:
    """Delete an alert message via the webhook's own delete endpoint
    (same authored-by-webhook constraint as _edit_via_webhook -- the bot
    API can't touch it). Used once an alert resolves: per explicit
    direction, #infra-alerts should show ONLY currently-firing alerts,
    with resolved/historical state living in Grafana, not accumulating
    in Discord. Retries on 429 like every other Discord call here.
    """
    for attempt in range(1, max_attempts + 1):
        async with session.delete(
            f"{DISCORD_WEBHOOK_URL}/messages/{message_id}",
        ) as del_resp:
            if del_resp.status < 300 or del_resp.status == 404:
                # 404 = already gone (e.g. manually deleted) -- treat as
                # success, nothing left to clean up.
                return
            if del_resp.status == 429:
                try:
                    body = await del_resp.json()
                    retry_after = float(body.get("retry_after", 1.0))
                except Exception:
                    retry_after = 1.0
                log.warning(
                    "Delete rate-limited for message %s (attempt %d/%d), retrying in %.2fs",
                    message_id, attempt, max_attempts, retry_after,
                )
                await asyncio.sleep(retry_after + 0.1)
                continue
            body_text = await del_resp.text()
            log.warning("Failed to delete message via webhook API: %s %s", del_resp.status, body_text)
            return
    log.error("Giving up deleting message %s after %d attempts", message_id, max_attempts)


def _resume_ack_watchers() -> None:
    """Re-spawn resolution-watcher tasks for any alert that was acked
    (has an ack_silence_id) but never saw resolution before the process
    last stopped. Without this, a restart after an ack silently drops
    the watcher -- the silence stays in place until its 30-day ceiling
    but the "resolved" message and early silence teardown never happen.

    Called from on_ready, which discord.py can fire more than once per
    process (Gateway reconnect/resume) -- _spawn_ack_watcher is a no-op
    if a watcher for that message_id is already running, so repeat
    calls are safe and cheap.
    """
    resumed = 0
    skipped_no_fingerprint = 0
    for message_id, pending in _pending.items():
        silence_id = pending.get("ack_silence_id")
        if not silence_id or pending.get("resolved"):
            continue
        try:
            alertname = pending["alertname"]
        except KeyError:
            log.warning("Skipping malformed pending entry for message %s (missing alertname)", message_id)
            continue
        fingerprint = pending.get("fingerprint")
        if not fingerprint:
            # Persisted by a pre-fingerprint version of this service.
            # Nothing safe to poll on -- resume-watching would just
            # never find a match (see _alert_still_active's docstring
            # for why label-only matching is unreliable) and eventually
            # time out without ever tearing down the silence early. Log
            # it and leave the silence to ride out its 30-day ceiling
            # rather than guessing.
            skipped_no_fingerprint += 1
            continue
        _spawn_ack_watcher(message_id, silence_id, alertname, fingerprint, pending)
        resumed += 1
    if resumed:
        log.info("Resumed %d ack resolution watcher(s) after restart", resumed)
    if skipped_no_fingerprint:
        log.warning(
            "Skipped resuming %d ack watcher(s) with no persisted fingerprint (pre-fingerprint state) "
            "-- their silences will ride out the 30-day ceiling instead of tearing down early",
            skipped_no_fingerprint,
        )


class AckBotClient(discord.Client):
    def __init__(self, *args, **kwargs) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_reactions = True
        super().__init__(*args, intents=intents, **kwargs)
        self._http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        self._http_session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._http_session:
            await self._http_session.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Reaction listener ready as %s", self.user)
        _resume_ack_watchers()

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.channel_id != DISCORD_CHANNEL_ID:
            return
        if self.user and payload.user_id == self.user.id:
            return  # our own priming reactions
        if ALLOWED_USER_IDS and payload.user_id not in ALLOWED_USER_IDS:
            log.info("Ignoring reaction from non-allowed user %s", payload.user_id)
            return

        emoji_str = str(payload.emoji)
        pending = _pending.get(payload.message_id)
        if pending is None:
            log.info("Reaction on unknown/expired message %s, ignoring", payload.message_id)
            return

        assert self._http_session is not None

        if emoji_str == ACK_ONLY_EMOJI:
            if pending.get("acked"):
                log.info("Message %s already acked, ignoring repeat", payload.message_id)
                return
            pending["acked"] = True
            _save_pending()

            created_by = f"discord:{payload.user_id}"
            comment = f"Acked via Discord reaction ({emoji_str}) by user {payload.user_id} -- EM7-style, suppressed until resolution"
            silence_id = await _create_silence(
                self._http_session, pending["matchers"], ACK_SILENCE_CEILING, created_by, comment
            )
            annotation_id = await _create_ack_annotation(
                self._http_session, pending["alertname"], pending["labels"], payload.user_id
            )

            if silence_id:
                ack_line = (
                    f"\n👀 Acked by <@{payload.user_id}> — new notifications suppressed until "
                    f"this resolves (silence `{silence_id[:8]}`"
                )
                ack_line += f", annotation `{annotation_id}`)" if annotation_id else ")"
                log.info(
                    "Created ack silence %s (annotation %s) for alert %s, starting resolution watcher",
                    silence_id, annotation_id, pending["alertname"],
                )
                pending["content"] = pending["content"] + ack_line
                pending["ack_silence_id"] = silence_id
                _save_pending()
                _spawn_ack_watcher(
                    payload.message_id, silence_id, pending["alertname"], pending.get("fingerprint", ""), pending
                )
            else:
                ack_line = "\n⚠️ Ack failed — could not create Grafana silence, check service logs"
                pending["content"] = pending["content"] + ack_line
                _save_pending()
            await self._edit(payload.message_id, pending["content"])
            return

        if emoji_str == SILENCE_MENU_EMOJI:
            if pending.get("silenced") or pending.get("menu_open"):
                # Either already silenced, or the menu's already open and
                # the duration emoji are visible -- nothing more to do.
                return
            pending["menu_open"] = True
            pending["content"] = pending["content"] + "\n🔇 Pick a duration below:"
            _save_pending()
            await self._edit(payload.message_id, pending["content"])
            for emoji, _duration in SILENCE_OPTIONS:
                await _add_reaction_with_retry(self._http_session, payload.message_id, emoji)
            return

        duration = SILENCE_EMOJI.get(emoji_str)
        if duration is None:
            return
        if not pending.get("menu_open"):
            # Duration emoji reacted before the menu was opened (e.g. a
            # stale/manually-added reaction) -- ignore, since there's no
            # menu prompt on the message for this to be answering.
            return
        if pending.get("silenced"):
            log.info("Message %s already silenced, ignoring additional silence reaction", payload.message_id)
            return
        pending["silenced"] = True
        _save_pending()

        created_by = f"discord:{payload.user_id}"
        comment = f"Silenced via Discord reaction ({emoji_str}) by user {payload.user_id}"
        silence_id = await _create_silence(
            self._http_session, pending["matchers"], duration, created_by, comment
        )

        if silence_id:
            hours = int(duration.total_seconds() // 3600)
            line = f"\n🔇 Silenced by <@{payload.user_id}> for {hours}h (silence `{silence_id[:8]}`)"
            log.info("Created silence %s for alert %s (%dh)", silence_id, pending["alertname"], hours)
        else:
            line = "\n⚠️ Silence failed — could not create Grafana silence, check service logs"
        pending["content"] = pending["content"] + line
        _save_pending()
        await self._edit(payload.message_id, pending["content"])

    async def _edit(self, message_id: int, new_content: str) -> None:
        assert self._http_session is not None
        await _edit_via_webhook(self._http_session, message_id, new_content)


async def run_http_server() -> None:
    app = web.Application()
    app.router.add_post("/grafana-webhook", handle_grafana_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_LISTEN_PORT)  # noqa: S104 -- must accept Grafana's webhook POST from another host, not just localhost
    await site.start()
    log.info("HTTP receiver listening on :%d/grafana-webhook", HTTP_LISTEN_PORT)
    # Keep this coroutine alive alongside the Discord client.
    await asyncio.Event().wait()


# How often the reconciliation sweep runs. This is a safety net, not the
# primary resolve-detection path (that's the webhook resolved-batch
# handler for unacked alerts, and _watch_for_resolution's poll for acked
# ones) -- it exists to catch cases neither of those cover: a missed
# Grafana webhook delivery (bot down during the resolved notification,
# Discord outage, Alertmanager retry exhaustion), or a crash between an
# unacked-resolve delete and its _save_pending() call leaving a stale
# entry. Runs at a slower cadence than the ack watcher's 30s poll since
# it's O(all pending alerts) against the same active-alerts endpoint
# rather than one alert per task.
RECONCILE_INTERVAL_SEC = 300
# Consecutive reconcile sweeps required before deleting anything. 2 =
# 10 minutes of confirmed absence at the default 5-minute interval.
RECONCILE_MISS_THRESHOLD = 2

# Per-message_id count of consecutive reconcile sweeps where the alert
# was absent from the active-alerts list. Not persisted -- a service
# restart resets it, which is fine since a restart also means state.json
# was just freshly reloaded and _pending only reflects genuinely
# still-open alerts as of the last _save_pending() before the restart.
_reconcile_miss_counts: dict[int, int] = {}


async def _reconcile_pending() -> None:
    """Background loop: periodically diff every _pending entry that ISN'T
    already covered by an ack watcher against Grafana's active-alerts
    list (matched by fingerprint -- see _alert_still_active's docstring
    for why label matching across the webhook-payload/API boundary is
    unreliable), and delete the Discord message for anything confirmed
    resolved but never cleaned up. See RECONCILE_INTERVAL_SEC for why
    this exists alongside the webhook-driven and ack-watcher-driven
    paths.

    Requires RECONCILE_MISS_THRESHOLD consecutive sweeps (not a single
    one) with the alert absent before deleting anything. A single sweep
    deleted 3 GENUINELY STILL-FIRING alerts' Discord messages on
    2026-08-09 -- root cause was matching on labels instead of
    fingerprint (see _alert_still_active), but the single-miss trigger
    made that bug immediately destructive instead of self-correcting on
    the next poll. Never repeat that mistake: always debounce a
    delete-on-absence decision against a data source that can be
    transiently wrong.
    """
    async with aiohttp.ClientSession() as session:
        while True:
            await asyncio.sleep(RECONCILE_INTERVAL_SEC)
            try:
                async with session.get(
                    f"{GRAFANA_URL}/api/alertmanager/grafana/api/v2/alerts",
                    headers={"Authorization": f"Bearer {GRAFANA_SA_TOKEN}"},
                ) as resp:
                    if resp.status >= 300:
                        log.warning("Reconcile: could not query active alerts (%s), skipping this pass", resp.status)
                        continue
                    active_alerts = await resp.json()
            except Exception:
                log.exception("Reconcile: error querying active alerts, will retry next interval")
                continue

            active_fingerprints = {a.get("fingerprint") for a in active_alerts if a.get("fingerprint")}
            candidates: list[int] = []
            for message_id, pending in list(_pending.items()):
                if pending.get("resolved") or pending.get("acked"):
                    # acked entries are covered by their own watcher task
                    continue
                fingerprint = pending.get("fingerprint")
                if not fingerprint:
                    # Pre-fingerprint legacy entry -- nothing safe to
                    # match on, leave it for someone to notice/clean up
                    # manually rather than guessing with label matching.
                    continue
                if fingerprint not in active_fingerprints:
                    candidates.append(message_id)
                else:
                    _reconcile_miss_counts.pop(message_id, None)

            stale: list[int] = []
            for message_id in candidates:
                count = _reconcile_miss_counts.get(message_id, 0) + 1
                _reconcile_miss_counts[message_id] = count
                if count >= RECONCILE_MISS_THRESHOLD:
                    stale.append(message_id)
                else:
                    log.info(
                        "Reconcile: message %s absent from active-alerts %d/%d sweeps, waiting for confirmation",
                        message_id, count, RECONCILE_MISS_THRESHOLD,
                    )

            if not stale:
                continue
            log.info("Reconcile: found %d stale unacked message(s) not caught by the webhook path, cleaning up", len(stale))
            for message_id in stale:
                await _delete_via_webhook(session, message_id)
                _reconcile_miss_counts.pop(message_id, None)
                still_pending = _pending.get(message_id)
                if still_pending is not None and not still_pending.get("acked"):
                    _pending.pop(message_id, None)
                    _save_pending()


async def main() -> None:
    _load_pending()
    client = AckBotClient()
    await asyncio.gather(
        client.start(DISCORD_BOT_TOKEN),
        run_http_server(),
        _reconcile_pending(),
    )


if __name__ == "__main__":
    asyncio.run(main())

