"""clip jobs, clips and clip edits (Flow Studio)

Revision ID: 20260724_0008
Revises: 20260723_0007
Create Date: 2026-07-29 10:52:56.517462
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '20260724_0008'
down_revision: Union[str, None] = '20260723_0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('clip_jobs',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('source_type', sa.Enum('UPLOAD', 'LINK', name='clip_source_type', native_enum=False), nullable=False),
    sa.Column('source_ref', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('status', sa.Enum('QUEUED', 'ANALYZING', 'SCORING', 'RENDERING', 'DONE', 'ERROR', name='clip_job_status', native_enum=False), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source_sha256', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_clip_jobs_user_created_at', 'clip_jobs', ['user_id', sa.text('created_at DESC')], unique=False)
    op.create_table('clips',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('job_id', sa.UUID(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('hook_text', sa.Text(), nullable=True),
    sa.Column('start_sec', sa.Float(), nullable=False),
    sa.Column('end_sec', sa.Float(), nullable=False),
    sa.Column('clipspec', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('output_ref', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('PENDING', 'RENDERING', 'READY', 'ERROR', name='clip_status', native_enum=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['clip_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_clips_job_rank', 'clips', ['job_id', 'rank'], unique=False)
    op.create_table('clip_edits',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('clip_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('clipspec', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source', sa.Enum('AUTO', 'OPENCUT', name='clip_edit_source', native_enum=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_clip_edits_clip_version', 'clip_edits', ['clip_id', 'version'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_clip_edits_clip_version', table_name='clip_edits')
    op.drop_table('clip_edits')
    op.drop_index('idx_clips_job_rank', table_name='clips')
    op.drop_table('clips')
    op.drop_index('idx_clip_jobs_user_created_at', table_name='clip_jobs')
    op.drop_table('clip_jobs')
