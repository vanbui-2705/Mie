"""Initial FlowMeta schema managed by Alembic.

Revision ID: 20260713_0001
Revises:
Create Date: 2026-07-13

This baseline is intentionally idempotent. It can initialize a new database or
adopt an existing pre-Alembic FlowMeta database and then stamp it at this
revision. Future schema changes must be expressed as normal Alembic operations.
"""
from typing import Sequence, Union

from alembic import op
from app.models.sqlmodels import Base

revision: str = "20260713_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# `Base.metadata` tracks the models as they are today, not as they were at this
# revision. Creating all of it here would build tables that later revisions
# still try to create, which aborts `upgrade head` on any empty database. Keep
# the baseline to the tables that existed when it was written; every table
# below is created by the revision named beside it.
POST_BASELINE_TABLES = frozenset(
    {
        "google_sheet_connections",  # 20260720_0004
        "rental_configs",  # 20260723_0005
        "rental_rooms",  # 20260723_0005
        "publication_jobs",  # 20260723_0006
        "rental_sheet_mirror_jobs",  # 20260723_0006
        "sheet_campaigns",  # 20260723_0007
        "sheet_source_items",  # 20260723_0007
        "sheet_writeback_jobs",  # 20260723_0007
        "clips",  # 20260724_0008
        "clip_jobs",  # 20260724_0008
        "clip_edits",  # 20260724_0008
        "clip_analysis",  # 20260810_0010
    }
)


def _baseline_tables() -> list:
    return [
        table
        for name, table in Base.metadata.tables.items()
        if name not in POST_BASELINE_TABLES
    ]


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    Base.metadata.create_all(bind=bind, tables=_baseline_tables(), checkfirst=True)

    # Adopt databases created by the former create_all_tables bootstrap.
    op.execute("ALTER TABLE facebook_accounts ADD COLUMN IF NOT EXISTS browser_status VARCHAR(32) NOT NULL DEFAULT 'not_configured'")
    op.execute("ALTER TABLE facebook_accounts ADD COLUMN IF NOT EXISTS browser_last_checked_at TIMESTAMP WITH TIME ZONE NULL")
    op.execute("ALTER TABLE facebook_accounts ADD COLUMN IF NOT EXISTS browser_last_error TEXT NULL")
    op.execute("ALTER TABLE facebook_accounts ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMP WITH TIME ZONE NULL")
    op.execute("ALTER TABLE facebook_accounts ADD COLUMN IF NOT EXISTS token_last_refreshed_at TIMESTAMP WITH TIME ZONE NULL")
    op.execute("ALTER TABLE facebook_accounts ADD COLUMN IF NOT EXISTS token_is_long_lived BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE share_targets ADD COLUMN IF NOT EXISTS target_type VARCHAR(32) NOT NULL DEFAULT 'page'")
    op.execute("ALTER TABLE share_targets ALTER COLUMN facebook_page_id DROP NOT NULL")
    op.execute("ALTER TABLE share_targets ADD COLUMN IF NOT EXISTS facebook_group_id UUID NULL REFERENCES facebook_groups(id) ON DELETE CASCADE")
    op.execute("ALTER TABLE share_targets ADD COLUMN IF NOT EXISTS external_page_id UUID NULL REFERENCES external_pages(id) ON DELETE CASCADE")
    op.execute("ALTER TABLE share_targets ADD COLUMN IF NOT EXISTS facebook_account_id UUID NULL REFERENCES facebook_accounts(id) ON DELETE CASCADE")
    op.execute("ALTER TABLE task_logs ALTER COLUMN action TYPE VARCHAR(32)")
    op.execute("ALTER TABLE task_items ALTER COLUMN status TYPE VARCHAR(32)")
    op.execute("ALTER TABLE task_items ALTER COLUMN action TYPE VARCHAR(32)")
    op.execute("ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS post_items_json TEXT NULL")
    op.execute("ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS next_item_index INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=_baseline_tables(), checkfirst=True)
