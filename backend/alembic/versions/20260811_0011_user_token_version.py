"""user token version

Tokens are stateless, so nothing but expiry could end a session. This column
gives a password change something to invalidate against.

Revision ID: 20260811_0011
Revises: 20260810_0010
Create Date: 2026-08-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260811_0011'
down_revision: Union[str, None] = '20260810_0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('users', 'token_version')
