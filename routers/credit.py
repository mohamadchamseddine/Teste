import random
import string
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import get_current_user
from schemas import CreditApprovalRequest
import models
import whatsapp
import audit

router = APIRouter(prefix="/api/credit", tags=["credit"])


def _generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


@router.post("/request-approval")
async def request_credit_approval(
    data: CreditApprovalRequest,
    background: BackgroundTasks,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cl_res = await db.execute(select(models.Client).where(models.Client.id == data.client_id))
    client = cl_res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    if data.direction == models.Direction.usdt_to_usd:
        client_balance = client.usdt_balance
    else:
        client_balance = client.usd_balance

    credit_amount = round(max(0.0, data.amount_in - client_balance), 6)
    available_credit = round(client.credit_limit - client.credit_used, 6)

    if credit_amount <= 0:
        raise HTTPException(status_code=400, detail="Nenhum crédito necessário para esta transação")
    if available_credit < credit_amount - 0.000001:
        raise HTTPException(
            status_code=422,
            detail=f"Crédito insuficiente. Disponível: {available_credit:.2f}, Necessário: {credit_amount:.2f}",
        )

    # Invalidate previous unused OTPs for this client
    prev_res = await db.execute(
        select(models.CreditApprovalOTP).where(
            models.CreditApprovalOTP.client_id == data.client_id,
            models.CreditApprovalOTP.used == False,
        )
    )
    for prev in prev_res.scalars().all():
        prev.used = True

    # Load fee to calculate interest preview (interest applies only to fee profit)
    cfg_res = await db.execute(select(models.AppSettings).where(models.AppSettings.id == 1))
    cfg = cfg_res.scalar_one_or_none()
    fee_pct = cfg.fee_pct if cfg else 1.0
    fee_amount = round(data.amount_in * fee_pct / 100, 6)
    interest_amount = round(fee_amount * client.credit_interest_pct / 100, 6)

    code = _generate_code()
    otp = models.CreditApprovalOTP(
        client_id=data.client_id,
        code=code,
        direction=data.direction,
        amount_in=data.amount_in,
        credit_amount=credit_amount,
        interest_pct=client.credit_interest_pct,
        interest_days=client.credit_interest_days,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(otp)
    await db.commit()

    background.add_task(
        whatsapp.send_credit_approval_otp,
        phone=client.phone,
        client_name=client.name,
        credit_amount=credit_amount,
        interest_pct=client.credit_interest_pct,
        interest_days=client.credit_interest_days,
        interest_amount=interest_amount,
        code=code,
    )

    return {"message": "Código enviado ao cliente via WhatsApp", "expires_in_minutes": 10}
