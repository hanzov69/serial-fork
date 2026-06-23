"""Make rescinded serial numbers reusable

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-22 00:00:00.000000

Replaces the plain unique(printer_type_id, serial_number) constraint on the
serials table with a PARTIAL unique index that only applies to active
(non-rescinded) rows. This lets a rescinded serial's number be reissued while
keeping the old rescinded row for history.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the unconditional unique constraint (requires a table rebuild on SQLite).
    with op.batch_alter_table("serials", schema=None, recreate="always") as batch_op:
        batch_op.drop_constraint("uq_serial_type_number", type_="unique")

    # Partial unique index: only one ACTIVE serial per (printer_type, serial_number).
    op.create_index(
        "uq_serial_type_number_active",
        "serials",
        ["printer_type_id", "serial_number"],
        unique=True,
        sqlite_where=sa.text("rescinded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_serial_type_number_active", table_name="serials")
    with op.batch_alter_table("serials", schema=None, recreate="always") as batch_op:
        batch_op.create_unique_constraint(
            "uq_serial_type_number", ["printer_type_id", "serial_number"]
        )
