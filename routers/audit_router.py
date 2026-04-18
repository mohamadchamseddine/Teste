from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from datetime import datetime

from database import get_db
from auth import require_admin
from schemas import AuditLogOut
import models

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditLogOut])
async def list_audit(
    limit: int = Query(100, le=500),
    offset: int = 0,
    username: Optional[str] = None,
    action: Optional[str] = None,
    _: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(models.AuditLog).order_by(models.AuditLog.created_at.desc()).limit(limit).offset(offset)
    if username:
        q = q.where(models.AuditLog.username.ilike(f"%{username}%"))
    if action:
        q = q.where(models.AuditLog.action == action)
    result = await db.execute(q)
    return result.scalars().all()
