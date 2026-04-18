from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from auth import get_current_user, verify_pin
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
    # Verify operator PIN
    if not user.pin_hash:
        raise HTTPException(status_code=403, detail="Você precisa cadastrar um PIN antes de realizar transações")

    if user.pin_locked:
        raise HTTPException(
            status_code=403,
            detail="Usuário bloqueado por excesso de tentativas de PIN incorreto. Contate o administrador.",
        )

    if not verify_pin(data.operator_pin, user.pin_hash):
        user.pin_failed_attempts = (user.pin_failed_attempts or 0) + 1
        attempts_left = max(0, 3 - user.pin_failed_attempts)

        if user.pin_failed_attempts >= 3:
            user.pin_locked = True
            await audit.log(
                db, action="pin_lockout", username=user.username,
                request=request, user_id=user.id, entity_type="operator",
                new_value={"reason": "3 tentativas de PIN incorreto"},
            )
            await db.commit()
            raise HTTPException(
                status_code=403,
                detail="Usuário bloqueado após 3 tentativas incorretas de PIN. Contate o administrador.",
            )

        await audit.log(
            db, action="transaction_pin_failed", username=user.username,
            request=request, user_id=user.id, entity_type="transaction",
            new_value={"attempts": user.pin_failed_attempts, "attempts_left": attempts_left},
        )
        await db.commit()
        raise HTTPException(
            status_code=401,
            detail=f"PIN incorreto. Tentativas restantes: {attempts_left}",
        )

    # PIN correct — reset failed attempts counter
    if user.pin_failed_attempts:
        user.pin_failed_attempts = 0

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
    credit_amount_used = 0.0
    if data.client_id:
        cl_res = await db.execute(select(models.Client).where(models.Client.id == data.client_id))
        client = cl_res.scalar_one_or_none()
        if not client:
            raise HTTPException(status_code=404, detail="Cliente não encontrado")
        client_name = client_name or client.name

        # Check if credit is needed
        if data.direction == models.Direction.usdt_to_usd:
            client_balance = client.usdt_balance
        else:
            client_balance = client.usd_balance

        if client_balance < data.amount_in:
            credit_needed = round(data.amount_in - max(0.0, client_balance), 6)
            available_credit = round(client.credit_limit - client.credit_used, 6)

            if credit_needed > available_credit + 0.000001:
                raise HTTPException(
                    status_code=422,
                    detail=f"Saldo insuficiente. Saldo: {client_balance:.2f}, Crédito disponível: {available_credit:.2f}",
                )

            if not data.credit_approval_code:
                raise HTTPException(
                    status_code=402,
                    detail={
                        "credit_needed": True,
                        "client_id": client.id,
                        "direction": data.direction.value,
                        "amount_in": data.amount_in,
                        "client_balance": client_balance,
                        "credit_amount": credit_needed,
                        "interest_pct": client.credit_interest_pct,
                        "interest_days": client.credit_interest_days,
                    },
                )

            # Verify credit approval OTP
            otp_res = await db.execute(
                select(models.CreditApprovalOTP).where(
                    models.CreditApprovalOTP.client_id == client.id,
                    models.CreditApprovalOTP.code == data.credit_approval_code,
                    models.CreditApprovalOTP.used == False,
                    models.CreditApprovalOTP.direction == data.direction,
                )
            )
            otp = otp_res.scalar_one_or_none()
            if not otp:
                raise HTTPException(status_code=400, detail="Código de aprovação inválido ou já utilizado")
            if otp.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
                raise HTTPException(status_code=400, detail="Código de aprovação expirado")

            otp.used = True
            credit_amount_used = credit_needed
            client.credit_used = round(client.credit_used + credit_needed, 6)

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
        credit_amount_used=credit_amount_used,
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
            client.usdt_balance = round(max(0.0, client.usdt_balance) - data.amount_in + credit_amount_used, 6)
            client.usd_balance = round(client.usd_balance + amount_out, 6)
        else:
            client.usd_balance = round(max(0.0, client.usd_balance) - data.amount_in + credit_amount_used, 6)
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
