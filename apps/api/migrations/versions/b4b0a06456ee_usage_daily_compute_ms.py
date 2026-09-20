"""usage_daily compute_ms

Revision ID: b4b0a06456ee
Revises: fd79c1bbd68b
Create Date: 2026-09-20 14:27:01.351826
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b4b0a06456ee'
down_revision = 'fd79c1bbd68b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default, or this fails on any table that already has rows —
    # which is every deployment that has ever run a job.
    op.add_column(
        "usage_daily",
        sa.Column("compute_ms", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("usage_daily", "compute_ms")
