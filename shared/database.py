"""
Async SQLAlchemy engine and session factory.
Both the bot and web app import this module to get database access.
WAL mode is enabled on every connection for safe concurrent access.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _set_wal_mode(dbapi_conn, _connection_record):
    """Enable WAL journal mode for safe multi-process concurrent access."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_engine(db_path: str) -> None:
    """Initialize the engine. Call once at startup."""
    global _engine, _session_factory

    if db_path == ":memory:":
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,
        )
    else:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )

    event.listen(engine.sync_engine, "connect", _set_wal_mode)

    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)


def get_engine():
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_engine() first.")
    return _session_factory


async def next_serial_number(session: AsyncSession, printer_type_id: int) -> int:
    """
    Compute the next available serial number for a given printer type:
    the lowest positive integer that has no active serial and is not reserved.

    This fills earlier gaps in the sequence (e.g. left behind when a
    reservation is removed, when numbers were skipped, or when a serial was
    rescinded) before continuing past the current maximum, rather than only
    ever incrementing the highest issued number. Rescinded serials are kept
    for history but their numbers are free to reuse.

    Must be called within an open session so the read and the subsequent Serial
    insert happen in the same SQLite write transaction, preventing races.

    Each printer type has its own independent sequence: BBP-001 and CC-001
    are both serial_number=1, for different printer types.
    """
    from shared.models import Serial, SerialReservation  # avoid circular import

    issued_rows = await session.execute(
        select(Serial.serial_number)
        .where(Serial.printer_type_id == printer_type_id)
        .where(Serial.rescinded_at.is_(None))  # rescinded numbers are free to reuse
    )
    reserved_rows = await session.execute(
        select(SerialReservation.serial_number)
        .where(SerialReservation.printer_type_id == printer_type_id)
    )
    taken: set[int] = set(issued_rows.scalars().all()) | set(reserved_rows.scalars().all())

    candidate = 1
    while candidate in taken:
        candidate += 1

    return candidate


async def is_serial_number_free(
    session: AsyncSession, printer_type_id: int, serial_number: int
) -> bool:
    """
    Return True if the given (printer_type_id, serial_number) pair has no ACTIVE
    serial. Rescinded serials don't count — their number is free to reissue.
    BBP-042 and CC-042 are checked independently.
    """
    from shared.models import Serial

    existing = await session.scalar(
        select(Serial)
        .where(Serial.printer_type_id == printer_type_id)
        .where(Serial.serial_number == serial_number)
        .where(Serial.rescinded_at.is_(None))
    )
    return existing is None


async def bootstrap_owner(discord_id: str, username: str) -> None:
    """
    Ensure an Owner user exists. Called at startup when `initial_owner_discord_id` is set.
    Idempotent: does nothing if an owner already exists in the database.
    """
    import logging
    from shared.models import User, UserRole  # avoid circular import at module level

    log = logging.getLogger(__name__)

    async with get_session() as session:
        existing_owner = await session.scalar(
            select(User).where(User.role == UserRole.owner)
        )
        if existing_owner is not None:
            return  # owner already exists, nothing to do

        result = await session.execute(
            select(User).where(User.discord_id == discord_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            session.add(User(discord_id=discord_id, username=username, role=UserRole.owner))
            log.info("Bootstrap: created Owner user %s (%s)", username, discord_id)
        else:
            user.role = UserRole.owner
            log.info("Bootstrap: promoted existing user %s (%s) to Owner", user.username, discord_id)


async def get_config(session: AsyncSession, key: str) -> str | None:
    """Return the DB-stored override for a config key, or None if not set."""
    from shared.models import SystemConfig  # avoid circular import
    row = await session.get(SystemConfig, key)
    return row.value if row else None


async def set_config(session: AsyncSession, key: str, value: str | None) -> None:
    """Upsert a config key in the database."""
    from shared.models import SystemConfig  # avoid circular import
    row = await session.get(SystemConfig, key)
    if row is None:
        session.add(SystemConfig(key=key, value=value))
    else:
        row.value = value


async def get_serial_delimiter(fallback: str = "-") -> str:
    """Read the current serial delimiter from the DB, falling back to *fallback*."""
    async with get_session() as session:
        val = await get_config(session, "serial_delimiter")
    if val and len(val) == 1 and 0x21 <= ord(val) <= 0x7E and not val.isalnum():
        return val
    return fallback


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager yielding a database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
