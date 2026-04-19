"""Add pin_hash to clients

Revision ID: 005
Revises: 004
Create Date: 2025-01-01 00:00:04.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("pin_hash", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "pin_hash")
