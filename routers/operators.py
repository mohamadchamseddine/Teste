from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import require_admin, hash_password
from schemas import OperatorCreate, OperatorUpdate, UserOut
import models
import audit

router = APIRouter(prefix="/api/operators", tags=["operators"])


@router.get("", response_model=list[UserOut])
async def list_operators(
    _: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.User).order_by(models.User.created_at))
    return result.scalars().all()


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
    return user


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
    return user
