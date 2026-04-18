"""Add credit fields to clients and credit_approval_otps table

Revision ID: 004
Revises: 003
Create Date: 2025-01-01 00:00:03.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Credit fields on clients
    op.add_column("clients", sa.Column("credit_limit", sa.Float(), nullable=False, server_default="0"))
    op.add_column("clients", sa.Column("credit_used", sa.Float(), nullable=False, server_default="0"))
    op.add_column("clients", sa.Column("credit_interest_pct", sa.Float(), nullable=False, server_default="0"))
    op.add_column("clients", sa.Column("credit_interest_days", sa.Integer(), nullable=False, server_default="30"))

    # credit_amount_used on transactions
    op.add_column("transactions", sa.Column("credit_amount_used", sa.Float(), nullable=False, server_default="0"))

    # credit approval OTPs table
    op.create_table(
        "credit_approval_otps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("direction", sa.Enum("usdt_to_usd", "usd_to_usdt", name="direction"), nullable=False),
        sa.Column("amount_in", sa.Float(), nullable=False),
        sa.Column("credit_amount", sa.Float(), nullable=False),
        sa.Column("interest_pct", sa.Float(), nullable=False),
        sa.Column("interest_days", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_table("credit_approval_otps")
    op.drop_column("transactions", "credit_amount_used")
    op.drop_column("clients", "credit_interest_days")
    op.drop_column("clients", "credit_interest_pct")
    op.drop_column("clients", "credit_used")
    op.drop_column("clients", "credit_limit")
