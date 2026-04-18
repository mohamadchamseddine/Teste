from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import get_current_user, require_admin
from schemas import FeeOut, FeeUpdate
import models
import audit

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/fee", response_model=FeeOut)
async def get_fee(
    _: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.AppSettings).where(models.AppSettings.id == 1))
    cfg = result.scalar_one_or_none()
    return FeeOut(fee_pct=cfg.fee_pct if cfg else 1.0)


@router.put("/fee", response_model=FeeOut)
async def update_fee(
    data: FeeUpdate,
    request: Request,
    admin: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.AppSettings).where(models.AppSettings.id == 1))
    cfg = result.scalar_one_or_none()
    old_fee = cfg.fee_pct if cfg else 1.0

    if cfg:
        cfg.fee_pct = data.fee_pct
    else:
        cfg = models.AppSettings(id=1, fee_pct=data.fee_pct)
        db.add(cfg)

    await audit.log(
        db, action="update_fee", username=admin.username,
        request=request, user_id=admin.id,
        entity_type="settings", entity_id=1,
        old_value={"fee_pct": old_fee}, new_value={"fee_pct": data.fee_pct},
    )
    await db.commit()
    return FeeOut(fee_pct=data.fee_pct)
