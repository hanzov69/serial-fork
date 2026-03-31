"""
FastAPI web application factory.
"""
from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import Settings
from shared.database import bootstrap_owner, init_engine
from web.routers import auth, serials, admin, user


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        config_path = os.environ.get("CONFIG_PATH", "config.toml")
        settings = Settings.load(config_path)

    app = FastAPI(
        title="Serial Fork",
        description="Serial number tracking for 3D printer makers",
        version="0.1.0",
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
    )

    # Session middleware (signed cookies via itsdangerous under the hood)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.web_secret_key,
        session_cookie="bb_session",
        max_age=30 * 24 * 60 * 60,  # 30 days
        https_only=not settings.debug,
        same_site="lax",
    )

    # Store shared state
    app.state.settings = settings

    # Templates
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    templates = Jinja2Templates(directory=templates_dir)
    templates.env.globals["settings"] = settings
    app.state.templates = templates

    # Static files
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Routers
    app.include_router(auth.router)
    app.include_router(serials.router)
    app.include_router(admin.router)
    app.include_router(user.router)

    app.state.site_theme = "babybelt"  # default until DB is read

    @app.on_event("startup")
    async def startup():
        init_engine(settings.db_path)
        _run_migrations(settings.db_path)
        if settings.initial_owner_discord_id:
            await bootstrap_owner(
                settings.initial_owner_discord_id,
                settings.initial_owner_username,
            )
        from shared.database import get_config, get_session
        async with get_session() as session:
            theme = await get_config(session, "site_theme")
        if theme in ("babybelt", "printcepts", "wave"):
            app.state.site_theme = theme

    return app


def _run_migrations(db_path: str) -> None:
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
        import logging
        logging.getLogger(__name__).error("Migration failed:\n%s", result.stderr)
        raise RuntimeError("Database migration failed")


# ASGI entry point for uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn
    config_path = os.environ.get("CONFIG_PATH", "config.toml")
    s = Settings.load(config_path)
    uvicorn.run("web.main:app", host=s.web_host, port=s.web_port, reload=s.debug)
