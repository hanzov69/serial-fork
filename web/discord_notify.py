"""
Discord REST API helpers for the web app.

Used to update mod-channel messages when approvals/rejections happen via the web UI,
without requiring discord.py (uses httpx to call the API directly with the bot token).
"""
from __future__ import annotations

import logging

import httpx

from shared.config import Settings

log = logging.getLogger(__name__)

_DISCORD_API = "https://discord.com/api/v10"


def _color(hex_int: int) -> int:
    return hex_int


_GREEN = 0x57F287
_RED = 0xED4245


async def _patch_message(settings: Settings, message_id: str, payload: dict) -> None:
    """PATCH a Discord channel message. Silently logs on failure."""
    url = f"{_DISCORD_API}/channels/{settings.discord_mod_notify_channel_id}/messages/{message_id}"
    headers = {"Authorization": f"Bot {settings.discord_token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(url, json=payload, headers=headers)
            resp.raise_for_status()
    except Exception as exc:
        log.warning("Could not update Discord mod message %s: %s", message_id, exc)


async def notify_approved(
    settings: Settings,
    message_id: str | None,
    request_id: int,
    pt_name: str,
    pt_identifier: str,
    serial_display: str,
    requester_discord_id: str,
    moderator_name: str,
) -> None:
    if not message_id:
        return
    embed = {
        "title": "✅ Request Approved",
        "description": f"Serial **{serial_display}** issued.",
        "color": _GREEN,
        "fields": [
            {"name": "Request ID", "value": f"`#{request_id}`", "inline": True},
            {"name": "Type", "value": f"{pt_name} (`{pt_identifier}`)", "inline": True},
            {"name": "Requester", "value": f"<@{requester_discord_id}>", "inline": True},
            {"name": "Reviewed By", "value": moderator_name, "inline": True},
        ],
        "footer": {"text": "Serial System"},
    }
    await _patch_message(settings, message_id, {"embeds": [embed], "components": []})


async def notify_rejected(
    settings: Settings,
    message_id: str | None,
    request_id: int,
    pt_name: str,
    pt_identifier: str,
    requester_discord_id: str,
    reason: str | None,
    moderator_name: str,
) -> None:
    if not message_id:
        return
    fields = [
        {"name": "Request ID", "value": f"`#{request_id}`", "inline": True},
        {"name": "Type", "value": f"{pt_name} (`{pt_identifier}`)", "inline": True},
        {"name": "Requester", "value": f"<@{requester_discord_id}>", "inline": True},
    ]
    if reason:
        fields.append({"name": "Reason", "value": reason, "inline": False})
    fields.append({"name": "Reviewed By", "value": moderator_name, "inline": True})

    embed = {
        "title": "❌ Request Rejected",
        "color": _RED,
        "fields": fields,
        "footer": {"text": "Serial System"},
    }
    await _patch_message(settings, message_id, {"embeds": [embed], "components": []})
