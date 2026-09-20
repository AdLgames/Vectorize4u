"""overage cap opt-out

§8's cap is on by default, so the column is too. Existing rows need a
server_default: a NOT NULL column added without one fails outright on any
table that already has data, which is every table that matters.

Revision ID: 6b661963fe8e
Revises: 36a7dbf29ddb
Create Date: 2026-09-20 09:32:00.216320
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '6b661963fe8e'
down_revision = '36a7dbf29ddb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "overage_cap_opt_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "overage_cap_opt_out")
