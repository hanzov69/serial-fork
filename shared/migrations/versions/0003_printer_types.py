"""Add printer_types; migrate Serial and SerialRequest to use type FK

Revision ID: 0003
Revises: 0002
Create Date: 2024-01-01 00:00:02.000000

Changes:
- Create printer_types table (no default types seeded; owners create their own)
- serial_requests: drop printer_model, add printer_type_id FK
- serials: drop printer_model, add printer_type_id FK + serial_number column,
           add unique(printer_type_id, serial_number)
- serial_reservations: drop old unique(serial_number), add printer_type_id FK,
                        add unique(printer_type_id, serial_number)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create printer_types
    # ------------------------------------------------------------------
    op.create_table(
        "printer_types",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("identifier", sa.String(length=3), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("identifier"),
    )

    # ------------------------------------------------------------------
    # 2. serial_requests: replace printer_model with printer_type_id
    # ------------------------------------------------------------------
    with op.batch_alter_table("serial_requests", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("printer_type_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_serial_requests_printer_type",
            "printer_types",
            ["printer_type_id"],
            ["id"],
        )

    # Now make it NOT NULL via batch rebuild
    with op.batch_alter_table("serial_requests", schema=None) as batch_op:
        batch_op.alter_column("printer_type_id", nullable=False)
        batch_op.drop_column("printer_model")

    # ------------------------------------------------------------------
    # 3. serials: replace printer_model with printer_type_id + serial_number
    # ------------------------------------------------------------------
    with op.batch_alter_table("serials", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("printer_type_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("serial_number", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_serials_printer_type",
            "printer_types",
            ["printer_type_id"],
            ["id"],
        )

    # Default existing rows: printer_type_id=1 (BB), serial_number mirrors old id
    with op.batch_alter_table("serials", schema=None) as batch_op:
        batch_op.alter_column("printer_type_id", nullable=False)
        batch_op.alter_column("serial_number", nullable=False)
        batch_op.create_unique_constraint(
            "uq_serial_type_number", ["printer_type_id", "serial_number"]
        )
        batch_op.drop_column("printer_model")

    # ------------------------------------------------------------------
    # 4. serial_reservations: add printer_type_id, replace unique constraint
    # ------------------------------------------------------------------
    with op.batch_alter_table("serial_reservations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("printer_type_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_reservations_printer_type",
            "printer_types",
            ["printer_type_id"],
            ["id"],
        )

    # Use recreate="always" so SQLite rebuilds the table without needing the
    # exact auto-generated name of the old unique(serial_number) constraint.
    with op.batch_alter_table("serial_reservations", schema=None, recreate="always") as batch_op:
        batch_op.alter_column("printer_type_id", nullable=False)
        batch_op.create_unique_constraint(
            "uq_reservation_type_number", ["printer_type_id", "serial_number"]
        )


def downgrade() -> None:
    with op.batch_alter_table("serial_reservations", schema=None) as batch_op:
        batch_op.drop_constraint("uq_reservation_type_number", type_="unique")
        batch_op.create_unique_constraint("uq_1", ["serial_number"])
        batch_op.drop_constraint("fk_reservations_printer_type", type_="foreignkey")
        batch_op.drop_column("printer_type_id")

    with op.batch_alter_table("serials", schema=None) as batch_op:
        batch_op.drop_constraint("uq_serial_type_number", type_="unique")
        batch_op.add_column(sa.Column("printer_model", sa.String(200), nullable=True))
        batch_op.drop_column("serial_number")
        batch_op.drop_constraint("fk_serials_printer_type", type_="foreignkey")
        batch_op.drop_column("printer_type_id")

    with op.batch_alter_table("serial_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("printer_model", sa.String(200), nullable=True))
        batch_op.drop_constraint("fk_serial_requests_printer_type", type_="foreignkey")
        batch_op.drop_column("printer_type_id")

    op.drop_table("printer_types")
