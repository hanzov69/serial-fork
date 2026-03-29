"""Add rejection_reason to serial_requests

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-28 00:00:00.000000

Changes:
- serial_requests: add rejection_reason TEXT NULL
  (owner role requires no schema change — stored as string in users.role)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("serial_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("serial_requests", schema=None) as batch_op:
        batch_op.drop_column("rejection_reason")
