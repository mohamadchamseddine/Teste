from pydantic import BaseModel, field_validator
from typing import Optional, Any
from datetime import datetime
from models import UserRole, Direction, Currency, MovementType


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    role: UserRole
    is_active: bool
    has_pin: bool = False
    pin_locked: bool = False
    pin_failed_attempts: int = 0
    can_see_profits: bool
    can_see_volume: bool
    can_see_balance: bool
    can_unblock_users: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate(cls, obj, **kwargs):
        data = super().model_validate(obj, **kwargs)
        if hasattr(obj, "pin_hash"):
            data.has_pin = obj.pin_hash is not None
        return data


# ── Operators ─────────────────────────────────────────────────────────────────

class OperatorCreate(BaseModel):
    username: str
    password: str
    pin: str
    role: UserRole = UserRole.operator

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        digits = v.strip()
        if not digits.isdigit() or len(digits) != 4:
            raise ValueError("PIN deve ter exatamente 4 dígitos numéricos")
        return digits


class OperatorUpdate(BaseModel):
    is_active: Optional[bool] = None
    can_see_profits: Optional[bool] = None
    can_see_volume: Optional[bool] = None
    can_see_balance: Optional[bool] = None
    can_unblock_users: Optional[bool] = None


class OperatorSetPin(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        digits = v.strip()
        if not digits.isdigit() or len(digits) != 4:
            raise ValueError("PIN deve ter exatamente 4 dígitos numéricos")
        return digits


# ── Settings ──────────────────────────────────────────────────────────────────

class FeeUpdate(BaseModel):
    fee_pct: float

    @field_validator("fee_pct")
    @classmethod
    def validate_fee(cls, v: float) -> float:
        if v < 0 or v > 100:
            raise ValueError("Taxa deve estar entre 0 e 100")
        return round(v, 4)


class FeeOut(BaseModel):
    fee_pct: float


# ── Transactions ──────────────────────────────────────────────────────────────

class CreditRequiredInfo(BaseModel):
    credit_needed: bool = True
    client_id: int
    direction: Direction
    amount_in: float
    client_balance: float
    credit_amount: float
    interest_pct: float
    interest_days: int
    interest_amount: float


class CreditApprovalRequest(BaseModel):
    client_id: int
    direction: Direction
    amount_in: float


class TransactionCreate(BaseModel):
    direction: Direction
    amount_in: float
    operator_pin: str
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    notes: Optional[str] = None
    credit_approval_code: Optional[str] = None

    @field_validator("amount_in")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Valor deve ser maior que zero")
        return round(v, 6)

    @field_validator("operator_pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        digits = v.strip()
        if not digits.isdigit() or len(digits) != 4:
            raise ValueError("PIN deve ter exatamente 4 dígitos numéricos")
        return digits


class TransactionOut(BaseModel):
    id: int
    operator_id: int
    client_id: Optional[int]
    direction: Direction
    amount_in: float
    fee_pct: float
    fee_amount: float
    amount_out: float
    client_name: Optional[str]
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Clients ───────────────────────────────────────────────────────────────────

class ClientCreate(BaseModel):
    name: str
    phone: str
    credit_limit: float = 0.0
    credit_interest_pct: float = 0.0
    credit_interest_days: int = 30

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) < 10:
            raise ValueError("Número de telefone inválido")
        return digits


class ClientOut(BaseModel):
    id: int
    name: str
    phone: str
    is_active: bool
    usdt_balance: float
    usd_balance: float
    credit_limit: float
    credit_used: float
    credit_interest_pct: float
    credit_interest_days: int
    deposit_address: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    credit_limit: Optional[float] = None
    credit_interest_pct: Optional[float] = None
    credit_interest_days: Optional[int] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if v is None:
            return v
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) < 10:
            raise ValueError("Número de telefone inválido")
        return digits


class ClientBalanceOut(BaseModel):
    usdt_balance: float
    usd_balance: float


class ClientProfitOut(BaseModel):
    client_id: int
    client_name: str
    phone: str
    total_transactions: int
    fee_usdt: float
    fee_usd: float
    total_fee_usd_equivalent: float


# ── OTP ───────────────────────────────────────────────────────────────────────

class OTPRequest(BaseModel):
    phone: str


class OTPVerify(BaseModel):
    phone: str
    code: str


# ── Balance ───────────────────────────────────────────────────────────────────

class CashBalanceOut(BaseModel):
    currency: Currency
    balance: float
    updated_at: datetime

    model_config = {"from_attributes": True}


class CashMovementCreate(BaseModel):
    currency: Currency
    movement_type: MovementType
    amount: float
    notes: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Valor deve ser maior que zero")
        return round(v, 6)


class CashMovementOut(BaseModel):
    id: int
    operator_id: int
    currency: Currency
    movement_type: MovementType
    amount: float
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    my_transactions_today: int
    total_volume_today: Optional[float] = None
    total_fee_today: Optional[float] = None
    # All-time profits
    total_fee_usdt_alltime: Optional[float] = None
    total_fee_usd_alltime: Optional[float] = None
    # Cash balances
    usdt_balance: Optional[float] = None
    usd_balance: Optional[float] = None
    # Client aggregates (admin only)
    clients_usdt_total: Optional[float] = None
    clients_usd_total: Optional[float] = None
    company_usdt: Optional[float] = None
    company_usd: Optional[float] = None
    recent_transactions: list[TransactionOut] = []


# ── Profits ───────────────────────────────────────────────────────────────────

class ProfitSummary(BaseModel):
    total_transactions: int
    total_fee_usdt: float
    total_fee_usd: float
    total_volume_usdt: float
    total_volume_usd: float
    per_client: list[ClientProfitOut] = []


# ── Audit ─────────────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: int
    user_id: Optional[int]
    username: str
    action: str
    entity_type: Optional[str]
    entity_id: Optional[int]
    old_value: Optional[Any]
    new_value: Optional[Any]
    ip_address: str
    machine_name: str
    created_at: datetime

    model_config = {"from_attributes": True}
