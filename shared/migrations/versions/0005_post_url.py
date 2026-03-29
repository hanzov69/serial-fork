"""Replace photo_url with post_url, drop notes from serial_requests

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-29 00:00:00.000000

Changes:
- serial_requests: rename photo_url -> post_url
- serial_requests: drop notes column
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("serial_requests", schema=None, recreate="always") as batch_op:
        batch_op.add_column(sa.Column("post_url", sa.Text(), nullable=True))
        batch_op.drop_column("photo_url")
        batch_op.drop_column("notes")


def downgrade() -> None:
    with op.batch_alter_table("serial_requests", schema=None, recreate="always") as batch_op:
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("photo_url", sa.Text(), nullable=True))
        batch_op.drop_column("post_url")
