"""add proxy_host and proxy_port to devices

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-04-09 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('devices', sa.Column('proxy_host', sa.String(length=255), nullable=True))
    op.add_column('devices', sa.Column('proxy_port', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('devices', 'proxy_port')
    op.drop_column('devices', 'proxy_host')
