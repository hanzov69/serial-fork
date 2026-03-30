"""
Configuration management via Pydantic Settings.
Load order (highest → lowest priority):
  1. Environment variables
  2. .env file
  3. config.toml
  4. field defaults
"""
from __future__ import annotations

from typing import Any, Tuple, Type

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Default TOML path — overridden at load time via Settings.load(path)
        toml_file="config.toml",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        **kwargs: Any,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # env vars > .env file > config.toml > defaults
        env = kwargs.get("env_settings")
        dotenv = kwargs.get("dotenv_settings")
        return tuple(s for s in (env, dotenv, TomlConfigSettingsSource(settings_cls)) if s is not None)

    # --- Discord bot ---
    discord_token: str = Field(..., description="Discord bot token")
    discord_guild_id: int = Field(..., description="Guild (server) ID where bot operates")
    discord_forum_channel_id: int = Field(
        ..., description="Forum channel where users create build posts and use /request"
    )
    discord_mod_notify_channel_id: int = Field(
        ..., description="Channel where moderators receive approval notifications"
    )

    # --- Discord OAuth2 (web app) ---
    discord_client_id: str = Field(..., description="Discord application client ID")
    discord_client_secret: str = Field(..., description="Discord application client secret")

    # --- Web app ---
    web_secret_key: str = Field(..., description="Secret key for signing session cookies")
    web_base_url: str = Field(default="http://localhost:8000", description="Public base URL of the web app")
    web_host: str = Field(default="0.0.0.0")
    web_port: int = Field(default=8000)

    # --- Database ---
    db_path: str = Field(default="/data/serial_fork.db", description="Path to SQLite database file")

    # --- Serial display ---
    # serial_prefix is no longer a global setting — each PrinterType has its own identifier.
    # serial_pad_width controls the minimum digit width across all types.
    serial_pad_width: int = Field(
        default=3,
        description="Minimum digit width for serial numbers (3 → BBP-001; auto-expands beyond 999)",
    )

    # --- Bootstrap owner ---
    # Set once on first deploy; ignored after an owner exists in the DB.
    initial_owner_discord_id: str | None = Field(
        default=None,
        description="Discord ID of the first Owner. Auto-created on startup if no owner exists yet.",
    )
    initial_owner_username: str = Field(
        default="Owner",
        description="Display name for the auto-created owner (can be changed later).",
    )

    # --- Housekeeping ---
    rejected_request_purge_days: int = Field(
        default=30,
        description="Auto-delete rejected requests older than this many days (0 = disabled)",
    )

    # --- Backup ---
    backup_allow_admin: bool = Field(
        default=False,
        description="Allow admin-role users to download a database backup (owner can always download)",
    )

    # --- Dev helpers ---
    sync_commands: bool = Field(
        default=False,
        description="Sync Discord slash commands on bot startup (only needed after command changes)",
    )
    debug: bool = Field(default=False)

    @classmethod
    def load(cls, config_path: str = "config.toml") -> "Settings":
        """Load settings. Priority: env vars > .env > config.toml > defaults."""
        cls.model_config["toml_file"] = config_path
        return cls()
