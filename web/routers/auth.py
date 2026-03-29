"""
Discord OAuth2 authentication routes.
Flow: /auth/login → Discord → /auth/callback → session set → redirect home
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import User
from web.deps import get_db, get_current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

DISCORD_API = "https://discord.com/api/v10"
DISCORD_OAUTH_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"


def _settings(request: Request):
    return request.app.state.settings


def _redirect_uri(settings) -> str:
    """Build the OAuth2 callback URI from web_base_url.

    web_base_url is the single source of truth for the public URL — include
    the port there if needed (e.g. http://localhost:8000).  Behind a reverse
    proxy the URL has no explicit port and none should be added.
    """
    return settings.web_base_url.rstrip("/") + "/auth/callback"


@router.get("/login")
async def login(request: Request):
    """Redirect the user to Discord's OAuth2 authorization page."""
    settings = _settings(request)
    redirect_uri = _redirect_uri(settings)
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify",
    }
    url = httpx.URL(DISCORD_OAUTH_URL, params=params)
    return RedirectResponse(str(url))


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth2 callback from Discord."""
    if error or not code:
        raise HTTPException(status_code=400, detail=f"OAuth2 error: {error or 'missing code'}")

    settings = _settings(request)
    redirect_uri = _redirect_uri(settings)

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            DISCORD_TOKEN_URL,
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            log.error("Token exchange failed: %s", token_resp.text)
            raise HTTPException(status_code=502, detail="Failed to exchange OAuth2 code")

        token_data = token_resp.json()
        access_token = token_data["access_token"]

        # Fetch user info from Discord
        user_resp = await client.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch Discord user info")

        discord_user = user_resp.json()

    discord_id = discord_user["id"]
    username = discord_user.get("global_name") or discord_user.get("username", "Unknown")
    avatar_hash = discord_user.get("avatar")

    # Upsert user in database
    result = await db.execute(select(User).where(User.discord_id == discord_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(discord_id=discord_id, username=username, avatar_hash=avatar_hash)
        db.add(user)
    else:
        user.username = username
        user.avatar_hash = avatar_hash

    await db.flush()

    # Store Discord ID in session (signed cookie via Starlette sessions)
    request.session["discord_user_id"] = discord_id

    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


@router.get("/me")
async def me(current_user: User | None = Depends(get_current_user)):
    if current_user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "discord_id": current_user.discord_id,
        "username": current_user.username,
        "role": current_user.role,
    }
