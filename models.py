import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, Float, DateTime,
    Enum, ForeignKey, JSON, Text
)
from sqlalchemy.orm import relationship
from database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"


class Direction(str, enum.Enum):
    usdt_to_usd = "usdt_to_usd"
    usd_to_usdt = "usd_to_usdt"


class Currency(str, enum.Enum):
    USDT = "USDT"
    USD = "USD"


class MovementType(str, enum.Enum):
    deposit = "deposit"
    withdrawal = "withdrawal"


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    pin_hash = Column(String(255), nullable=True)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.operator)
    is_active = Column(Boolean, default=True)
    can_see_profits = Column(Boolean, default=False)
    can_see_volume = Column(Boolean, default=False)
    can_see_balance = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    transactions = relationship("Transaction", back_populates="operator")
    cash_movements = relationship("CashMovement", back_populates="operator")
    audit_logs = relationship("AuditLog", back_populates="user")


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    usdt_balance = Column(Float, default=0.0)
    usd_balance = Column(Float, default=0.0)
    deposit_address = Column(String(50), unique=True, nullable=True)
    deposit_address_index = Column(Integer, unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    otps = relationship("OTPCode", back_populates="client")
    transactions = relationship("Transaction", back_populates="client")
    usdt_deposits = relationship("USDTDeposit", back_populates="client")


class OTPCode(Base):
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)

    client = relationship("Client", back_populates="otps")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    direction = Column(Enum(Direction), nullable=False)
    amount_in = Column(Float, nullable=False)
    fee_pct = Column(Float, nullable=False)
    fee_amount = Column(Float, nullable=False)
    amount_out = Column(Float, nullable=False)
    client_name = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    operator = relationship("User", back_populates="transactions")
    client = relationship("Client", back_populates="transactions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    ip_address = Column(String(100), nullable=False, default="unknown")
    machine_name = Column(String(500), nullable=False, default="unknown")
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)

    user = relationship("User", back_populates="audit_logs")


class CashBalance(Base):
    __tablename__ = "cash_balances"

    id = Column(Integer, primary_key=True)
    currency = Column(Enum(Currency), unique=True, nullable=False)
    balance = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class CashMovement(Base):
    __tablename__ = "cash_movements"

    id = Column(Integer, primary_key=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    currency = Column(Enum(Currency), nullable=False)
    movement_type = Column(Enum(MovementType), nullable=False)
    amount = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    operator = relationship("User", back_populates="cash_movements")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    fee_pct = Column(Float, default=1.0)


class USDTDeposit(Base):
    __tablename__ = "usdt_deposits"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    tx_hash = Column(String(100), unique=True, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    confirmed_at = Column(DateTime(timezone=True), default=utcnow)

    client = relationship("Client", back_populates="usdt_deposits")
