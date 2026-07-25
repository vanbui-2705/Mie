"""Add Google Sheet campaign, source item and writeback pipeline.

Revision ID: 20260723_0007
Revises: 20260723_0006
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260723_0007"
down_revision: Union[str, None] = "20260723_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sheet_campaigns",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("default_targets_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("default_schedule_mode", sa.String(length=16), server_default="NOW", nullable=False),
        sa.Column("schedule_slots_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("active_weekdays_json", sa.Text(), server_default="[0,1,2,3,4,5,6]", nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Ho_Chi_Minh", nullable=False),
        sa.Column("max_posts_per_day", sa.Integer(), server_default="20", nullable=False),
        sa.Column("min_post_gap_seconds", sa.Integer(), server_default="300", nullable=False),
        sa.Column("late_policy", sa.String(length=16), server_default="publish_now", nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default="3", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["google_sheet_connections.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", name="uq_sheet_campaign_connection"),
    )
    op.create_index("idx_sheet_campaigns_user", "sheet_campaigns", ["user_id"], unique=False)

    op.create_table(
        "sheet_source_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("sheet_row_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("media_urls_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("media_paths_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("targets_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("schedule_mode", sa.String(length=16), server_default="NOW", nullable=False),
        sa.Column("requested_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["google_sheet_connections.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["sheet_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id", "external_id",
            name="uq_sheet_source_campaign_external",
        ),
    )
    op.create_index(
        "idx_sheet_source_user_status",
        "sheet_source_items",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "idx_sheet_source_campaign_row",
        "sheet_source_items",
        ["campaign_id", "sheet_row_number"],
        unique=False,
    )

    op.add_column(
        "publication_jobs",
        sa.Column("sheet_source_item_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "publication_jobs",
        sa.Column("source_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_foreign_key(
        "fk_publication_jobs_sheet_source_item",
        "publication_jobs",
        "sheet_source_items",
        ["sheet_source_item_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_publication_jobs_sheet_version_target",
        "publication_jobs",
        ["sheet_source_item_id", "source_version", "target_type", "target_id"],
    )

    op.create_table(
        "sheet_writeback_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source_item_id", sa.UUID(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_item_id"], ["sheet_source_items.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_item_id", "source_version",
            name="uq_sheet_writeback_item_version",
        ),
    )
    op.create_index(
        "idx_sheet_writeback_due",
        "sheet_writeback_jobs",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "idx_sheet_writeback_user",
        "sheet_writeback_jobs",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_sheet_writeback_user", table_name="sheet_writeback_jobs")
    op.drop_index("idx_sheet_writeback_due", table_name="sheet_writeback_jobs")
    op.drop_table("sheet_writeback_jobs")
    op.drop_constraint(
        "uq_publication_jobs_sheet_version_target",
        "publication_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "fk_publication_jobs_sheet_source_item",
        "publication_jobs",
        type_="foreignkey",
    )
    op.drop_column("publication_jobs", "source_version")
    op.drop_column("publication_jobs", "sheet_source_item_id")
    op.drop_index("idx_sheet_source_campaign_row", table_name="sheet_source_items")
    op.drop_index("idx_sheet_source_user_status", table_name="sheet_source_items")
    op.drop_table("sheet_source_items")
    op.drop_index("idx_sheet_campaigns_user", table_name="sheet_campaigns")
    op.drop_table("sheet_campaigns")
