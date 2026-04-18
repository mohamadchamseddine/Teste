"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(100), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("admin", "operator", name="userrole"), nullable=False, server_default="operator"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("can_see_profits", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("can_see_volume", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("can_see_balance", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), unique=True, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("usdt_balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("usd_balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("deposit_address", sa.String(50), unique=True, nullable=True),
        sa.Column("deposit_address_index", sa.Integer(), unique=True, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_clients_phone", "clients", ["phone"])

    op.create_table(
        "otp_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("direction", sa.Enum("usdt_to_usd", "usd_to_usdt", name="direction"), nullable=False),
        sa.Column("amount_in", sa.Float(), nullable=False),
        sa.Column("fee_pct", sa.Float(), nullable=False),
        sa.Column("fee_amount", sa.Float(), nullable=False),
        sa.Column("amount_out", sa.Float(), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(100), nullable=False, server_default="unknown"),
        sa.Column("machine_name", sa.String(500), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "cash_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("currency", sa.Enum("USDT", "USD", name="currency"), unique=True, nullable=False),
        sa.Column("balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "cash_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("currency", sa.Enum("USDT", "USD", name="currency"), nullable=False),
        sa.Column("movement_type", sa.Enum("deposit", "withdrawal", name="movementtype"), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fee_pct", sa.Float(), nullable=False, server_default="1.0"),
    )

    op.create_table(
        "usdt_deposits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("tx_hash", sa.String(100), unique=True, nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_usdt_deposits_tx_hash", "usdt_deposits", ["tx_hash"])


def downgrade() -> None:
    op.drop_table("usdt_deposits")
    op.drop_table("app_settings")
    op.drop_table("cash_movements")
    op.drop_table("cash_balances")
    op.drop_table("audit_logs")
    op.drop_table("transactions")
    op.drop_table("otp_codes")
    op.drop_table("clients")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS userrole")
    op.execute("DROP TYPE IF EXISTS direction")
    op.execute("DROP TYPE IF EXISTS currency")
    op.execute("DROP TYPE IF EXISTS movementtype")
