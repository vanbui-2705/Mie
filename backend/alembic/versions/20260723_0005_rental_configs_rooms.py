"""Add rental_configs and rental_rooms tables.

Revision ID: 20260723_0005
Revises: 20260720_0004
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260723_0005"
down_revision: Union[str, None] = "20260720_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rental_configs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="nhatrovn"),
        sa.Column("source_credentials_enc", sa.Text(), nullable=False),
        sa.Column("province_code", sa.String(length=32), nullable=False),
        sa.Column("province_name", sa.String(length=128), nullable=False),
        sa.Column("district_code", sa.String(length=32), nullable=False),
        sa.Column("district_name", sa.String(length=128), nullable=False),
        sa.Column("ward_code", sa.String(length=32), nullable=True),
        sa.Column("ward_name", sa.String(length=128), nullable=True),
        sa.Column("extra_filters_json", sa.Text(), nullable=True),
        sa.Column("auto_post", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("post_spacing_seconds", sa.Integer(), nullable=False, server_default="480"),
        sa.Column("post_delay_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("caption_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("contact_phone", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("group_match_level", sa.String(length=16), nullable=False, server_default="district"),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        sa.Column("google_sheet_connection_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_post_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["google_sheet_connection_id"], ["google_sheet_connections.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_rental_configs_user",
        "rental_configs",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "rental_rooms",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("config_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("external_room_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("price", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("area_text", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
        sa.Column("district", sa.String(length=128), nullable=True),
        sa.Column("ward", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("images_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("caption", sa.Text(), nullable=False, server_default=""),
        sa.Column("matched_group_ids_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("post_urls_json", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["config_id"], ["rental_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "config_id", "external_room_id",
            name="uq_rental_rooms_config_room",
        ),
    )
    op.create_index(
        "idx_rental_rooms_user",
        "rental_rooms",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_rental_rooms_user", table_name="rental_rooms")
    op.drop_table("rental_rooms")
    op.drop_index("idx_rental_configs_user", table_name="rental_configs")
    op.drop_table("rental_configs")
