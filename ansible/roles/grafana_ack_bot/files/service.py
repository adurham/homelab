"""Grafana Discord Ack Bot.

Standalone service (deliberately NOT part of hermes-agent) that:
  1. Receives Grafana alertmanager webhook POSTs on a local HTTP port.
  2. Posts a formatted alert message to #infra-alerts via the Hermes
     Discord bot's existing webhook, then adds three reaction emoji as
     ack-duration options.
  3. Listens for reaction-add events on those messages (via the SAME bot
     token's Gateway connection -- reactions are broadcast Gateway
     events, NOT routed through Discord's single global Interactions
     Endpoint URL, so this cannot conflict with hermes-agent's own
     button/slash-command interaction handling on the same bot).
  4. On a recognized ack reaction from the allowed user, calls Grafana's
     Alertmanager Silence API to silence that alert for the chosen
     duration, then edits the message to show who acked it and for how
     long.

Why a separate service instead of extending hermes-agent's Discord
adapter: Discord interactions (message components / buttons) are routed
via ONE global per-application "Interactions Endpoint URL" setting.
hermes-agent already owns that for its own approval-button UI; pointing
it at a new receiver would silently redirect ALL of Hermes's Discord
interactions here and break existing hermes-agent features. Reactions
carry no such global routing conflict -- they're just Gateway events any
connected session for the bot token receives -- so a second, fully
separate process on the same bot token is safe and additive.

Config: all via environment variables, see grafana-ack-bot.env.example
in the homelab repo (ansible/roles/grafana_ack_bot/templates/).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
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
# Comma-separated Discord user IDs allowed to ack. Reactions from anyone
# else (including the bot's own reaction-priming) are ignored.
ALLOWED_USER_IDS = {
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip()
}
HTTP_LISTEN_PORT = int(os.environ.get("HTTP_LISTEN_PORT", "8990"))

# Reaction emoji -> ack duration. Order matters: this is also the order
# reactions get added to a fresh alert message.
ACK_OPTIONS: list[tuple[str, timedelta]] = [
    ("1\N{combining enclosing keycap}", timedelta(hours=1)),
    ("4\N{combining enclosing keycap}", timedelta(hours=4)),
    ("\N{CALENDAR}", timedelta(hours=24)),
]
ACK_EMOJI = {emoji: duration for emoji, duration in ACK_OPTIONS}

# In-memory map of Discord message_id -> alertmanager matchers, populated
# when we post an alert. Lost on restart -- acceptable, since a message
# older than the process restart just won't be silenceable via reaction
# anymore (still visible/actionable manually in Grafana). Not persisted
# to keep this service dependency-free (no DB/file needed for a Sunday
# night iteration; revisit if that gap proves painful in practice).
_pending_acks: dict[int, dict] = {}

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
    instance/hostname) rather than the whole alert rule -- so acking one
    down host doesn't silence the rule for every host it could ever fire
    on.
    """
    labels = alert.get("labels", {})
    matchers = []
    for name, value in labels.items():
        if not value:
            continue
        matchers.append({"name": name, "value": str(value), "isEqual": True, "isRegex": False})
    return matchers


async def _post_alert_message(session: aiohttp.ClientSession, alert: dict) -> None:
    severity, text = _severity_and_summary(alert)
    labels = alert.get("labels", {})
    alertname = labels.get("alertname", "alert")
    generator_url = alert.get("generatorURL", "")
    lines = [text]
    if generator_url:
        lines.append(f"[View in Grafana]({generator_url})")
    lines.append(
        "React to ack: 1\N{combining enclosing keycap}=1h  "
        "4\N{combining enclosing keycap}=4h  \N{CALENDAR}=24h"
    )
    content = "\n".join(lines)

    async with session.post(
        f"{DISCORD_WEBHOOK_URL}?wait=true",
        json={"content": content, "username": "Grafana Alerts"},
    ) as resp:
        resp.raise_for_status()
        posted = await resp.json()
    message_id = int(posted["id"])

    for emoji, _duration in ACK_OPTIONS:
        async with session.put(
            f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}"
            f"/messages/{message_id}/reactions/{emoji}/@me",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
        ) as reaction_resp:
            if reaction_resp.status >= 300:
                body = await reaction_resp.text()
                log.warning("Failed to add reaction %s: %s %s", emoji, reaction_resp.status, body)
        # Discord's reaction-add endpoint has a tight per-route rate limit
        # (observed: adding 3 reactions back-to-back with no delay 429s on
        # the 2nd/3rd). A small stagger keeps every priming reaction
        # landing reliably without meaningfully slowing message posting.
        await asyncio.sleep(0.3)

    _pending_acks[message_id] = {
        "alertname": alertname,
        "matchers": _matchers_for_alert(alert),
        "content": content,
    }
    log.info("Posted alert %s as message %s with %d matchers", alertname, message_id, len(_pending_acks[message_id]["matchers"]))


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


# ── Discord reaction handling -> Grafana silence ──────────────────────────


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
        duration = ACK_EMOJI.get(emoji_str)
        if duration is None:
            return

        pending = _pending_acks.get(payload.message_id)
        if pending is None:
            log.info("Reaction on unknown/expired message %s, ignoring", payload.message_id)
            return
        if pending.get("acked"):
            # Already handled (e.g. user reacted with two different ack
            # emoji, or double-clicked). Don't create a second silence or
            # append a second ack line -- first reaction wins.
            log.info("Message %s already acked, ignoring additional reaction", payload.message_id)
            return
        pending["acked"] = True

        assert self._http_session is not None
        created_by = f"discord:{payload.user_id}"
        comment = f"Acked via Discord reaction ({emoji_str}) by user {payload.user_id}"
        silence_id = await _create_silence(
            self._http_session, pending["matchers"], duration, created_by, comment
        )

        # The alert message was posted via the raw Discord webhook, so it's
        # "authored by" that webhook identity, not the bot user -- Discord
        # only allows editing it through the webhook's own edit-message
        # endpoint (PATCH /webhooks/{id}/{token}/messages/{id}), NOT the
        # normal bot channel-message edit API (that 403s with "Cannot edit
        # a message authored by another user" even though it's the same
        # underlying application). DISCORD_WEBHOOK_URL already has the
        # {id}/{token} pair baked in.
        old_content = pending.get("content", "")
        if silence_id:
            hours = int(duration.total_seconds() // 3600)
            ack_line = f"\n✅ Acked by <@{payload.user_id}> for {hours}h (silence `{silence_id[:8]}`)"
            new_content = old_content + ack_line
            log.info("Created silence %s for alert %s (%dh)", silence_id, pending["alertname"], hours)
        else:
            new_content = old_content + "\n⚠️ Ack failed — could not create Grafana silence, check service logs"

        async with self._http_session.patch(
            f"{DISCORD_WEBHOOK_URL}/messages/{payload.message_id}",
            json={"content": new_content},
        ) as edit_resp:
            if edit_resp.status >= 300:
                body = await edit_resp.text()
                log.warning("Failed to edit ack message via webhook API: %s %s", edit_resp.status, body)


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
