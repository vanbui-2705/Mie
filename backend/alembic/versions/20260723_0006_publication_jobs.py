"""Add durable per-target publication jobs.

Revision ID: 20260723_0006
Revises: 20260723_0005
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260723_0006"
down_revision: Union[str, None] = "20260723_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rental_configs",
        sa.Column("last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rental_rooms",
        sa.Column("source_status", sa.String(length=64), server_default="", nullable=False),
    )
    op.add_column(
        "rental_rooms",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rental_rooms",
        sa.Column("media_paths_json", sa.Text(), server_default="[]", nullable=False),
    )
    op.add_column(
        "rental_rooms",
        sa.Column("mirror_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "rental_rooms",
        sa.Column("mirror_error", sa.Text(), nullable=True),
    )
    op.create_table(
        "publication_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rental_room_id", sa.UUID(), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("target_external_id", sa.String(length=255), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("task_run_id", sa.UUID(), nullable=True),
        sa.Column("task_item_id", sa.Integer(), nullable=True),
        sa.Column("facebook_post_id", sa.String(length=255), nullable=True),
        sa.Column("facebook_url", sa.Text(), nullable=True),
        sa.Column("result_message", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rental_room_id"], ["rental_rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_run_id"], ["task_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_item_id"], ["task_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rental_room_id", "target_type", "target_id",
            name="uq_publication_jobs_rental_target",
        ),
    )
    op.create_index(
        "idx_publication_jobs_due",
        "publication_jobs",
        ["status", "scheduled_at", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "idx_publication_jobs_user",
        "publication_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "idx_publication_jobs_task_item",
        "publication_jobs",
        ["task_item_id"],
        unique=False,
    )
    op.create_table(
        "rental_sheet_mirror_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rental_room_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("sheet_row_number", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rental_room_id"], ["rental_rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["google_sheet_connections.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rental_room_id", "connection_id",
            name="uq_rental_sheet_mirror_room_connection",
        ),
    )
    op.create_index(
        "idx_rental_sheet_mirror_due",
        "rental_sheet_mirror_jobs",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "idx_rental_sheet_mirror_user",
        "rental_sheet_mirror_jobs",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_rental_sheet_mirror_user", table_name="rental_sheet_mirror_jobs")
    op.drop_index("idx_rental_sheet_mirror_due", table_name="rental_sheet_mirror_jobs")
    op.drop_table("rental_sheet_mirror_jobs")
    op.drop_index("idx_publication_jobs_task_item", table_name="publication_jobs")
    op.drop_index("idx_publication_jobs_user", table_name="publication_jobs")
    op.drop_index("idx_publication_jobs_due", table_name="publication_jobs")
    op.drop_table("publication_jobs")
    op.drop_column("rental_rooms", "media_paths_json")
    op.drop_column("rental_rooms", "mirror_error")
    op.drop_column("rental_rooms", "mirror_status")
    op.drop_column("rental_rooms", "last_seen_at")
    op.drop_column("rental_rooms", "source_status")
    op.drop_column("rental_configs", "last_sync_attempt_at")
