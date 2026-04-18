import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from database import AsyncSessionLocal
import models
import blockchain
import whatsapp
from config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scan_usdt_deposits():
    """Periodically check each client's deposit address for incoming USDT TRC20 transactions."""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(models.Client).where(
                    models.Client.deposit_address.isnot(None),
                    models.Client.is_active == True,
                )
            )
            clients = result.scalars().all()

            for client in clients:
                try:
                    txs = await blockchain.get_trc20_incoming(client.deposit_address)
                    for tx in txs:
                        tx_hash = tx.get("transaction_id", "")
                        if not tx_hash:
                            continue

                        # Check idempotency
                        existing = await db.execute(
                            select(models.USDTDeposit).where(models.USDTDeposit.tx_hash == tx_hash)
                        )
                        if existing.scalar_one_or_none():
                            continue

                        raw_value = tx.get("value", "0")
                        amount = blockchain.parse_trc20_amount(raw_value)
                        if amount <= 0:
                            continue

                        # Record deposit
                        deposit = models.USDTDeposit(
                            client_id=client.id,
                            tx_hash=tx_hash,
                            amount=amount,
                        )
                        db.add(deposit)

                        # Update client balance
                        client.usdt_balance = round(client.usdt_balance + amount, 6)

                        # Update cash USDT balance
                        bal_res = await db.execute(
                            select(models.CashBalance).where(
                                models.CashBalance.currency == models.Currency.USDT
                            )
                        )
                        cash = bal_res.scalar_one_or_none()
                        if cash:
                            cash.balance = round(cash.balance + amount, 6)
                        else:
                            db.add(models.CashBalance(currency=models.Currency.USDT, balance=amount))

                        # Audit log
                        audit_entry = models.AuditLog(
                            username="system",
                            action="usdt_deposit_detected",
                            entity_type="usdt_deposit",
                            ip_address="blockchain",
                            machine_name="scanner",
                            new_value={
                                "client_id": client.id,
                                "tx_hash": tx_hash,
                                "amount": amount,
                            },
                        )
                        db.add(audit_entry)
                        await db.flush()

                        await db.commit()
                        logger.info("Depósito USDT confirmado: %s → %s USDT (client %d)", tx_hash, amount, client.id)

                        # Notify via WhatsApp (non-blocking)
                        try:
                            await whatsapp.send_deposit_notification(
                                phone=client.phone,
                                client_name=client.name,
                                amount=amount,
                                tx_hash=tx_hash,
                                usdt_balance=client.usdt_balance,
                                base_url=settings.base_url,
                            )
                        except Exception as exc:
                            logger.error("WhatsApp deposit notify failed: %s", exc)

                except Exception as exc:
                    logger.error("Erro ao escanear cliente %d: %s", client.id, exc)
                    await db.rollback()

        except Exception as exc:
            logger.error("Erro no scanner geral: %s", exc)


def start_scheduler():
    scheduler.add_job(scan_usdt_deposits, "interval", seconds=60, id="usdt_scanner")
    scheduler.start()
    logger.info("Scheduler iniciado — escaneando depósitos USDT a cada 60s")


def stop_scheduler():
    scheduler.shutdown(wait=False)
