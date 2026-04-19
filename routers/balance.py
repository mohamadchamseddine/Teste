from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import require_admin
from schemas import CashBalanceOut, CashMovementCreate, CashMovementOut, ClientBalanceAdjustment
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


@router.post("/client-movement")
async def client_balance_movement(
    data: ClientBalanceAdjustment,
    request: Request,
    admin: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    cl_res = await db.execute(select(models.Client).where(models.Client.id == data.client_id))
    client = cl_res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Check sufficient balance for withdrawal
    if data.movement_type == models.MovementType.withdrawal:
        current = client.usdt_balance if data.currency == models.Currency.USDT else client.usd_balance
        if current < data.amount:
            raise HTTPException(
                status_code=422,
                detail=f"Saldo insuficiente do cliente. Disponível: {current:,.2f} {data.currency.value}",
            )

    # Check cash box for deposits (cash leaves the box when crediting a client)
    cash_res = await db.execute(
        select(models.CashBalance).where(models.CashBalance.currency == data.currency)
    )
    cash = cash_res.scalar_one_or_none()

    if data.movement_type == models.MovementType.deposit:
        if not cash or cash.balance < data.amount:
            avail = cash.balance if cash else 0
            raise HTTPException(
                status_code=422,
                detail=f"Saldo insuficiente no caixa. Disponível: {avail:,.2f} {data.currency.value}",
            )

    old_client = {"usdt_balance": client.usdt_balance, "usd_balance": client.usd_balance}

    # Update client balance
    if data.currency == models.Currency.USDT:
        if data.movement_type == models.MovementType.deposit:
            client.usdt_balance = round(client.usdt_balance + data.amount, 6)
        else:
            client.usdt_balance = round(client.usdt_balance - data.amount, 6)
    else:
        if data.movement_type == models.MovementType.deposit:
            client.usd_balance = round(client.usd_balance + data.amount, 6)
        else:
            client.usd_balance = round(client.usd_balance - data.amount, 6)

    # Update cash box (deposit to client = cash leaves box; withdrawal from client = cash enters box)
    if cash:
        if data.movement_type == models.MovementType.deposit:
            cash.balance = round(cash.balance - data.amount, 6)
        else:
            cash.balance = round(cash.balance + data.amount, 6)
        cash.updated_at = datetime.now(timezone.utc)

    await audit.log(
        db, action=f"client_balance_{data.movement_type.value}",
        username=admin.username, request=request, user_id=admin.id,
        entity_type="client", entity_id=client.id,
        old_value=old_client,
        new_value={"usdt_balance": client.usdt_balance, "usd_balance": client.usd_balance,
                   "currency": data.currency, "amount": data.amount, "notes": data.notes},
    )
    await db.commit()
    await db.refresh(client)
    return {"client_name": client.name, "usdt_balance": client.usdt_balance, "usd_balance": client.usd_balance}


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
