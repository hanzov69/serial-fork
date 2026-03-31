"""
Serial Fork Discord bot entry point.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import Settings
from shared.database import bootstrap_owner, get_config, get_session, init_engine

log = logging.getLogger(__name__)


class BBSerialBot(commands.Bot):
    def __init__(self, settings: Settings):
        self.settings = settings
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        from bot.cogs.serials import SerialsCog
        from bot.cogs.admin import AdminCog
        from bot.cogs.listeners import ListenersCog
        from bot.cogs.housekeeping import HousekeepingCog

        await self.add_cog(SerialsCog(self))
        await self.add_cog(AdminCog(self))
        await self.add_cog(ListenersCog(self))
        await self.add_cog(HousekeepingCog(self))

        if self.settings.sync_commands:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash commands synced to guild %d", self.settings.discord_guild_id)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="serial requests",
            )
        )


async def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    config_path = os.environ.get("CONFIG_PATH", "config.toml")
    settings = Settings.load(config_path)

    init_engine(settings.db_path)

    # Run Alembic migrations before starting
    _run_migrations(settings.db_path)

    # Load any runtime overrides stored in the database
    async with get_session() as session:
        db_delimiter = await get_config(session, "serial_delimiter")
    if db_delimiter is not None:
        try:
            Settings._validate_serial_delimiter(db_delimiter)
            settings.serial_delimiter = db_delimiter
        except (ValueError, Exception):
            pass  # keep the config.toml default

    # Auto-create owner if configured and not yet present
    if settings.initial_owner_discord_id:
        await bootstrap_owner(
            settings.initial_owner_discord_id,
            settings.initial_owner_username,
        )

    bot = BBSerialBot(settings)
    async with bot:
        await bot.start(settings.discord_token)


def _run_migrations(db_path: str) -> None:
    """Run pending Alembic migrations synchronously at startup."""
    import subprocess

    env = os.environ.copy()
    env["DB_PATH"] = db_path
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("Migration failed:\n%s", result.stderr)
        raise RuntimeError("Database migration failed")
    log.info("Migrations complete")


if __name__ == "__main__":
    asyncio.run(main())
