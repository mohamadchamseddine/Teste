from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from auth import get_current_user
from schemas import TransactionCreate, TransactionOut
import models
import audit
import whatsapp
from config import settings

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.post("", response_model=TransactionOut, status_code=201)
async def create_transaction(
    data: TransactionCreate,
    request: Request,
    background: BackgroundTasks,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Load fee
    cfg_res = await db.execute(select(models.AppSettings).where(models.AppSettings.id == 1))
    cfg = cfg_res.scalar_one_or_none()
    fee_pct = cfg.fee_pct if cfg else 1.0

    fee_amount = round(data.amount_in * (fee_pct / 100), 6)
    amount_out = round(data.amount_in - fee_amount, 6)

    # Determine which currency leaves the cash box
    if data.direction == models.Direction.usdt_to_usd:
        outgoing_currency = models.Currency.USD
        incoming_currency = models.Currency.USDT
    else:
        outgoing_currency = models.Currency.USDT
        incoming_currency = models.Currency.USD

    # Check cash balance
    bal_res = await db.execute(
        select(models.CashBalance).where(models.CashBalance.currency == outgoing_currency)
    )
    cash = bal_res.scalar_one_or_none()
    if not cash or cash.balance < amount_out:
        avail = cash.balance if cash else 0
        raise HTTPException(
            status_code=422,
            detail=f"Saldo insuficiente de {outgoing_currency.value} no caixa. Disponível: {avail:,.2f}",
        )

    # Load client if provided
    client = None
    client_name = data.client_name
    if data.client_id:
        cl_res = await db.execute(select(models.Client).where(models.Client.id == data.client_id))
        client = cl_res.scalar_one_or_none()
        if not client:
            raise HTTPException(status_code=404, detail="Cliente não encontrado")
        client_name = client_name or client.name

    # Create transaction
    tx = models.Transaction(
        operator_id=user.id,
        client_id=client.id if client else None,
        direction=data.direction,
        amount_in=data.amount_in,
        fee_pct=fee_pct,
        fee_amount=fee_amount,
        amount_out=amount_out,
        client_name=client_name,
        notes=data.notes,
    )
    db.add(tx)
    await db.flush()

    # Update cash balances
    cash.balance = round(cash.balance - amount_out, 6)
    cash.updated_at = datetime.now(timezone.utc)

    in_bal_res = await db.execute(
        select(models.CashBalance).where(models.CashBalance.currency == incoming_currency)
    )
    in_cash = in_bal_res.scalar_one_or_none()
    if in_cash:
        in_cash.balance = round(in_cash.balance + data.amount_in, 6)
        in_cash.updated_at = datetime.now(timezone.utc)

    # Update client balances
    if client:
        if data.direction == models.Direction.usdt_to_usd:
            client.usdt_balance = round(client.usdt_balance - data.amount_in, 6)
            client.usd_balance = round(client.usd_balance + amount_out, 6)
        else:
            client.usd_balance = round(client.usd_balance - data.amount_in, 6)
            client.usdt_balance = round(client.usdt_balance + amount_out, 6)

    await audit.log(
        db, action="create_transaction", username=user.username,
        request=request, user_id=user.id,
        entity_type="transaction", entity_id=tx.id,
        new_value={
            "direction": data.direction,
            "amount_in": data.amount_in,
            "fee_pct": fee_pct,
            "fee_amount": fee_amount,
            "amount_out": amount_out,
            "client_id": client.id if client else None,
        },
    )
    await db.commit()
    await db.refresh(tx)

    # Send WhatsApp notification asynchronously
    if client:
        background.add_task(
            whatsapp.send_transaction_notification,
            phone=client.phone,
            client_name=client.name,
            direction=data.direction.value,
            amount_in=data.amount_in,
            fee_pct=fee_pct,
            fee_amount=fee_amount,
            amount_out=amount_out,
            usdt_balance=client.usdt_balance,
            usd_balance=client.usd_balance,
            base_url=settings.base_url,
        )

    return tx


@router.get("", response_model=list[TransactionOut])
async def list_transactions(
    limit: int = 50,
    offset: int = 0,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(models.Transaction).order_by(models.Transaction.created_at.desc()).limit(limit).offset(offset)
    if user.role != models.UserRole.admin:
        q = q.where(models.Transaction.operator_id == user.id)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{tx_id}", response_model=TransactionOut)
async def get_transaction(
    tx_id: int,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.Transaction).where(models.Transaction.id == tx_id))
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transação não encontrada")
    if user.role != models.UserRole.admin and tx.operator_id != user.id:
        raise HTTPException(status_code=403, detail="Acesso negado")
    return tx
