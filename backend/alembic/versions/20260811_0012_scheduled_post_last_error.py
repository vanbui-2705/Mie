"""scheduled post last error

Revision ID: 20260811_0012
Revises: 20260811_0011
Create Date: 2026-08-11

A schedule that cannot fire — every target gone or no longer owned — used to
keep retrying every minute with nothing to show for it. It now stops and says
why, which needs somewhere to put the reason.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260811_0012"
down_revision = "20260811_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_posts",
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheduled_posts", "last_error")
