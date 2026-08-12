"""user token version

Tokens are stateless, so nothing but expiry could end a session. This column
gives a password change something to invalidate against.

Revision ID: 20260811_0011
Revises: 20260810_0010
Create Date: 2026-08-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = '20260811_0011'
down_revision: Union[str, None] = '20260810_0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `users` is a baseline table, so revision 20260713_0001 builds it from the
    # current model and this column is already there on a fresh database.
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.drop_column('users', 'token_version')
