from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from auth import get_current_user
from schemas import DashboardStats, TransactionOut
import models

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    is_admin = user.role == models.UserRole.admin

    # My transactions today
    my_count_res = await db.execute(
        select(func.count(models.Transaction.id)).where(
            models.Transaction.operator_id == user.id,
            models.Transaction.created_at >= today_start,
        )
    )
    my_count = my_count_res.scalar() or 0

    stats = DashboardStats(my_transactions_today=my_count)

    # Volume today
    if is_admin or user.can_see_volume:
        vol_res = await db.execute(
            select(func.sum(models.Transaction.amount_in)).where(
                models.Transaction.created_at >= today_start
            )
        )
        stats.total_volume_today = round(vol_res.scalar() or 0, 2)

    # Fee today
    if is_admin or user.can_see_profits:
        fee_res = await db.execute(
            select(func.sum(models.Transaction.fee_amount)).where(
                models.Transaction.created_at >= today_start
            )
        )
        stats.total_fee_today = round(fee_res.scalar() or 0, 2)

    # Cash balances
    if is_admin or user.can_see_balance:
        bal_res = await db.execute(select(models.CashBalance))
        balances = {b.currency: b.balance for b in bal_res.scalars().all()}
        stats.usdt_balance = balances.get(models.Currency.USDT, 0.0)
        stats.usd_balance = balances.get(models.Currency.USD, 0.0)

    # Admin-only: client totals and company equity
    if is_admin:
        cl_usdt_res = await db.execute(select(func.sum(models.Client.usdt_balance)))
        cl_usd_res = await db.execute(select(func.sum(models.Client.usd_balance)))
        cl_usdt = round(cl_usdt_res.scalar() or 0, 2)
        cl_usd = round(cl_usd_res.scalar() or 0, 2)
        stats.clients_usdt_total = cl_usdt
        stats.clients_usd_total = cl_usd
        stats.company_usdt = round((stats.usdt_balance or 0) - cl_usdt, 2)
        stats.company_usd = round((stats.usd_balance or 0) - cl_usd, 2)

    # Recent transactions
    tx_q = (
        select(models.Transaction)
        .order_by(models.Transaction.created_at.desc())
        .limit(10)
    )
    if not is_admin:
        tx_q = tx_q.where(models.Transaction.operator_id == user.id)
    tx_res = await db.execute(tx_q)
    stats.recent_transactions = tx_res.scalars().all()

    return stats
