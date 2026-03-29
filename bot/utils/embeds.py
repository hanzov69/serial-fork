"""
Discord embed builders for consistent bot message formatting.
"""
from __future__ import annotations

from datetime import datetime

import discord

from shared.config import Settings
from shared.models import PrinterType, Serial, SerialRequest, User


def _ts(dt: datetime | None) -> str:
    if dt is None:
        return "N/A"
    return f"<t:{int(dt.timestamp())}:R> (<t:{int(dt.timestamp())}:f>)"


def _pad(settings: Settings) -> int:
    return settings.serial_pad_width


def request_received(request: SerialRequest, printer_type: PrinterType, settings: Settings) -> discord.Embed:
    embed = discord.Embed(
        title="Serial Request Received",
        description=f"Your request for a **{printer_type.name}** serial has been submitted.",
        color=discord.Color.blurple(),
        timestamp=request.submitted_at,
    )
    embed.add_field(name="Request ID", value=f"`#{request.id}`", inline=True)
    embed.add_field(name="Printer Type", value=f"{printer_type.name} (`{printer_type.identifier}`)", inline=True)
    embed.add_field(name="Status", value="Pending review", inline=True)
    if request.post_url:
        embed.add_field(name="Forum Post", value=request.post_url, inline=False)
    embed.set_footer(text="Serial System")
    return embed


def request_pending_review(
    request: SerialRequest, printer_type: PrinterType, requester: User, settings: Settings
) -> discord.Embed:
    embed = discord.Embed(
        title="New Serial Request",
        color=discord.Color.yellow(),
        timestamp=request.submitted_at,
    )
    embed.add_field(name="Request ID", value=f"`#{request.id}`", inline=True)
    embed.add_field(name="Type", value=f"{printer_type.name} (`{printer_type.identifier}`)", inline=True)
    embed.add_field(name="Submitted By", value=f"<@{requester.discord_id}>", inline=True)
    if request.post_url:
        embed.add_field(name="Forum Post", value=request.post_url, inline=False)
    embed.set_footer(text=f"Use /approve {request.id} or /reject {request.id}")
    return embed


def serial_issued(serial: Serial, settings: Settings) -> discord.Embed:
    display = serial.display(_pad(settings))
    embed = discord.Embed(
        title=f"Serial Issued: {display}",
        description=(
            f"Congratulations! Your **{serial.printer_type.name}** has been assigned "
            f"serial number **{display}**."
        ),
        color=discord.Color.green(),
        timestamp=serial.issued_at,
    )
    embed.add_field(name="Serial Number", value=f"`{display}`", inline=True)
    embed.add_field(name="Printer Type", value=serial.printer_type.name, inline=True)
    embed.add_field(name="View Online", value="More details available in the web app", inline=False)
    embed.set_footer(text="Serial System")
    return embed


def request_rejected(
    request: SerialRequest, printer_type: PrinterType, reason: str | None, settings: Settings
) -> discord.Embed:
    embed = discord.Embed(
        title="Serial Request Rejected",
        description=f"Your request for a **{printer_type.name}** serial was not approved.",
        color=discord.Color.red(),
    )
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(
        name="Questions?",
        value="Contact a moderator if you believe this was an error.",
        inline=False,
    )
    embed.set_footer(text="Serial System")
    return embed


def serial_lookup(serial: Serial, settings: Settings) -> discord.Embed:
    display = serial.display(_pad(settings))
    color = discord.Color.green() if serial.is_active else discord.Color.dark_grey()
    embed = discord.Embed(title=f"Serial Lookup: {display}", color=color)
    embed.add_field(name="Serial Number", value=f"`{display}`", inline=True)
    embed.add_field(name="Status", value="Active" if serial.is_active else "Rescinded", inline=True)
    embed.add_field(name="Printer Type", value=serial.printer_type.name, inline=True)
    embed.add_field(name="Issued", value=_ts(serial.issued_at), inline=True)
    embed.add_field(name="Holder", value=f"<@{serial.holder.discord_id}>", inline=True)
    if not serial.is_active:
        embed.add_field(name="Rescinded", value=_ts(serial.rescinded_at), inline=True)
        if serial.rescind_reason:
            embed.add_field(name="Rescind Reason", value=serial.rescind_reason, inline=False)
    return embed


def request_mod_resolved_approved(
    request_id: int,
    printer_type: PrinterType,
    serial_display: str,
    requester: User,
    moderator_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="✅ Request Approved",
        description=f"Serial **{serial_display}** issued.",
        color=discord.Color.green(),
    )
    embed.add_field(name="Request ID", value=f"`#{request_id}`", inline=True)
    embed.add_field(name="Type", value=f"{printer_type.name} (`{printer_type.identifier}`)", inline=True)
    embed.add_field(name="Requester", value=f"<@{requester.discord_id}>", inline=True)
    embed.add_field(name="Reviewed By", value=moderator_name, inline=True)
    embed.set_footer(text="Serial System")
    return embed


def request_mod_resolved_rejected(
    request_id: int,
    printer_type: PrinterType,
    requester: User,
    reason: str | None,
    moderator_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="❌ Request Rejected",
        color=discord.Color.red(),
    )
    embed.add_field(name="Request ID", value=f"`#{request_id}`", inline=True)
    embed.add_field(name="Type", value=f"{printer_type.name} (`{printer_type.identifier}`)", inline=True)
    embed.add_field(name="Requester", value=f"<@{requester.discord_id}>", inline=True)
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Reviewed By", value=moderator_name, inline=True)
    embed.set_footer(text="Serial System")
    return embed


def queue_embed(requests: list[SerialRequest], settings: Settings) -> discord.Embed:
    embed = discord.Embed(
        title="Serial Request Queue",
        color=discord.Color.blurple(),
        description=f"**{len(requests)}** pending request(s)",
    )
    for req in requests[:20]:
        type_label = (
            f"{req.printer_type.name} (`{req.printer_type.identifier}`)"
            if req.printer_type else "Unknown"
        )
        embed.add_field(
            name=f"#{req.id} — {type_label}",
            value=f"By <@{req.requester.discord_id}> · {_ts(req.submitted_at)}",
            inline=False,
        )
    if len(requests) > 20:
        embed.set_footer(text=f"Showing first 20 of {len(requests)} requests")
    return embed
