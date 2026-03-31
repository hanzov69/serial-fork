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


async def create_forum_tag(
    settings: Settings,
    tag_name: str,
    channel_id: int | None = None,
) -> str | None:
    """
    Add a new available tag to the forum channel and return its snowflake ID.
    Fetches the current tag list, appends the new tag, PATCHes the channel,
    then returns the ID Discord assigned to it.  Returns None on failure.

    channel_id overrides settings.discord_forum_channel_id (use when the
    effective channel is stored as a DB config override).
    """
    effective_channel_id = channel_id or settings.discord_forum_channel_id
    channel_url = f"{_DISCORD_API}/channels/{effective_channel_id}"
    headers = {"Authorization": f"Bot {settings.discord_token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Fetch existing tags so we don't clobber them.
            get_resp = await client.get(channel_url, headers=headers)
            get_resp.raise_for_status()
            existing_tags = get_resp.json().get("available_tags", [])

            new_tags = existing_tags + [{"name": tag_name, "moderated": False}]
            patch_resp = await client.patch(
                channel_url,
                json={"available_tags": new_tags},
                headers=headers,
            )
            patch_resp.raise_for_status()

            updated_tags = patch_resp.json().get("available_tags", [])
            # Find the tag we just added by name (last match wins if duplicate names).
            tag_id = None
            for tag in updated_tags:
                if tag.get("name") == tag_name:
                    tag_id = str(tag["id"])
            return tag_id
    except Exception as exc:
        log.warning("Could not create forum tag '%s': %s", tag_name, exc)
        return None


async def assign_role(
    settings: Settings,
    discord_user_id: str,
    role_id: str,
) -> None:
    """Assign a Discord guild role to a user via the bot token. Logs on failure."""
    url = f"{_DISCORD_API}/guilds/{settings.discord_guild_id}/members/{discord_user_id}/roles/{role_id}"
    headers = {"Authorization": f"Bot {settings.discord_token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.put(url, headers=headers)
            if resp.status_code not in (200, 204):
                log.warning(
                    "Could not assign role %s to user %s: %s %s",
                    role_id, discord_user_id, resp.status_code, resp.text,
                )
    except Exception as exc:
        log.warning("Could not assign role %s to user %s: %s", role_id, discord_user_id, exc)


def _parse_thread_id(post_url: str) -> int | None:
    """Extract the thread/channel snowflake from a Discord jump URL."""
    import re
    m = re.search(r"discord\.com/channels/\d+/(\d+)", post_url)
    return int(m.group(1)) if m else None


async def post_thread_message(settings: Settings, post_url: str, content: str) -> None:
    """Post a plain-text message into the Discord forum thread identified by post_url."""
    thread_id = _parse_thread_id(post_url)
    if thread_id is None:
        log.warning("Could not parse thread ID from post_url: %s", post_url)
        return
    url = f"{_DISCORD_API}/channels/{thread_id}/messages"
    headers = {"Authorization": f"Bot {settings.discord_token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"content": content}, headers=headers)
            if resp.status_code not in (200, 201):
                log.warning("Could not post to thread %s: %s %s", thread_id, resp.status_code, resp.text)
    except Exception as exc:
        log.warning("Could not post to thread %s: %s", thread_id, exc)


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
