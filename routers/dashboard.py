from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from auth import get_current_user, require_admin
from schemas import DashboardStats, ProfitSummary, ClientProfitOut
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
    stats = DashboardStats(my_transactions_today=my_count_res.scalar() or 0)

    # Volume today
    if is_admin or user.can_see_volume:
        vol_res = await db.execute(
            select(func.sum(models.Transaction.amount_in)).where(
                models.Transaction.created_at >= today_start
            )
        )
        stats.total_volume_today = round(vol_res.scalar() or 0, 2)

    # Fee today + all-time split by currency
    if is_admin or user.can_see_profits:
        fee_today_res = await db.execute(
            select(func.sum(models.Transaction.fee_amount)).where(
                models.Transaction.created_at >= today_start
            )
        )
        stats.total_fee_today = round(fee_today_res.scalar() or 0, 2)

        # All-time USDT fees (from USDT→USD transactions, fee paid in USDT)
        fee_usdt_res = await db.execute(
            select(func.sum(models.Transaction.fee_amount)).where(
                models.Transaction.direction == models.Direction.usdt_to_usd
            )
        )
        stats.total_fee_usdt_alltime = round(fee_usdt_res.scalar() or 0, 6)

        # All-time USD fees (from USD→USDT transactions, fee paid in USD)
        fee_usd_res = await db.execute(
            select(func.sum(models.Transaction.fee_amount)).where(
                models.Transaction.direction == models.Direction.usd_to_usdt
            )
        )
        stats.total_fee_usd_alltime = round(fee_usd_res.scalar() or 0, 6)

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


@router.get("/profits", response_model=ProfitSummary)
async def profits_summary(
    _: models.User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Totals
    count_res = await db.execute(select(func.count(models.Transaction.id)))
    fee_usdt_res = await db.execute(
        select(func.sum(models.Transaction.fee_amount)).where(
            models.Transaction.direction == models.Direction.usdt_to_usd
        )
    )
    fee_usd_res = await db.execute(
        select(func.sum(models.Transaction.fee_amount)).where(
            models.Transaction.direction == models.Direction.usd_to_usdt
        )
    )
    vol_usdt_res = await db.execute(
        select(func.sum(models.Transaction.amount_in)).where(
            models.Transaction.direction == models.Direction.usdt_to_usd
        )
    )
    vol_usd_res = await db.execute(
        select(func.sum(models.Transaction.amount_in)).where(
            models.Transaction.direction == models.Direction.usd_to_usdt
        )
    )

    # Per-client profits: aggregate by client_id
    per_client_res = await db.execute(
        select(
            models.Transaction.client_id,
            func.count(models.Transaction.id).label("total_transactions"),
            func.sum(
                func.case(
                    (models.Transaction.direction == models.Direction.usdt_to_usd, models.Transaction.fee_amount),
                    else_=0,
                )
            ).label("fee_usdt"),
            func.sum(
                func.case(
                    (models.Transaction.direction == models.Direction.usd_to_usdt, models.Transaction.fee_amount),
                    else_=0,
                )
            ).label("fee_usd"),
        )
        .where(models.Transaction.client_id.isnot(None))
        .group_by(models.Transaction.client_id)
    )
    rows = per_client_res.all()

    # Load client details
    client_ids = [r.client_id for r in rows]
    clients_map: dict[int, models.Client] = {}
    if client_ids:
        cl_res = await db.execute(
            select(models.Client).where(models.Client.id.in_(client_ids))
        )
        clients_map = {c.id: c for c in cl_res.scalars().all()}

    per_client = []
    for r in rows:
        client = clients_map.get(r.client_id)
        if not client:
            continue
        fee_usdt = round(r.fee_usdt or 0, 6)
        fee_usd = round(r.fee_usd or 0, 6)
        per_client.append(ClientProfitOut(
            client_id=client.id,
            client_name=client.name,
            phone=client.phone,
            total_transactions=r.total_transactions,
            fee_usdt=fee_usdt,
            fee_usd=fee_usd,
            total_fee_usd_equivalent=round(fee_usdt + fee_usd, 6),
        ))

    per_client.sort(key=lambda x: x.total_fee_usd_equivalent, reverse=True)

    return ProfitSummary(
        total_transactions=count_res.scalar() or 0,
        total_fee_usdt=round(fee_usdt_res.scalar() or 0, 6),
        total_fee_usd=round(fee_usd_res.scalar() or 0, 6),
        total_volume_usdt=round(vol_usdt_res.scalar() or 0, 2),
        total_volume_usd=round(vol_usd_res.scalar() or 0, 2),
        per_client=per_client,
    )
