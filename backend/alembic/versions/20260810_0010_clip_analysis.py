"""clip analysis cache

Revision ID: 20260810_0010
Revises: 20260729_0009
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '20260810_0010'
down_revision: Union[str, None] = '20260729_0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'clip_analysis',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('cache_key', sa.String(length=128), nullable=False),
        sa.Column(
            'owner_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('hit_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_clip_analysis_cache_key', 'clip_analysis', ['cache_key'], unique=True)
    op.create_index('ix_clip_analysis_owner_id', 'clip_analysis', ['owner_id'])
    # The sweeper expires entries oldest-use-first.
    op.create_index('ix_clip_analysis_last_used_at', 'clip_analysis', ['last_used_at'])


def downgrade() -> None:
    op.drop_index('ix_clip_analysis_last_used_at', table_name='clip_analysis')
    op.drop_index('ix_clip_analysis_owner_id', table_name='clip_analysis')
    op.drop_index('ix_clip_analysis_cache_key', table_name='clip_analysis')
    op.drop_table('clip_analysis')
