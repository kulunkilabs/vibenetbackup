"""make credentials.username nullable for password-only devices

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-04-12 00:00:00.000000

Some devices (e.g. standalone TP-Link APs/switches, some consumer routers)
have no username field — only a password.  Making username nullable lets
users create a credential with just a password.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite does not support ALTER COLUMN — use batch mode to recreate the table.
    with op.batch_alter_table('credentials', recreate='always') as batch_op:
        batch_op.alter_column('username',
                              existing_type=sa.String(length=255),
                              nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('credentials', recreate='always') as batch_op:
        batch_op.alter_column('username',
                              existing_type=sa.String(length=255),
                              nullable=False)
