"""
Housekeeping cog: scheduled tasks for database maintenance.

Tasks:
- Daily purge of rejected serial requests older than `rejected_request_purge_days` days.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from discord.ext import commands, tasks
from sqlalchemy import delete, select

from shared.database import get_session
from shared.models import RequestStatus, SerialRequest

log = logging.getLogger(__name__)


class HousekeepingCog(commands.Cog, name="Housekeeping"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._purge_loop.start()

    def cog_unload(self) -> None:
        self._purge_loop.cancel()

    @property
    def settings(self):
        return self.bot.settings

    @tasks.loop(hours=24)
    async def _purge_loop(self) -> None:
        purge_days = self.settings.rejected_request_purge_days
        if purge_days <= 0:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=purge_days)

        async with get_session() as session:
            result = await session.execute(
                select(SerialRequest)
                .where(SerialRequest.status == RequestStatus.rejected)
                .where(SerialRequest.reviewed_at < cutoff)
            )
            old_requests = list(result.scalars())

            if not old_requests:
                return

            ids = [r.id for r in old_requests]
            await session.execute(
                delete(SerialRequest).where(SerialRequest.id.in_(ids))
            )
            log.info(
                "Housekeeping: purged %d rejected request(s) older than %d days (IDs: %s)",
                len(ids),
                purge_days,
                ids,
            )

    @_purge_loop.before_loop
    async def _before_purge(self) -> None:
        await self.bot.wait_until_ready()
