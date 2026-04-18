"""Add pin lockout fields and can_unblock_users

Revision ID: 003
Revises: 002
Create Date: 2025-01-01 00:00:02.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pin_failed_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("pin_locked", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("can_unblock_users", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("users", "can_unblock_users")
    op.drop_column("users", "pin_locked")
    op.drop_column("users", "pin_failed_attempts")
