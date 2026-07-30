"""clip retention: last_seen_at / purged_at (Flow Studio auto-purge)

Revision ID: 20260729_0009
Revises: 20260724_0008
Create Date: 2026-07-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260729_0009'
down_revision: Union[str, None] = '20260724_0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'clip_jobs',
        sa.Column('last_seen_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )
    op.add_column(
        'clip_jobs',
        sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True),
    )
    # The sweeper scans oldest-heartbeat-first among rows that still hold files.
    op.create_index(
        'idx_clip_jobs_sweep', 'clip_jobs', ['purged_at', 'last_seen_at'], unique=False,
    )
    # clip_job_status / clip_status are VARCHAR (native_enum=False), so the new
    # CANCELLED / PURGED members need no type change.


def downgrade() -> None:
    op.drop_index('idx_clip_jobs_sweep', table_name='clip_jobs')
    op.drop_column('clip_jobs', 'purged_at')
    op.drop_column('clip_jobs', 'last_seen_at')
