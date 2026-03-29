"""Alembic migration environment.
Uses a synchronous SQLite connection (Alembic doesn't support async natively).
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

# Make shared importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_db_url() -> str:
    url = os.environ.get("DB_PATH") or os.environ.get("db_path") or "/data/bb_serial.db"
    # Alembic uses sync driver
    return f"sqlite:///{url}"


def run_migrations_offline() -> None:
    url = get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_db_url(), connect_args={"check_same_thread": False})
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
