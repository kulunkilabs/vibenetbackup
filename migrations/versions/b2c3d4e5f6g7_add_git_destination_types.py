"""Add github, gitea, git destination types

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-13

"""
from alembic import op

revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

# SQLite does not enforce enum constraints, so no ALTER TYPE needed.
# The new values ('github', 'gitea', 'git') are handled by the application layer.


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
