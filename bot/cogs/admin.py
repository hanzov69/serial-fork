"""
Admin commands: /addmod, /removemod, /rescind,
                /reserve, /unreserve, /reservations,
                /assign,
                /addprinter, /printers
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

from bot.utils.checks import is_admin, is_owner
from bot.cogs.serials import _channel_id, _printer_type_autocomplete
from shared.database import get_session, is_serial_number_free, next_serial_number
from shared.models import (
    AuditLog,
    PrinterType,
    RequestStatus,
    Serial,
    SerialRequest,
    SerialReservation,
    User,
    UserRole,
)

log = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9]{1,3}$")


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def settings(self):
        return self.bot.settings

    # ------------------------------------------------------------------
    # /addmod / /removemod
    # ------------------------------------------------------------------

    @app_commands.command(name="addmod", description="[Admin] Grant moderator role to a user")
    @app_commands.describe(member="The Discord member to promote")
    @is_admin()
    async def cmd_addmod(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        admin = await _get_or_create_user(interaction.user)

        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == str(member.id))
            )
            target = result.scalar_one_or_none()
            if target is None:
                target = User(
                    discord_id=str(member.id),
                    username=member.display_name,
                    avatar_hash=member.avatar.key if member.avatar else None,
                    role=UserRole.moderator,
                )
                session.add(target)
                await session.flush()
            elif target.role == UserRole.owner:
                await interaction.followup.send(f"{member.mention} is the Owner — their role cannot be changed.", ephemeral=True)
                return
            elif target.role == UserRole.moderator:
                await interaction.followup.send(f"{member.mention} is already a moderator.", ephemeral=True)
                return
            elif target.role == UserRole.admin:
                await interaction.followup.send(f"{member.mention} is already an admin.", ephemeral=True)
                return
            else:
                target.role = UserRole.moderator

            session.add(AuditLog(actor_id=admin.id, action="promote", target_user_id=target.id, details="new_role=moderator"))

        await interaction.followup.send(f"{member.mention} has been granted **moderator** role.", ephemeral=True)

    @app_commands.command(name="removemod", description="[Admin] Remove moderator role from a user")
    @app_commands.describe(member="The Discord member to demote")
    @is_admin()
    async def cmd_removemod(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        admin = await _get_or_create_user(interaction.user)

        async with get_session() as session:
            result = await session.execute(select(User).where(User.discord_id == str(member.id)))
            target = result.scalar_one_or_none()

            if target is None or target.role != UserRole.moderator:
                await interaction.followup.send(f"{member.mention} is not a moderator.", ephemeral=True)
                return

            if target.role == UserRole.owner:
                await interaction.followup.send(f"{member.mention} is the Owner — their role cannot be changed.", ephemeral=True)
                return

            target.role = UserRole.user
            session.add(AuditLog(actor_id=admin.id, action="demote", target_user_id=target.id, details="new_role=user"))

        await interaction.followup.send(f"{member.mention}'s moderator role has been removed.", ephemeral=True)

    # ------------------------------------------------------------------
    # /transferownership
    # ------------------------------------------------------------------

    @app_commands.command(
        name="transferownership",
        description="[Owner] Transfer the Owner role to another admin, reducing yourself to admin",
    )
    @app_commands.describe(member="The admin to promote to Owner")
    @is_owner()
    async def cmd_transferownership(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        current_owner = await _get_or_create_user(interaction.user)

        if member.id == interaction.user.id:
            await interaction.followup.send("You are already the Owner.", ephemeral=True)
            return

        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == str(member.id))
            )
            target = result.scalar_one_or_none()

            if target is None or not target.is_admin:
                await interaction.followup.send(
                    f"{member.mention} must already be an admin to receive the Owner role.",
                    ephemeral=True,
                )
                return

            # Atomically swap roles
            result_owner = await session.execute(
                select(User).where(User.id == current_owner.id)
            )
            owner_row = result_owner.scalar_one()
            owner_row.role = UserRole.admin
            target.role = UserRole.owner

            session.add(AuditLog(
                actor_id=current_owner.id,
                action="promote",
                target_user_id=target.id,
                details=f"ownership_transfer: {current_owner.username} → {target.username}",
            ))

        await interaction.followup.send(
            f"Ownership transferred to {member.mention}. You are now an **admin**.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /rescind
    # ------------------------------------------------------------------

    @app_commands.command(name="rescind", description="[Admin] Rescind an issued serial number")
    @app_commands.describe(
        printer_type="The printer type identifier (e.g. BBP, CC)",
        serial_number="The numeric part of the serial to rescind",
        reason="Reason for rescinding",
    )
    @app_commands.autocomplete(printer_type=_printer_type_autocomplete)
    @is_admin()
    async def cmd_rescind(
        self,
        interaction: discord.Interaction,
        printer_type: str,
        serial_number: int,
        reason: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        admin = await _get_or_create_user(interaction.user)

        async with get_session() as session:
            result = await session.execute(
                select(Serial)
                .join(PrinterType, Serial.printer_type_id == PrinterType.id)
                .where(PrinterType.identifier == printer_type.upper())
                .where(Serial.serial_number == serial_number)
                .options(selectinload(Serial.printer_type))
            )
            serial = result.scalar_one_or_none()

            if serial is None:
                await interaction.followup.send(
                    f"No serial found for `{printer_type.upper()}-{serial_number:03d}`.", ephemeral=True
                )
                return

            if not serial.is_active:
                await interaction.followup.send(
                    f"Serial `{serial.display(self.settings.serial_pad_width)}` is already rescinded.",
                    ephemeral=True,
                )
                return

            serial.rescinded_at = datetime.now(timezone.utc)
            serial.rescinded_by_id = admin.id
            serial.rescind_reason = reason
            session.add(AuditLog(actor_id=admin.id, action="rescind", serial_id=serial.id, details=f"reason={reason}"))
            display = serial.display(self.settings.serial_pad_width)

        await interaction.followup.send(f"Serial **{display}** has been rescinded.", ephemeral=True)

    # ------------------------------------------------------------------
    # /reserve / /unreserve / /reservations
    # ------------------------------------------------------------------

    @app_commands.command(name="reserve", description="[Admin] Reserve a serial number so it won't be auto-assigned")
    @app_commands.describe(
        printer_type="The printer type (e.g. BBP, CC)",
        serial_number="The serial number to reserve",
        reason="Why this number is being reserved (optional)",
    )
    @app_commands.autocomplete(printer_type=_printer_type_autocomplete)
    @is_admin()
    async def cmd_reserve(
        self,
        interaction: discord.Interaction,
        printer_type: str,
        serial_number: int,
        reason: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        admin = await _get_or_create_user(interaction.user)

        async with get_session() as session:
            pt = await session.scalar(
                select(PrinterType).where(PrinterType.identifier == printer_type.upper())
            )
            if pt is None:
                await interaction.followup.send(f"Unknown printer type `{printer_type}`.", ephemeral=True)
                return

            if not await is_serial_number_free(session, pt.id, serial_number):
                await interaction.followup.send(
                    f"`{pt.format_serial(serial_number, self.settings.serial_pad_width)}` is already issued.",
                    ephemeral=True,
                )
                return

            existing = await session.scalar(
                select(SerialReservation)
                .where(SerialReservation.printer_type_id == pt.id)
                .where(SerialReservation.serial_number == serial_number)
            )
            if existing:
                await interaction.followup.send(
                    f"`{pt.format_serial(serial_number, self.settings.serial_pad_width)}` is already reserved.",
                    ephemeral=True,
                )
                return

            session.add(SerialReservation(
                printer_type_id=pt.id,
                serial_number=serial_number,
                reason=reason,
                reserved_by_id=admin.id,
            ))
            display = pt.format_serial(serial_number, self.settings.serial_pad_width)

        msg = f"Reserved **{display}**."
        if reason:
            msg += f" Reason: {reason}"
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="unreserve", description="[Admin] Release a reserved serial number back into rotation")
    @app_commands.describe(
        printer_type="The printer type (e.g. BBP, CC)",
        serial_number="The serial number to unreserve",
    )
    @app_commands.autocomplete(printer_type=_printer_type_autocomplete)
    @is_admin()
    async def cmd_unreserve(
        self,
        interaction: discord.Interaction,
        printer_type: str,
        serial_number: int,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        async with get_session() as session:
            pt = await session.scalar(
                select(PrinterType).where(PrinterType.identifier == printer_type.upper())
            )
            if pt is None:
                await interaction.followup.send(f"Unknown printer type `{printer_type}`.", ephemeral=True)
                return

            result = await session.execute(
                select(SerialReservation)
                .where(SerialReservation.printer_type_id == pt.id)
                .where(SerialReservation.serial_number == serial_number)
            )
            reservation = result.scalar_one_or_none()
            if reservation is None:
                await interaction.followup.send(
                    f"`{pt.format_serial(serial_number, self.settings.serial_pad_width)}` is not reserved.",
                    ephemeral=True,
                )
                return

            await session.delete(reservation)
            display = pt.format_serial(serial_number, self.settings.serial_pad_width)

        await interaction.followup.send(f"Reservation for **{display}** removed.", ephemeral=True)

    @app_commands.command(name="reservations", description="[Admin] List all reserved serial numbers")
    @is_admin()
    async def cmd_reservations(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        async with get_session() as session:
            result = await session.execute(
                select(SerialReservation)
                .options(
                    selectinload(SerialReservation.printer_type),
                    selectinload(SerialReservation.reserved_by),
                )
                .order_by(SerialReservation.printer_type_id, SerialReservation.serial_number)
            )
            reservations = list(result.scalars())

        if not reservations:
            await interaction.followup.send("No serial numbers are currently reserved.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Reserved Serial Numbers",
            color=discord.Color.orange(),
            description=f"**{len(reservations)}** reserved",
        )
        pad = self.settings.serial_pad_width
        for r in reservations[:25]:
            display = r.printer_type.format_serial(r.serial_number, pad)
            embed.add_field(
                name=display,
                value=f"{r.reason or '*(no reason)*'} — {r.reserved_by.username}",
                inline=False,
            )
        if len(reservations) > 25:
            embed.set_footer(text=f"Showing first 25 of {len(reservations)}")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /assign
    # ------------------------------------------------------------------

    @app_commands.command(
        name="assign",
        description="[Admin] Approve a pending request and assign a specific serial number",
    )
    @app_commands.describe(
        request_id="The pending request ID",
        serial_number="The specific serial number to assign (must not be already issued)",
    )
    @is_admin()
    async def cmd_assign(
        self,
        interaction: discord.Interaction,
        request_id: int,
        serial_number: int,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        admin = await _get_or_create_user(interaction.user)

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

            if not await is_serial_number_free(session, request.printer_type_id, serial_number):
                pt = request.printer_type
                await interaction.followup.send(
                    f"`{pt.format_serial(serial_number, self.settings.serial_pad_width)}` is already issued.",
                    ephemeral=True,
                )
                return

            # Remove reservation for this slot if one exists
            existing_res = await session.scalar(
                select(SerialReservation)
                .where(SerialReservation.printer_type_id == request.printer_type_id)
                .where(SerialReservation.serial_number == serial_number)
            )
            if existing_res:
                await session.delete(existing_res)

            request.status = RequestStatus.approved
            request.reviewed_at = datetime.now(timezone.utc)
            request.reviewed_by_id = admin.id

            serial = Serial(
                printer_type_id=request.printer_type_id,
                serial_number=serial_number,
                request_id=request.id,
                holder_id=request.requester_id,
                issued_by_id=admin.id,
            )
            session.add(serial)
            session.add(AuditLog(
                actor_id=admin.id,
                action="approve",
                target_user_id=request.requester_id,
                details=f"request_id={request_id}, assigned={request.printer_type.identifier}-{serial_number}",
            ))
            await session.flush()

            serial_db_id = serial.id
            printer_type = request.printer_type
            requester = request.requester

        display = printer_type.format_serial(serial_number, self.settings.serial_pad_width)
        await interaction.followup.send(
            f"Assigned **{display}** to request `#{request_id}`.", ephemeral=True
        )

        from bot.utils.embeds import serial_issued
        async with get_session() as session:
            result = await session.execute(
                select(Serial)
                .where(Serial.id == serial_db_id)
                .options(selectinload(Serial.printer_type), selectinload(Serial.holder), selectinload(Serial.issued_by))
            )
            serial_obj = result.scalar_one()

        embed = serial_issued(serial_obj, self.settings)
        try:
            user_obj = await self.bot.fetch_user(int(requester.discord_id))
            await user_obj.send(embed=embed)
        except discord.HTTPException:
            log.warning("Could not DM requester %s", requester.discord_id)

    # ------------------------------------------------------------------
    # /addprinter / /printers
    # ------------------------------------------------------------------

    @app_commands.command(name="addprinter", description="[Admin] Create a new printer type")
    @app_commands.describe(
        identifier="1–3 character unique identifier (e.g. BBP). Will be uppercased.",
        name="Full display name (e.g. 'BabyBelt Pro')",
        description="Optional description of this printer type",
    )
    @is_admin()
    async def cmd_addprinter(
        self,
        interaction: discord.Interaction,
        identifier: str,
        name: str,
        description: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        identifier = identifier.upper().strip()

        if not _IDENTIFIER_RE.match(identifier):
            await interaction.followup.send(
                "Identifier must be 1–3 alphanumeric characters (e.g. `BB`, `BBP`, `CC`).",
                ephemeral=True,
            )
            return

        admin = await _get_or_create_user(interaction.user)

        async with get_session() as session:
            # Check uniqueness
            existing_id = await session.scalar(
                select(PrinterType).where(PrinterType.identifier == identifier)
            )
            if existing_id:
                await interaction.followup.send(
                    f"A printer type with identifier `{identifier}` already exists.", ephemeral=True
                )
                return

            existing_name = await session.scalar(
                select(PrinterType).where(PrinterType.name == name.strip())
            )
            if existing_name:
                await interaction.followup.send(
                    f"A printer type named **{name}** already exists.", ephemeral=True
                )
                return

        # Auto-create a forum tag for this printer type.
        tag_id: str | None = None
        forum_channel_id = await _channel_id("discord_forum_channel_id", self.settings.discord_forum_channel_id)
        forum_channel = self.bot.get_channel(forum_channel_id)
        if isinstance(forum_channel, discord.ForumChannel):
            try:
                new_tag = discord.ForumTag(name=name.strip())
                updated = await forum_channel.edit(
                    available_tags=list(forum_channel.available_tags) + [new_tag]
                )
                for tag in updated.available_tags:
                    if tag.name == name.strip():
                        tag_id = str(tag.id)
                if tag_id is None:
                    log.warning("Created forum tag for '%s' but couldn't find its ID in the response", name.strip())
            except discord.HTTPException as exc:
                log.warning("Could not create forum tag for '%s': %s", name.strip(), exc)
        else:
            log.warning("Forum channel %d not found or not a ForumChannel — skipping tag creation", forum_channel_id)

        async with get_session() as session:
            pt = PrinterType(
                identifier=identifier,
                name=name.strip(),
                description=description,
                is_active=True,
                created_by_id=admin.id,
                discord_tag_id=tag_id,
            )
            session.add(pt)

        tag_note = f" (forum tag ID: `{tag_id}`)" if tag_id else " ⚠️ forum tag could not be created — set it manually in the Config page"
        await interaction.followup.send(
            f"Printer type **{name}** (`{identifier}`) created successfully.{tag_note}", ephemeral=True
        )
        log.info("Admin %s created printer type %s (%s) tag_id=%s", interaction.user, name, identifier, tag_id)

    @app_commands.command(name="printers", description="List all printer types")
    async def cmd_printers(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        async with get_session() as session:
            result = await session.execute(
                select(PrinterType).order_by(PrinterType.identifier)
            )
            types = list(result.scalars())

        if not types:
            await interaction.followup.send("No printer types configured.", ephemeral=True)
            return

        embed = discord.Embed(title="Printer Types", color=discord.Color.blurple())
        for pt in types:
            status = "Active" if pt.is_active else "Inactive"
            embed.add_field(
                name=f"`{pt.identifier}` — {pt.name}",
                value=f"{pt.description or '*(no description)*'} · {status}",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=False)


async def _get_or_create_user(discord_user: discord.User | discord.Member) -> User:
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
        return user
