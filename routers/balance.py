from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import require_admin
from schemas import CashBalanceOut, CashMovementCreate, CashMovementOut
import models
import audit

router = APIRouter(prefix="/api/balance", tags=["balance"])


@router.get("", response_model=list[CashBalanceOut])
async def get_balances(
    _: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.CashBalance))
    return result.scalars().all()


@router.post("/deposit", response_model=CashBalanceOut)
async def cash_deposit(
    data: CashMovementCreate,
    request: Request,
    admin: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _apply_movement(db, admin, request, data, models.MovementType.deposit)


@router.post("/withdrawal", response_model=CashBalanceOut)
async def cash_withdrawal(
    data: CashMovementCreate,
    request: Request,
    admin: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _apply_movement(db, admin, request, data, models.MovementType.withdrawal)


async def _apply_movement(
    db: AsyncSession,
    admin: models.User,
    request: Request,
    data: CashMovementCreate,
    movement_type: models.MovementType,
) -> models.CashBalance:
    result = await db.execute(
        select(models.CashBalance).where(models.CashBalance.currency == data.currency)
    )
    cash = result.scalar_one_or_none()
    if not cash:
        cash = models.CashBalance(currency=data.currency, balance=0.0)
        db.add(cash)
        await db.flush()

    old_balance = cash.balance

    if movement_type == models.MovementType.withdrawal and cash.balance < data.amount:
        raise HTTPException(
            status_code=422,
            detail=f"Saldo insuficiente. Disponível: {cash.balance:,.2f} {data.currency.value}",
        )

    if movement_type == models.MovementType.deposit:
        cash.balance = round(cash.balance + data.amount, 6)
    else:
        cash.balance = round(cash.balance - data.amount, 6)

    cash.updated_at = datetime.now(timezone.utc)

    movement = models.CashMovement(
        operator_id=admin.id,
        currency=data.currency,
        movement_type=movement_type,
        amount=data.amount,
        notes=data.notes,
    )
    db.add(movement)

    await audit.log(
        db,
        action=f"cash_{movement_type.value}",
        username=admin.username,
        request=request,
        user_id=admin.id,
        entity_type="cash_balance",
        old_value={"currency": data.currency, "balance": old_balance},
        new_value={"currency": data.currency, "balance": cash.balance, "amount": data.amount},
    )
    await db.commit()
    await db.refresh(cash)
    return cash


@router.get("/movements", response_model=list[CashMovementOut])
async def list_movements(
    limit: int = 100,
    _: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.CashMovement)
        .order_by(models.CashMovement.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
