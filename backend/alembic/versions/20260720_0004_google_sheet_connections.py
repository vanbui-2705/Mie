"""Add Google Sheets connections.

Revision ID: 20260720_0004
Revises: 20260713_0003
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260720_0004"
down_revision: Union[str, None] = "20260713_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GOOGLE_SHEET_PERMISSIONS = (
    "google_sheet:read",
    "google_sheet:create",
    "google_sheet:update",
    "google_sheet:delete",
)


def upgrade() -> None:
    op.create_table(
        "google_sheet_connections",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("spreadsheet_id", sa.String(length=255), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False, server_default="Posts"),
        sa.Column("credentials_enc", sa.Text(), nullable=False),
        sa.Column("service_account_email", sa.String(length=320), nullable=False),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="connected"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "spreadsheet_id", "sheet_name",
            name="uq_google_sheet_connections_user_sheet",
        ),
    )
    op.create_index(
        "idx_google_sheet_connections_user",
        "google_sheet_connections",
        ["user_id"],
        unique=False,
    )

    connection = op.get_bind()
    for code in GOOGLE_SHEET_PERMISSIONS:
        resource, action = code.split(":", 1)
        connection.execute(sa.text("""
            INSERT INTO permissions (code, resource, action, is_system)
            VALUES (:code, :resource, :action, TRUE)
            ON CONFLICT (code) DO UPDATE
            SET resource = EXCLUDED.resource, action = EXCLUDED.action
        """), {"code": code, "resource": resource, "action": action})

    for code in GOOGLE_SHEET_PERMISSIONS:
        connection.execute(sa.text("""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name IN ('user', 'staff', 'manager', 'admin', 'super_admin')
              AND p.code = :code
            ON CONFLICT DO NOTHING
        """), {"code": code})


def downgrade() -> None:
    connection = op.get_bind()
    for code in GOOGLE_SHEET_PERMISSIONS:
        connection.execute(sa.text("""
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE code = :code
            )
        """), {"code": code})
        connection.execute(sa.text(
            "DELETE FROM permissions WHERE code = :code"
        ), {"code": code})
    op.drop_index("idx_google_sheet_connections_user", table_name="google_sheet_connections")
    op.drop_table("google_sheet_connections")
