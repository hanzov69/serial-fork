"""
Discord command permission checks backed by the database (not Discord roles).
"""
from __future__ import annotations

import discord
from discord import app_commands

from shared.database import get_session
from shared.models import User, UserRole


async def _get_db_user(discord_id: str) -> User | None:
    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.discord_id == discord_id)
        )
        return result.scalar_one_or_none()


def is_moderator():
    """Check that the invoking user has at least moderator role in the DB."""
    async def predicate(interaction: discord.Interaction) -> bool:
        user = await _get_db_user(str(interaction.user.id))
        if user is None or not user.is_moderator:
            raise app_commands.CheckFailure(
                "You need to be a serial moderator to use this command."
            )
        return True
    return app_commands.check(predicate)


def is_admin():
    """Check that the invoking user has admin (or owner) role in the DB."""
    async def predicate(interaction: discord.Interaction) -> bool:
        user = await _get_db_user(str(interaction.user.id))
        if user is None or not user.is_admin:
            raise app_commands.CheckFailure(
                "You need to be an administrator to use this command."
            )
        return True
    return app_commands.check(predicate)


def is_owner():
    """Check that the invoking user has the owner role in the DB."""
    async def predicate(interaction: discord.Interaction) -> bool:
        user = await _get_db_user(str(interaction.user.id))
        if user is None or not user.is_owner:
            raise app_commands.CheckFailure(
                "Only the Owner can use this command."
            )
        return True
    return app_commands.check(predicate)
