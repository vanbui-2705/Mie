"""Add email identities, OAuth accounts and password reset tokens.

Revision ID: 20260713_0002
Revises: 20260713_0001
"""
from typing import Sequence, Union

from alembic import op
from app.models.sqlmodels import Base

revision: str = "20260713_0002"
down_revision: Union[str, None] = "20260713_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email CITEXT NULL")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255) NULL")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email) WHERE email IS NOT NULL")
    Base.metadata.tables["oauth_accounts"].create(op.get_bind(), checkfirst=True)
    Base.metadata.tables["password_reset_tokens"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["password_reset_tokens"].drop(op.get_bind(), checkfirst=True)
    Base.metadata.tables["oauth_accounts"].drop(op.get_bind(), checkfirst=True)
    op.execute("DROP INDEX IF EXISTS uq_users_email")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "full_name")
    op.drop_column("users", "email")
