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
    ClientCreate, ClientUpdate, ClientOut, ClientBalanceOut,
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


@router.patch("/api/clients/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: int,
    data: ClientUpdate,
    request: Request,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.Client).where(models.Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    if data.phone and data.phone != client.phone:
        existing = await db.execute(select(models.Client).where(models.Client.phone == data.phone))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Telefone já cadastrado")

    old = {"name": client.name, "phone": client.phone, "is_active": client.is_active,
           "credit_limit": client.credit_limit, "credit_interest_pct": client.credit_interest_pct,
           "credit_interest_days": client.credit_interest_days}

    if data.name is not None:
        client.name = data.name
    if data.phone is not None:
        client.phone = data.phone
    if data.is_active is not None:
        client.is_active = data.is_active
    if data.credit_limit is not None:
        client.credit_limit = data.credit_limit
    if data.credit_interest_pct is not None:
        client.credit_interest_pct = data.credit_interest_pct
    if data.credit_interest_days is not None:
        client.credit_interest_days = data.credit_interest_days

    await audit.log(
        db, action="update_client", username=user.username,
        request=request, user_id=user.id,
        entity_type="client", entity_id=client.id,
        old_value=old,
        new_value={"name": client.name, "phone": client.phone, "is_active": client.is_active,
                   "credit_limit": client.credit_limit, "credit_interest_pct": client.credit_interest_pct,
                   "credit_interest_days": client.credit_interest_days},
    )
    await db.commit()
    await db.refresh(client)
    return client


# ── Client auth (PIN) ─────────────────────────────────────────────────────────

@router.post("/api/client/login")
async def client_login(
    data: OTPVerify,  # reuse schema: phone + code(=pin)
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    cl_res = await db.execute(select(models.Client).where(models.Client.phone == data.phone))
    client = cl_res.scalar_one_or_none()
    if not client or not client.is_active:
        raise HTTPException(status_code=401, detail="Telefone ou PIN inválido")
    if not client.pin_hash:
        raise HTTPException(status_code=401, detail="PIN não cadastrado. Contate o operador.")
    from auth import verify_pin
    if not verify_pin(data.code, client.pin_hash):
        raise HTTPException(status_code=401, detail="Telefone ou PIN inválido")

    token = create_token(f"client:{client.id}")
    response.set_cookie("client_token", token, httponly=True, samesite="lax")
    return {"access_token": token, "token_type": "bearer"}


@router.put("/api/clients/{client_id}/pin")
async def set_client_pin(
    client_id: int,
    data: dict,
    request: Request,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pin = data.get("pin", "")
    if not pin or not str(pin).isdigit() or len(str(pin)) != 4:
        raise HTTPException(status_code=422, detail="PIN deve ter exatamente 4 dígitos numéricos")

    cl_res = await db.execute(select(models.Client).where(models.Client.id == client_id))
    client = cl_res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    from auth import hash_pin
    client.pin_hash = hash_pin(str(pin))

    await audit.log(
        db, action="set_client_pin", username=user.username,
        request=request, user_id=user.id,
        entity_type="client", entity_id=client.id,
    )
    await db.commit()
    return {"detail": "PIN definido com sucesso"}


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


@router.post("/api/clients/{client_id}/generate-address")
async def generate_client_address(
    client_id: int,
    request: Request,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.Client).where(models.Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    if client.deposit_address:
        return {"deposit_address": client.deposit_address}

    max_idx_res = await db.execute(select(func.max(models.Client.deposit_address_index)))
    max_idx = max_idx_res.scalar() or -1
    next_idx = max_idx + 1

    address = blockchain.get_next_deposit_address(next_idx)
    if not address:
        raise HTTPException(status_code=503, detail="TRON_MNEMONIC não configurado no servidor")

    client.deposit_address = address
    client.deposit_address_index = next_idx

    await audit.log(
        db, action="generate_deposit_address", username=user.username,
        request=request, user_id=user.id,
        entity_type="client", entity_id=client.id,
        new_value={"deposit_address": address},
    )
    await db.commit()
    return {"deposit_address": address}


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
