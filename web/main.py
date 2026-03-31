"""
FastAPI web application factory.
"""
from __future__ import annotations

import os
import re
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import Settings
from shared.database import bootstrap_owner, init_engine
from web.routers import auth, serials, admin, user


def _discover_themes(themes_dir: str) -> list[dict]:
    """
    Scan the themes directory for CSS files and parse their metadata comments.

    Each theme file should contain a comment block near the top with:
        theme-name: Display Name
        theme-id:   css-class-id
        theme-dot:  #hexcolor  (or a CSS gradient string for the picker dot)
        theme-description: Optional description
        theme-logo: /static/img/my-logo.png  (optional; overrides the default logo)

    Returns a list of dicts sorted by theme-name, with babybelt always first.
    """
    themes = []
    if not os.path.isdir(themes_dir):
        return themes
    for filename in sorted(os.listdir(themes_dir)):
        if not filename.endswith(".css"):
            continue
        path = os.path.join(themes_dir, filename)
        try:
            with open(path, encoding="utf-8") as f:
                header = f.read(512)  # only parse the top of the file
        except OSError:
            continue
        name    = re.search(r"\*\s*theme-name:\s*(.+)", header)
        tid     = re.search(r"\*\s*theme-id:\s*(.+)", header)
        dot     = re.search(r"\*\s*theme-dot:\s*(.+)", header)
        desc    = re.search(r"\*\s*theme-description:\s*(.+)", header)
        logo    = re.search(r"\*\s*theme-logo:\s*(.+)", header)
        if not (name and tid):
            continue
        themes.append({
            "id":          tid.group(1).strip(),
            "name":        name.group(1).strip(),
            "dot":         dot.group(1).strip() if dot else "#888888",
            "description": desc.group(1).strip() if desc else "",
            "logo":        logo.group(1).strip() if logo else None,
            "file":        filename,
        })
    # babybelt always first, rest alphabetical
    themes.sort(key=lambda t: (0 if t["id"] == "babybelt" else 1, t["name"]))
    return themes


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

    # Discover installed themes from the filesystem
    themes_dir = os.path.join(os.path.dirname(__file__), "static", "css", "themes")
    app.state.themes = _discover_themes(themes_dir)
    app.state.theme_logo_map = {t["id"]: t["logo"] for t in app.state.themes if t["logo"]}
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
            delimiter = await get_config(session, "serial_delimiter")
        valid_ids = {t["id"] for t in app.state.themes}
        if theme in valid_ids:
            app.state.site_theme = theme
        if delimiter and len(delimiter) == 1 and 0x21 <= ord(delimiter) <= 0x7E and not delimiter.isalnum():
            app.state.settings.serial_delimiter = delimiter

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
