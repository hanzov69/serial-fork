"""Add discord_tag_id to printer_types

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-30 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("printer_types", schema=None) as batch_op:
        batch_op.add_column(sa.Column("discord_tag_id", sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("printer_types", schema=None) as batch_op:
        batch_op.drop_column("discord_tag_id")
