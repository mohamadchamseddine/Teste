import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from database import engine, get_db, Base
from auth import get_current_user, get_current_client, decode_token, hash_password
import models
from scheduler import start_scheduler, stop_scheduler
from routers import auth as auth_router
from routers import operators, transactions, clients, balance, audit_router, dashboard, credit
from routers import settings as settings_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Exchange USDT ↔ USD", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(auth_router.router)
app.include_router(operators.router)
app.include_router(settings_router.router)
app.include_router(transactions.router)
app.include_router(clients.router)
app.include_router(balance.router)
app.include_router(audit_router.router)
app.include_router(dashboard.router)
app.include_router(credit.router)


async def seed_database():
    async with engine.begin() as conn:
        from database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            # Create admin if not exists
            result = await db.execute(select(models.User).where(models.User.username == "admin"))
            if not result.scalar_one_or_none():
                admin = models.User(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    role=models.UserRole.admin,
                )
                db.add(admin)
                logger.info("Admin criado: admin / admin123 (troque a senha!)")

            # Create default app settings
            cfg_res = await db.execute(select(models.AppSettings).where(models.AppSettings.id == 1))
            if not cfg_res.scalar_one_or_none():
                db.add(models.AppSettings(id=1, fee_pct=1.0))

            # Create cash balances
            for currency in models.Currency:
                bal_res = await db.execute(
                    select(models.CashBalance).where(models.CashBalance.currency == currency)
                )
                if not bal_res.scalar_one_or_none():
                    db.add(models.CashBalance(currency=currency, balance=0.0))

            await db.commit()


# ── Helper to get user from cookie for web pages ──────────────────────────────

async def get_user_from_cookie(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    subject = decode_token(token)
    if not subject or not subject.startswith("op:"):
        return None
    user_id = int(subject.split(":")[1])
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalar_one_or_none()
    return user if user and user.is_active else None


async def get_client_from_cookie(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("client_token")
    if not token:
        return None
    subject = decode_token(token)
    if not subject or not subject.startswith("client:"):
        return None
    client_id = int(subject.split(":")[1])
    result = await db.execute(select(models.Client).where(models.Client.id == client_id))
    client = result.scalar_one_or_none()
    return client if client and client.is_active else None


# ── Web pages ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if user:
        return RedirectResponse("/dashboard")
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})


@app.get("/transactions", response_class=HTMLResponse)
async def transactions_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("history.html", {"request": request, "user": user})


@app.get("/transactions/new", response_class=HTMLResponse)
async def new_transaction_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("new_transaction.html", {"request": request, "user": user})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    if user.role != models.UserRole.admin:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("admin.html", {"request": request, "user": user})


@app.get("/balance", response_class=HTMLResponse)
async def balance_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    if user.role != models.UserRole.admin:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("balance.html", {"request": request, "user": user})


@app.get("/profits", response_class=HTMLResponse)
async def profits_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    if user.role != models.UserRole.admin:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("profits.html", {"request": request, "user": user})


@app.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    if user.role != models.UserRole.admin:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("audit.html", {"request": request, "user": user})


@app.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("clients.html", {"request": request, "user": user})


# ── Client portal web pages ───────────────────────────────────────────────────

@app.get("/client/login", response_class=HTMLResponse)
async def client_login_page(request: Request):
    return templates.TemplateResponse("client/login.html", {"request": request})


@app.get("/client/dashboard", response_class=HTMLResponse)
async def client_dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
    client = await get_client_from_cookie(request, db)
    if not client:
        return RedirectResponse("/client/login")
    return templates.TemplateResponse("client/dashboard.html", {"request": request, "client": client})


@app.get("/client/deposit", response_class=HTMLResponse)
async def client_deposit_page(request: Request, db: AsyncSession = Depends(get_db)):
    client = await get_client_from_cookie(request, db)
    if not client:
        return RedirectResponse("/client/login")
    return templates.TemplateResponse("client/deposit.html", {"request": request, "client": client})


@app.get("/client/statement", response_class=HTMLResponse)
async def client_statement_page(request: Request, db: AsyncSession = Depends(get_db)):
    client = await get_client_from_cookie(request, db)
    if not client:
        return RedirectResponse("/client/login")
    return templates.TemplateResponse("client/statement.html", {"request": request, "client": client})
