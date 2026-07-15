"""Add RBAC and finish ownership constraints.

Revision ID: 20260713_0003
Revises: 20260713_0002
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.rbac_catalog import PERMISSIONS, ROLE_DEFINITIONS, split_permission

revision: str = "20260713_0003"
down_revision: Union[str, None] = "20260713_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(64) NOT NULL UNIQUE,
            display_name VARCHAR(128) NOT NULL,
            description TEXT NULL,
            is_system BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(128) NOT NULL UNIQUE,
            resource VARCHAR(64) NOT NULL,
            action VARCHAR(64) NOT NULL,
            description TEXT NULL,
            is_system BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS role_permissions (
            role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
            PRIMARY KEY (role_id, permission_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            assigned_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, role_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_id)")

    connection = op.get_bind()
    for code in PERMISSIONS:
        resource, action = split_permission(code)
        connection.execute(sa.text("""
            INSERT INTO permissions (code, resource, action, is_system)
            VALUES (:code, :resource, :action, TRUE)
            ON CONFLICT (code) DO UPDATE SET resource = EXCLUDED.resource, action = EXCLUDED.action
        """), {"code": code, "resource": resource, "action": action})

    for name, definition in ROLE_DEFINITIONS.items():
        connection.execute(sa.text("""
            INSERT INTO roles (name, display_name, description, is_system)
            VALUES (:name, :display_name, :description, TRUE)
            ON CONFLICT (name) DO UPDATE
            SET display_name = EXCLUDED.display_name, description = EXCLUDED.description
        """), {
            "name": name,
            "display_name": definition["display_name"],
            "description": definition["description"],
        })
        connection.execute(sa.text("DELETE FROM role_permissions WHERE role_id = (SELECT id FROM roles WHERE name = :name)"), {"name": name})
        for code in definition["permissions"]:
            connection.execute(sa.text("""
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r, permissions p
                WHERE r.name = :name AND p.code = :code
                ON CONFLICT DO NOTHING
            """), {"name": name, "code": code})

    # A legacy installation needs an owner before global rows can be assigned.
    op.execute("""
        INSERT INTO users (id, username, role, status, created_at)
        SELECT gen_random_uuid(), 'admin', 'super_admin', 'ACTIVE', now()
        WHERE NOT EXISTS (SELECT 1 FROM users)
    """)
    op.execute("""
        WITH ranked_admin AS (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn
            FROM users WHERE role IN ('admin', 'super_admin')
        )
        UPDATE users SET role = 'super_admin'
        WHERE id IN (SELECT id FROM ranked_admin WHERE rn = 1)
    """)
    op.execute("""
        INSERT INTO user_roles (user_id, role_id)
        SELECT u.id, r.id
        FROM users u
        JOIN roles r ON r.name = CASE
            WHEN u.role IN ('super_admin', 'admin', 'manager', 'staff', 'user') THEN u.role
            ELSE 'user' END
        ON CONFLICT DO NOTHING
    """)

    owner_sql = "(SELECT id FROM users ORDER BY CASE WHEN role = 'super_admin' THEN 0 ELSE 1 END, created_at, id LIMIT 1)"
    op.execute(f"UPDATE task_runs SET user_id = {owner_sql} WHERE user_id IS NULL")
    op.execute("UPDATE task_items ti SET user_id = tr.user_id FROM task_runs tr WHERE ti.run_id = tr.id AND ti.user_id IS NULL")
    op.execute("ALTER TABLE task_runs ALTER COLUMN user_id SET NOT NULL")
    op.execute("ALTER TABLE task_items ALTER COLUMN user_id SET NOT NULL")

    op.execute("ALTER TABLE proxy_keys ADD COLUMN IF NOT EXISTS user_id UUID NULL REFERENCES users(id) ON DELETE CASCADE")
    op.execute(f"UPDATE proxy_keys SET user_id = {owner_sql} WHERE user_id IS NULL")
    op.execute("ALTER TABLE proxy_keys ALTER COLUMN user_id SET NOT NULL")
    op.execute("ALTER TABLE proxy_keys DROP CONSTRAINT IF EXISTS proxy_keys_masked_key_key")
    op.execute("CREATE INDEX IF NOT EXISTS idx_proxy_keys_user ON proxy_keys(user_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_proxy_keys_user_masked ON proxy_keys(user_id, masked_key)")

    op.execute("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS user_id UUID NULL REFERENCES users(id) ON DELETE CASCADE")
    op.execute(f"UPDATE app_settings SET user_id = {owner_sql} WHERE user_id IS NULL")
    op.execute("ALTER TABLE app_settings ALTER COLUMN user_id SET NOT NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_app_settings_user ON app_settings(user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_app_settings_user")
    op.execute("ALTER TABLE app_settings DROP COLUMN IF EXISTS user_id")
    op.execute("DROP INDEX IF EXISTS uq_proxy_keys_user_masked")
    op.execute("DROP INDEX IF EXISTS idx_proxy_keys_user")
    op.execute("ALTER TABLE proxy_keys DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE task_items ALTER COLUMN user_id DROP NOT NULL")
    op.execute("ALTER TABLE task_runs ALTER COLUMN user_id DROP NOT NULL")
    op.execute("DROP TABLE IF EXISTS user_roles")
    op.execute("DROP TABLE IF EXISTS role_permissions")
    op.execute("DROP TABLE IF EXISTS permissions")
    op.execute("DROP TABLE IF EXISTS roles")
