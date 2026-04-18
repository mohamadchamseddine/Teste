import random
import string
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from auth import get_current_user, get_current_client, create_token
from schemas import (
    ClientCreate, ClientOut, ClientBalanceOut,
    OTPRequest, OTPVerify, TransactionOut,
)
import models
import audit
import whatsapp
import blockchain

router = APIRouter(tags=["clients"])


def _generate_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


# ── Registration (operators/admin) ────────────────────────────────────────────

@router.get("/api/clients", response_model=list[ClientOut])
async def list_clients(
    _: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.Client).order_by(models.Client.created_at.desc()))
    return result.scalars().all()


@router.post("/api/clients", response_model=ClientOut, status_code=201)
async def create_client(
    data: ClientCreate,
    request: Request,
    background: BackgroundTasks,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(models.Client).where(models.Client.phone == data.phone))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Telefone já cadastrado")

    # Get next available deposit address index
    max_idx_res = await db.execute(
        select(func.max(models.Client.deposit_address_index))
    )
    max_idx = max_idx_res.scalar() or -1
    next_idx = max_idx + 1

    deposit_address = blockchain.get_next_deposit_address(next_idx)

    client = models.Client(
        name=data.name,
        phone=data.phone,
        credit_limit=data.credit_limit,
        credit_interest_pct=data.credit_interest_pct,
        credit_interest_days=data.credit_interest_days,
        deposit_address=deposit_address,
        deposit_address_index=next_idx if deposit_address else None,
    )
    db.add(client)
    await db.flush()

    await audit.log(
        db, action="create_client", username=user.username,
        request=request, user_id=user.id,
        entity_type="client", entity_id=client.id,
        new_value={"name": data.name, "phone": data.phone},
    )
    await db.commit()
    await db.refresh(client)
    return client


# ── Client auth (WhatsApp OTP) ────────────────────────────────────────────────

@router.post("/api/client/request-otp")
async def request_otp(
    data: OTPRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.Client).where(models.Client.phone == data.phone))
    client = result.scalar_one_or_none()
    if not client or not client.is_active:
        # Don't reveal if phone exists
        return {"detail": "Se o número estiver cadastrado, você receberá um código."}

    code = _generate_otp()
    otp = models.OTPCode(
        client_id=client.id,
        code=code,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db.add(otp)
    await db.commit()

    background.add_task(whatsapp.send_otp, phone=client.phone, code=code)
    return {"detail": "Código enviado via WhatsApp."}


@router.post("/api/client/verify-otp")
async def verify_otp(
    data: OTPVerify,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    cl_res = await db.execute(select(models.Client).where(models.Client.phone == data.phone))
    client = cl_res.scalar_one_or_none()
    if not client or not client.is_active:
        raise HTTPException(status_code=401, detail="Código inválido ou expirado")

    now = datetime.now(timezone.utc)
    otp_res = await db.execute(
        select(models.OTPCode).where(
            models.OTPCode.client_id == client.id,
            models.OTPCode.code == data.code,
            models.OTPCode.used == False,
            models.OTPCode.expires_at > now,
        )
    )
    otp = otp_res.scalar_one_or_none()
    if not otp:
        raise HTTPException(status_code=401, detail="Código inválido ou expirado")

    otp.used = True
    await db.commit()

    token = create_token(f"client:{client.id}")
    response.set_cookie("client_token", token, httponly=True, samesite="lax")
    return {"access_token": token, "token_type": "bearer"}


@router.post("/api/client/logout")
async def client_logout(response: Response):
    response.delete_cookie("client_token")
    return {"detail": "Logout realizado"}


# ── Client self-service ───────────────────────────────────────────────────────

@router.get("/api/clients/{client_id}/balance", response_model=ClientBalanceOut)
async def get_client_balance(
    client_id: int,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.Client).where(models.Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return ClientBalanceOut(usdt_balance=client.usdt_balance, usd_balance=client.usd_balance)


@router.get("/api/client/me/balance", response_model=ClientBalanceOut)
async def client_my_balance(client: models.Client = Depends(get_current_client)):
    return ClientBalanceOut(usdt_balance=client.usdt_balance, usd_balance=client.usd_balance)


@router.get("/api/clients/{client_id}/statement", response_model=list[TransactionOut])
async def get_client_statement(
    client_id: int,
    limit: int = 100,
    _: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.Transaction)
        .where(models.Transaction.client_id == client_id)
        .order_by(models.Transaction.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/api/client/me/statement", response_model=list[TransactionOut])
async def client_my_statement(
    limit: int = 100,
    client: models.Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.Transaction)
        .where(models.Transaction.client_id == client.id)
        .order_by(models.Transaction.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/api/clients/{client_id}/deposit-qr")
async def get_deposit_qr(
    client_id: int,
    _: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.Client).where(models.Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client or not client.deposit_address:
        raise HTTPException(status_code=404, detail="Endereço de depósito não disponível")
    png = blockchain.generate_deposit_qr_png(client.deposit_address)
    return FastAPIResponse(content=png, media_type="image/png")


@router.get("/api/client/me/deposit-qr")
async def client_my_deposit_qr(client: models.Client = Depends(get_current_client)):
    if not client.deposit_address:
        raise HTTPException(status_code=404, detail="Endereço de depósito não disponível")
    png = blockchain.generate_deposit_qr_png(client.deposit_address)
    return FastAPIResponse(content=png, media_type="image/png")
