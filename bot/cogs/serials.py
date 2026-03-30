"""
Core serial number commands: /request, /approve, /reject, /lookup, /queue
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.utils.checks import is_moderator
from bot.utils.embeds import (
    queue_embed,
    request_mod_resolved_approved,
    request_mod_resolved_rejected,
    request_pending_review,
    request_received,
    request_rejected,
    serial_issued,
    serial_lookup,
)
from shared.database import get_session, next_serial_number
from shared.models import (
    AuditLog,
    PrinterType,
    RequestStatus,
    Serial,
    SerialRequest,
    User,
)

log = logging.getLogger(__name__)

# Matches https://discord.com/channels/{guild}/{channel}/{message}
_DISCORD_MSG_RE = re.compile(
    r"https?://(?:www\.)?discord\.com/channels/\d+/(\d+)/(\d+)"
)


async def _check_post_media(
    bot: commands.Bot, post_url: str
) -> tuple[bool, str | None]:
    """
    Fetch the linked Discord message and check for image/video content.

    Returns (has_media, warning).
    - has_media=True  → at least one image or video found, good to go.
    - has_media=False, warning=None → post is accessible but has no media.
    - has_media=False, warning=str → couldn't fetch the post; warning is
      shown to mods so they can check manually.
    """
    match = _DISCORD_MSG_RE.search(post_url)
    if not match:
        return False, "URL doesn't look like a direct Discord message link (expected discord.com/channels/…)."

    channel_id, message_id = int(match.group(1)), int(match.group(2))

    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        return False, "Post not found — the link may be incorrect or the post was deleted."
    except discord.Forbidden:
        return False, "Bot cannot access that channel — manual media check required."
    except discord.HTTPException as exc:
        log.warning("Media check failed for %s: %s", post_url, exc)
        return False, "Could not reach the post right now — manual media check required."

    # Check direct attachments (images / videos)
    for att in message.attachments:
        ct = att.content_type or ""
        if ct.startswith("image/") or ct.startswith("video/"):
            return True, None

    # Check embeds (linked images, GIFs, videos)
    for embed in message.embeds:
        if embed.type in ("image", "video", "gifv"):
            return True, None
        if embed.image or embed.video:
            return True, None

    return False, None


# ------------------------------------------------------------------
# Autocomplete helpers
# ------------------------------------------------------------------

async def _printer_type_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete active printer types by name or identifier."""
    async with get_session() as session:
        result = await session.execute(
            select(PrinterType).where(PrinterType.is_active == True).order_by(PrinterType.name)
        )
        types = result.scalars().all()

    return [
        app_commands.Choice(
            name=f"{pt.name} ({pt.identifier})",
            value=pt.identifier,
        )
        for pt in types
        if not current
        or current.lower() in pt.name.lower()
        or current.lower() in pt.identifier.lower()
    ][:25]


async def _get_or_create_user(discord_user: discord.User | discord.Member) -> User:
    """Fetch user from DB, creating a new record if this is their first interaction."""
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.discord_id == str(discord_user.id))
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                discord_id=str(discord_user.id),
                username=discord_user.display_name,
                avatar_hash=discord_user.avatar.key if discord_user.avatar else None,
            )
            session.add(user)
            await session.flush()
            await session.refresh(user)
        else:
            user.username = discord_user.display_name
            if discord_user.avatar:
                user.avatar_hash = discord_user.avatar.key
        return user


class SerialsCog(commands.Cog, name="Serials"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def settings(self):
        return self.bot.settings

    # ------------------------------------------------------------------
    # /request
    # ------------------------------------------------------------------

    @app_commands.command(name="request", description="Submit a serial number request for your build")
    @app_commands.describe(
        printer_type="The type of printer you built",
        post_url="Link to your Discord forum post showing the completed build (must be a discord.com URL)",
    )
    @app_commands.autocomplete(printer_type=_printer_type_autocomplete)
    async def cmd_request(
        self,
        interaction: discord.Interaction,
        printer_type: str,
        post_url: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if "discord.com" not in post_url:
            await interaction.followup.send(
                "The post URL must be a Discord link (must contain `discord.com`).",
                ephemeral=True,
            )
            return

        # Check that the linked post actually contains photos or videos.
        has_media, media_warning = await _check_post_media(self.bot, post_url)
        if media_warning:
            # Couldn't fetch the post — allow submission but flag it for mods.
            log.warning("Media check skipped for request (url=%s): %s", post_url, media_warning)
        elif not has_media:
            await interaction.followup.send(
                "Your forum post doesn't appear to contain any photos or videos of your build.\n"
                "Please add build photos or a video to your post and then re-submit.",
                ephemeral=True,
            )
            return

        user = await _get_or_create_user(interaction.user)

        # Resolve the printer type by identifier
        async with get_session() as session:
            pt_result = await session.execute(
                select(PrinterType)
                .where(PrinterType.identifier == printer_type.upper())
                .where(PrinterType.is_active == True)
            )
            pt = pt_result.scalar_one_or_none()

        if pt is None:
            await interaction.followup.send(
                f"Unknown printer type `{printer_type}`. Use the autocomplete to pick a valid type.",
                ephemeral=True,
            )
            return

        async with get_session() as session:
            request = SerialRequest(
                requester_id=user.id,
                printer_type_id=pt.id,
                channel_id=str(interaction.channel_id),
                post_url=post_url,
            )
            session.add(request)
            await session.flush()
            await session.refresh(request)
            request_id = request.id

        embed_confirm = request_received(request, pt, self.settings)
        await interaction.followup.send(embed=embed_confirm, ephemeral=True)

        mod_channel = self.bot.get_channel(self.settings.discord_mod_notify_channel_id)
        if mod_channel:
            embed_mod = request_pending_review(request, pt, user, self.settings, media_warning=media_warning)
            view = _ReviewView(request_id=request_id, bot=self.bot)
            mod_msg = await mod_channel.send(embed=embed_mod, view=view)
            async with get_session() as session:
                req = await session.get(SerialRequest, request_id)
                req.discord_message_id = str(mod_msg.id)
        else:
            log.warning(
                "Mod notify channel %d not found", self.settings.discord_mod_notify_channel_id
            )

    # ------------------------------------------------------------------
    # /approve
    # ------------------------------------------------------------------

    @app_commands.command(name="approve", description="[Moderator] Approve a pending serial request")
    @app_commands.describe(request_id="The request ID to approve")
    @is_moderator()
    async def cmd_approve(
        self, interaction: discord.Interaction, request_id: int
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await _do_approve(interaction, request_id, self.bot)

    # ------------------------------------------------------------------
    # /reject
    # ------------------------------------------------------------------

    @app_commands.command(name="reject", description="[Moderator] Reject a pending serial request")
    @app_commands.describe(
        request_id="The request ID to reject",
        reason="Reason for rejection (shown to the requester)",
    )
    @is_moderator()
    async def cmd_reject(
        self,
        interaction: discord.Interaction,
        request_id: int,
        reason: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await _do_reject(interaction, request_id, reason, self.bot)

    # ------------------------------------------------------------------
    # /lookup
    # ------------------------------------------------------------------

    @app_commands.command(name="lookup", description="Look up a serial number")
    @app_commands.describe(
        printer_type="The printer type identifier (e.g. BBP, CC)",
        serial_number="The numeric part of the serial (e.g. 42 for BBP-042)",
    )
    @app_commands.autocomplete(printer_type=_printer_type_autocomplete)
    async def cmd_lookup(
        self,
        interaction: discord.Interaction,
        printer_type: str,
        serial_number: int,
    ) -> None:
        await interaction.response.defer()

        async with get_session() as session:
            result = await session.execute(
                select(Serial)
                .join(PrinterType, Serial.printer_type_id == PrinterType.id)
                .where(PrinterType.identifier == printer_type.upper())
                .where(Serial.serial_number == serial_number)
                .options(
                    selectinload(Serial.printer_type),
                    selectinload(Serial.holder),
                    selectinload(Serial.issued_by),
                    selectinload(Serial.rescinded_by),
                )
            )
            serial = result.scalar_one_or_none()

        if serial is None:
            display = f"{printer_type.upper()}-{serial_number:03d}"
            await interaction.followup.send(
                f"No serial found for `{display}`.", ephemeral=True
            )
            return

        embed = serial_lookup(serial, self.settings)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /resubmit
    # ------------------------------------------------------------------

    @app_commands.command(name="resubmit", description="Update and re-submit a rejected serial request")
    @app_commands.describe(
        request_id="The ID of your rejected request to re-submit",
        post_url="Updated Discord forum post URL (must contain discord.com, leave blank to keep existing)",
    )
    async def cmd_resubmit(
        self,
        interaction: discord.Interaction,
        request_id: int,
        post_url: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        user = await _get_or_create_user(interaction.user)

        async with get_session() as session:
            result = await session.execute(
                select(SerialRequest)
                .where(SerialRequest.id == request_id)
                .options(
                    selectinload(SerialRequest.printer_type),
                    selectinload(SerialRequest.requester),
                )
            )
            request = result.scalar_one_or_none()

            if request is None:
                await interaction.followup.send(f"Request `#{request_id}` not found.", ephemeral=True)
                return

            if request.requester_id != user.id:
                await interaction.followup.send(
                    "You can only re-submit your own requests.", ephemeral=True
                )
                return

            if request.status != RequestStatus.rejected:
                await interaction.followup.send(
                    f"Request `#{request_id}` cannot be re-submitted (status: `{request.status}`).",
                    ephemeral=True,
                )
                return

            # Update post_url if provided; validate discord.com and check for media
            if post_url is not None:
                if "discord.com" not in post_url:
                    await interaction.followup.send(
                        "The post URL must be a Discord link (must contain `discord.com`).",
                        ephemeral=True,
                    )
                    return
                has_media, media_warning = await _check_post_media(self.bot, post_url)
                if media_warning:
                    log.warning("Media check skipped for resubmit (url=%s): %s", post_url, media_warning)
                elif not has_media:
                    await interaction.followup.send(
                        "Your forum post doesn't appear to contain any photos or videos of your build.\n"
                        "Please add build photos or a video to your post and then re-submit.",
                        ephemeral=True,
                    )
                    return
                request.post_url = post_url
            else:
                media_warning = None

            # Reset to pending
            request.status = RequestStatus.pending
            request.rejection_reason = None
            request.reviewed_at = None
            request.reviewed_by_id = None
            request.submitted_at = datetime.now(timezone.utc)
            request.channel_id = str(interaction.channel_id)

            await session.flush()
            pt = request.printer_type
            request_id_val = request.id

        embed_confirm = request_received(request, pt, self.settings)
        await interaction.followup.send(
            f"Request `#{request_id_val}` has been re-submitted for review.",
            embed=embed_confirm,
            ephemeral=True,
        )

        mod_channel = self.bot.get_channel(self.settings.discord_mod_notify_channel_id)
        if mod_channel:
            embed_mod = request_pending_review(request, pt, user, self.settings, media_warning=media_warning)
            view = _ReviewView(request_id=request_id_val, bot=self.bot)
            mod_msg = await mod_channel.send(embed=embed_mod, view=view)
            async with get_session() as session:
                req = await session.get(SerialRequest, request_id_val)
                req.discord_message_id = str(mod_msg.id)

    # ------------------------------------------------------------------
    # /queue
    # ------------------------------------------------------------------

    @app_commands.command(name="queue", description="[Moderator] Show pending serial requests")
    @is_moderator()
    async def cmd_queue(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        async with get_session() as session:
            result = await session.execute(
                select(SerialRequest)
                .where(SerialRequest.status == RequestStatus.pending)
                .options(
                    selectinload(SerialRequest.requester),
                    selectinload(SerialRequest.printer_type),
                )
                .order_by(SerialRequest.submitted_at)
            )
            requests = list(result.scalars().all())

        embed = queue_embed(requests, self.settings)
        await interaction.followup.send(embed=embed, ephemeral=True)


# ------------------------------------------------------------------
# Approval / rejection helpers (shared by cog commands and buttons)
# ------------------------------------------------------------------

async def _do_approve(
    interaction: discord.Interaction, request_id: int, bot: commands.Bot
) -> None:
    settings = bot.settings
    moderator = await _get_or_create_user(interaction.user)

    async with get_session() as session:
        result = await session.execute(
            select(SerialRequest)
            .where(SerialRequest.id == request_id)
            .options(
                selectinload(SerialRequest.requester),
                selectinload(SerialRequest.printer_type),
            )
        )
        request = result.scalar_one_or_none()

        if request is None:
            await interaction.followup.send(f"Request `#{request_id}` not found.", ephemeral=True)
            return

        if request.status != RequestStatus.pending:
            await interaction.followup.send(
                f"Request `#{request_id}` is already `{request.status}`.", ephemeral=True
            )
            return

        serial_num = await next_serial_number(session, request.printer_type_id)

        request.status = RequestStatus.approved
        request.reviewed_at = datetime.now(timezone.utc)
        request.reviewed_by_id = moderator.id

        serial = Serial(
            printer_type_id=request.printer_type_id,
            serial_number=serial_num,
            request_id=request.id,
            holder_id=request.requester_id,
            issued_by_id=moderator.id,
        )
        session.add(serial)
        session.add(AuditLog(
            actor_id=moderator.id,
            action="approve",
            target_user_id=request.requester_id,
            details=f"request_id={request_id}, type={request.printer_type.identifier}, serial={serial_num}",
        ))
        await session.flush()
        await session.refresh(serial)

        serial_db_id = serial.id
        printer_type = request.printer_type
        requester = request.requester
        mod_message_id = request.discord_message_id

    async with get_session() as session:
        result = await session.execute(
            select(Serial)
            .where(Serial.id == serial_db_id)
            .options(
                selectinload(Serial.printer_type),
                selectinload(Serial.holder),
                selectinload(Serial.issued_by),
            )
        )
        serial = result.scalar_one()

    display = serial.display(settings.serial_pad_width)
    embed = serial_issued(serial, settings)
    await interaction.followup.send(
        f"Approved! Serial **{display}** issued.", ephemeral=True
    )

    try:
        requester_obj = await bot.fetch_user(int(requester.discord_id))
        await requester_obj.send(embed=embed)
    except discord.HTTPException:
        log.warning("Could not DM requester %s", requester.discord_id)

    if mod_message_id:
        mod_channel = bot.get_channel(settings.discord_mod_notify_channel_id)
        if mod_channel:
            try:
                mod_msg = await mod_channel.fetch_message(int(mod_message_id))
                resolved_embed = request_mod_resolved_approved(
                    request_id, printer_type, display, requester, interaction.user.display_name
                )
                await mod_msg.edit(embed=resolved_embed, view=None)
            except discord.HTTPException:
                log.warning("Could not update mod channel message for request %d", request_id)

    if printer_type.discord_role_id:
        try:
            guild = bot.get_guild(settings.discord_guild_id)
            if guild:
                member = guild.get_member(int(requester.discord_id))
                if member is None:
                    member = await guild.fetch_member(int(requester.discord_id))
                role = guild.get_role(int(printer_type.discord_role_id))
                if role and member:
                    await member.add_roles(role, reason=f"Serial {display} approved (request #{request_id})")
                else:
                    log.warning("Role %s or member %s not found for role assignment", printer_type.discord_role_id, requester.discord_id)
        except discord.HTTPException as exc:
            log.warning("Could not assign role %s to %s: %s", printer_type.discord_role_id, requester.discord_id, exc)


async def _do_reject(
    interaction: discord.Interaction,
    request_id: int,
    reason: str | None,
    bot: commands.Bot,
) -> None:
    moderator = await _get_or_create_user(interaction.user)

    async with get_session() as session:
        result = await session.execute(
            select(SerialRequest)
            .where(SerialRequest.id == request_id)
            .options(
                selectinload(SerialRequest.requester),
                selectinload(SerialRequest.printer_type),
            )
        )
        request = result.scalar_one_or_none()

        if request is None:
            await interaction.followup.send(f"Request `#{request_id}` not found.", ephemeral=True)
            return

        if request.status != RequestStatus.pending:
            await interaction.followup.send(
                f"Request `#{request_id}` is already `{request.status}`.", ephemeral=True
            )
            return

        request.status = RequestStatus.rejected
        request.reviewed_at = datetime.now(timezone.utc)
        request.reviewed_by_id = moderator.id
        request.rejection_reason = reason

        session.add(AuditLog(
            actor_id=moderator.id,
            action="reject",
            target_user_id=request.requester_id,
            details=f"request_id={request_id}, reason={reason}",
        ))
        printer_type = request.printer_type
        requester = request.requester
        mod_message_id = request.discord_message_id

    embed = request_rejected(request, printer_type, reason, bot.settings)
    await interaction.followup.send(f"Request `#{request_id}` rejected.", ephemeral=True)

    try:
        requester_obj = await bot.fetch_user(int(requester.discord_id))
        await requester_obj.send(embed=embed)
    except discord.HTTPException:
        log.warning("Could not DM requester %s", requester.discord_id)

    if mod_message_id:
        mod_channel = bot.get_channel(bot.settings.discord_mod_notify_channel_id)
        if mod_channel:
            try:
                mod_msg = await mod_channel.fetch_message(int(mod_message_id))
                resolved_embed = request_mod_resolved_rejected(
                    request_id, printer_type, requester, reason, interaction.user.display_name
                )
                await mod_msg.edit(embed=resolved_embed, view=None)
            except discord.HTTPException:
                log.warning("Could not update mod channel message for request %d", request_id)


# ------------------------------------------------------------------
# Interactive review buttons attached to mod notification embeds
# ------------------------------------------------------------------

class _ReviewView(discord.ui.View):
    def __init__(self, request_id: int, bot: commands.Bot):
        super().__init__(timeout=None)
        self.request_id = request_id
        self.bot = bot

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        from bot.utils.checks import _get_db_user
        user = await _get_db_user(str(interaction.user.id))
        if user is None or not user.is_moderator:
            await interaction.followup.send("You are not a moderator.", ephemeral=True)
            return

        await _do_approve(interaction, self.request_id, self.bot)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_RejectModal(self.request_id, self.bot, self))


class _RejectModal(discord.ui.Modal, title="Reject Serial Request"):
    reason = discord.ui.TextInput(
        label="Reason (shown to requester)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, request_id: int, bot: commands.Bot, view: _ReviewView):
        super().__init__()
        self.request_id = request_id
        self.bot = bot
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        from bot.utils.checks import _get_db_user
        user = await _get_db_user(str(interaction.user.id))
        if user is None or not user.is_moderator:
            await interaction.followup.send("You are not a moderator.", ephemeral=True)
            return

        await _do_reject(interaction, self.request_id, self.reason.value or None, self.bot)
