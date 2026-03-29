"""
FastAPI dependency injection: database sessions and current user resolution.
"""
from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Cookie, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import get_session_factory
from shared.models import User, UserRole


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _get_serializer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(request.app.state.settings.web_secret_key)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the authenticated User or None if not logged in."""
    session_data = request.session.get("discord_user_id")
    if not session_data:
        return None

    result = await db.execute(
        select(User).where(User.discord_id == str(session_data))
    )
    return result.scalar_one_or_none()


async def require_user(
    current_user: User | None = Depends(get_current_user),
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def require_moderator(
    current_user: User = Depends(require_user),
) -> User:
    if not current_user.is_moderator:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Moderator access required")
    return current_user


async def require_admin(
    current_user: User = Depends(require_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


async def require_owner(
    current_user: User = Depends(require_user),
) -> User:
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required")
    return current_user


async def require_backup_access(
    request: Request,
    current_user: User = Depends(require_user),
) -> User:
    """Owner always; admins only when backup_allow_admin is enabled in config."""
    if current_user.is_owner:
        return current_user
    settings = request.app.state.settings
    if current_user.is_admin and settings.backup_allow_admin:
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Backup access denied")
