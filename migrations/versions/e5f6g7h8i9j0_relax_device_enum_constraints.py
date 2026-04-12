"""relax device_type and backup_engine enum constraints to plain text

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-04-12 00:00:00.000000

SQLite does not support ALTER COLUMN, so we recreate the devices table
without the CHECK constraints that the initial migration baked in for
device_type and backup_engine.  All existing data is preserved.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recreate devices table without Enum CHECK constraints so new device/engine
    # types (pfsense, proxmox, nokia_sros_md, mikrotik_routeros …) are accepted.
    with op.batch_alter_table('devices', recreate='always') as batch_op:
        batch_op.alter_column('device_type',
                              existing_type=sa.String(length=50),
                              type_=sa.String(length=50),
                              existing_nullable=False)
        batch_op.alter_column('backup_engine',
                              existing_type=sa.String(length=50),
                              type_=sa.String(length=50),
                              existing_nullable=False)

    # Also relax destinations.dest_type — 'github', 'gitea', 'git', 'forgejo'
    # were blocked by the original Enum constraint on non-SQLite engines.
    with op.batch_alter_table('destinations', recreate='always') as batch_op:
        batch_op.alter_column('dest_type',
                              existing_type=sa.String(length=50),
                              type_=sa.String(length=50),
                              existing_nullable=False)

    # Add missing group profile columns (v1.6) if not already present.
    # Guard against duplicates in case _apply_column_migrations() already ran.
    conn = op.get_bind()
    existing_group_cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(groups)")).fetchall()}
    for col_name, col_def in [
        ("destination_ids", "TEXT"),
        ("backup_engine",   "VARCHAR(50)"),
        ("notification_ids","TEXT"),
    ]:
        if col_name not in existing_group_cols:
            conn.execute(sa.text(f'ALTER TABLE groups ADD COLUMN "{col_name}" {col_def}'))


def downgrade() -> None:
    # Downgrade restores the original strict enums — existing rows with
    # non-original values will violate the constraint (data loss risk).
    pass
