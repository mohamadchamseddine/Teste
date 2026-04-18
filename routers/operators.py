from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import require_admin, get_current_user, hash_password, hash_pin
from schemas import OperatorCreate, OperatorUpdate, OperatorSetPin, UserOut
import models
import audit

router = APIRouter(prefix="/api/operators", tags=["operators"])


@router.get("", response_model=list[UserOut])
async def list_operators(
    _: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.User).order_by(models.User.created_at))
    users = result.scalars().all()
    out = []
    for u in users:
        d = UserOut.model_validate(u)
        d.has_pin = u.pin_hash is not None
        out.append(d)
    return out


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_operator(
    data: OperatorCreate,
    request: Request,
    admin: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(models.User).where(models.User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Nome de usuário já existe")

    user = models.User(
        username=data.username,
        password_hash=hash_password(data.password),
        pin_hash=hash_pin(data.pin),
        role=data.role,
    )
    db.add(user)
    await db.flush()

    await audit.log(
        db, action="create_operator", username=admin.username,
        request=request, user_id=admin.id,
        entity_type="operator", entity_id=user.id,
        new_value={"username": user.username, "role": user.role},
    )
    await db.commit()
    await db.refresh(user)
    result = UserOut.model_validate(user)
    result.has_pin = user.pin_hash is not None
    return result


@router.patch("/{operator_id}", response_model=UserOut)
async def update_operator(
    operator_id: int,
    data: OperatorUpdate,
    request: Request,
    admin: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.User).where(models.User.id == operator_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Operador não encontrado")

    old = {
        "is_active": user.is_active,
        "can_see_profits": user.can_see_profits,
        "can_see_volume": user.can_see_volume,
        "can_see_balance": user.can_see_balance,
    }

    if data.is_active is not None:
        user.is_active = data.is_active
    if data.can_see_profits is not None:
        user.can_see_profits = data.can_see_profits
    if data.can_see_volume is not None:
        user.can_see_volume = data.can_see_volume
    if data.can_see_balance is not None:
        user.can_see_balance = data.can_see_balance

    new = {
        "is_active": user.is_active,
        "can_see_profits": user.can_see_profits,
        "can_see_volume": user.can_see_volume,
        "can_see_balance": user.can_see_balance,
    }

    await audit.log(
        db, action="update_operator", username=admin.username,
        request=request, user_id=admin.id,
        entity_type="operator", entity_id=user.id,
        old_value=old, new_value=new,
    )
    await db.commit()
    await db.refresh(user)
    out = UserOut.model_validate(user)
    out.has_pin = user.pin_hash is not None
    return out


@router.put("/{operator_id}/pin", response_model=UserOut)
async def set_operator_pin(
    operator_id: int,
    data: OperatorSetPin,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Admin pode trocar PIN de qualquer operador; operador só pode trocar o próprio
    if current_user.role != models.UserRole.admin and current_user.id != operator_id:
        raise HTTPException(status_code=403, detail="Acesso negado")

    result = await db.execute(select(models.User).where(models.User.id == operator_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Operador não encontrado")

    user.pin_hash = hash_pin(data.pin)

    await audit.log(
        db, action="set_pin", username=current_user.username,
        request=request, user_id=current_user.id,
        entity_type="operator", entity_id=user.id,
    )
    await db.commit()
    await db.refresh(user)
    out = UserOut.model_validate(user)
    out.has_pin = True
    return out
