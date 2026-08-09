"""Grafana Discord Ack Bot.

Standalone service (deliberately NOT part of hermes-agent) that:
  1. Receives Grafana alertmanager webhook POSTs on a local HTTP port.
  2. Posts a formatted alert message to #infra-alerts via the Hermes
     Discord bot's existing webhook, then adds four reaction emoji: one
     plain ack (eyes) and three silence-duration options.
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
# Give up watching (leave the silence in place until its 30-day ceiling)
# after this long -- a safety valve so a permanently-stuck alert
# (Grafana can't tell it's resolved, or the matchers stop matching for
# some other reason) doesn't spin a watcher task forever.
ACK_WATCH_MAX_DURATION = timedelta(days=7)

# Timed silence options: actually suppresses re-firing/re-notification.
# Order matters: this is also the order reactions get added to a fresh
# alert message.
SILENCE_OPTIONS: list[tuple[str, timedelta]] = [
    ("1\N{combining enclosing keycap}", timedelta(hours=1)),
    ("4\N{combining enclosing keycap}", timedelta(hours=4)),
    ("\N{CALENDAR}", timedelta(hours=24)),
]
SILENCE_EMOJI = {emoji: duration for emoji, duration in SILENCE_OPTIONS}

# All emoji added to every posted alert message, in display/add order.
ALL_REACTION_EMOJI: list[str] = [ACK_ONLY_EMOJI] + [e for e, _ in SILENCE_OPTIONS]

# In-memory map of Discord message_id -> alert context, populated when we
# post an alert. Lost on restart -- acceptable, since a message older
# than the process restart just won't be actionable via reaction anymore
# (still visible/actionable manually in Grafana). Not persisted to keep
# this service dependency-free (no DB/file needed for a Sunday night
# iteration; revisit if that gap proves painful in practice).
_pending: dict[int, dict] = {}

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
    lines = [text]
    if generator_url:
        lines.append(f"[View in Grafana]({generator_url})")
    lines.append(
        f"React: {ACK_ONLY_EMOJI}=ack (suppress until resolved)  "
        "1\N{combining enclosing keycap}=silence 1h  "
        "4\N{combining enclosing keycap}=silence 4h  "
        "\N{CALENDAR}=silence 24h"
    )
    content = "\n".join(lines)

    async with session.post(
        f"{DISCORD_WEBHOOK_URL}?wait=true",
        json={"content": content, "username": "Grafana Alerts"},
    ) as resp:
        resp.raise_for_status()
        posted = await resp.json()
    message_id = int(posted["id"])

    for emoji in ALL_REACTION_EMOJI:
        await _add_reaction_with_retry(session, message_id, emoji)

    _pending[message_id] = {
        "alertname": alertname,
        "labels": labels,
        "matchers": _matchers_for_alert(alert),
        "content": content,
        "acked": False,
        "silenced": False,
    }
    log.info("Posted alert %s as message %s with %d matchers", alertname, message_id, len(_pending[message_id]["matchers"]))


async def handle_grafana_webhook(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=400, text="invalid json")

    alerts = payload.get("alerts", [])
    firing = [a for a in alerts if a.get("status") == "firing"]
    if not firing:
        # Resolved-only batches: nothing to ack, just acknowledge receipt.
        return web.Response(status=200, text="ok (no firing alerts)")

    async with aiohttp.ClientSession() as session:
        for alert in firing:
            try:
                await _post_alert_message(session, alert)
            except Exception:
                log.exception("Failed to post alert to Discord")

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


async def _alert_still_active(session: aiohttp.ClientSession, labels: dict) -> bool:
    """Check Grafana's Alertmanager active-alerts list for an entry whose
    labels exactly match. Used by the ack watcher to detect resolution --
    an acked alert instance disappearing from this list (or showing a
    non-active state) means it resolved and the ack's silence can come
    down early instead of riding out its 30-day ceiling.
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
        a_labels = a.get("labels", {})
        if a_labels == labels and a.get("status", {}).get("state") == "active":
            return True
    return False


async def _watch_for_resolution(
    message_id: int,
    silence_id: str,
    alertname: str,
    labels: dict,
    pending: dict,
) -> None:
    """Background task: poll until the acked alert is no longer active,
    then delete its silence early and post a synthesized resolved
    message. `pending` is the SAME dict stored in _pending so edits are
    reflected there too (matters if anything else ever reads content).
    """
    deadline = datetime.now(timezone.utc) + ACK_WATCH_MAX_DURATION
    async with aiohttp.ClientSession() as session:
        while datetime.now(timezone.utc) < deadline:
            await asyncio.sleep(ACK_WATCH_POLL_INTERVAL_SEC)
            try:
                still_active = await _alert_still_active(session, labels)
            except Exception:
                log.exception("Error polling active-alerts for %s, will retry", alertname)
                continue
            if still_active:
                continue

            log.info("Alert %s (silence %s) resolved, tearing down ack silence early", alertname, silence_id)
            await _delete_silence(session, silence_id)
            resolved_line = f"\n✅ Resolved — {alertname} is no longer firing (ack silence lifted)"
            new_content = pending["content"] + resolved_line
            pending["content"] = new_content
            await _edit_via_webhook(session, message_id, new_content)
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


async def _edit_via_webhook(session: aiohttp.ClientSession, message_id: int, new_content: str) -> None:
    # The alert message was posted via the raw Discord webhook, so it's
    # "authored by" that webhook identity, not the bot user -- Discord
    # only allows editing it through the webhook's own edit-message
    # endpoint (PATCH /webhooks/{id}/{token}/messages/{id}), NOT the
    # normal bot channel-message edit API (that 403s with "Cannot edit a
    # message authored by another user" even though it's the same
    # underlying application). DISCORD_WEBHOOK_URL already has the
    # {id}/{token} pair baked in.
    async with session.patch(
        f"{DISCORD_WEBHOOK_URL}/messages/{message_id}",
        json={"content": new_content},
    ) as edit_resp:
        if edit_resp.status >= 300:
            body = await edit_resp.text()
            log.warning("Failed to edit message via webhook API: %s %s", edit_resp.status, body)


class AckBotClient(discord.Client):
    def __init__(self, *args, **kwargs) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_reactions = True
        super().__init__(intents=intents, *args, **kwargs)
        self._http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        self._http_session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._http_session:
            await self._http_session.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Reaction listener ready as %s", self.user)

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
                asyncio.create_task(
                    _watch_for_resolution(
                        payload.message_id, silence_id, pending["alertname"], pending["labels"], pending
                    )
                )
            else:
                ack_line = "\n⚠️ Ack failed — could not create Grafana silence, check service logs"
                pending["content"] = pending["content"] + ack_line
            await self._edit(payload.message_id, pending["content"])
            return

        duration = SILENCE_EMOJI.get(emoji_str)
        if duration is None:
            return
        if pending.get("silenced"):
            log.info("Message %s already silenced, ignoring additional silence reaction", payload.message_id)
            return
        pending["silenced"] = True

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
        await self._edit(payload.message_id, pending["content"])

    async def _edit(self, message_id: int, new_content: str) -> None:
        assert self._http_session is not None
        await _edit_via_webhook(self._http_session, message_id, new_content)


async def run_http_server() -> None:
    app = web.Application()
    app.router.add_post("/grafana-webhook", handle_grafana_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_LISTEN_PORT)
    await site.start()
    log.info("HTTP receiver listening on :%d/grafana-webhook", HTTP_LISTEN_PORT)
    # Keep this coroutine alive alongside the Discord client.
    await asyncio.Event().wait()


async def main() -> None:
    client = AckBotClient()
    await asyncio.gather(
        client.start(DISCORD_BOT_TOKEN),
        run_http_server(),
    )


if __name__ == "__main__":
    asyncio.run(main())

