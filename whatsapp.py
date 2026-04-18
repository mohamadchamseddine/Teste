import httpx
import logging
from config import settings

logger = logging.getLogger(__name__)


async def send_message(phone: str, text: str) -> bool:
    if not settings.evolution_api_key or not settings.evolution_instance:
        logger.warning("WhatsApp não configurado — mensagem não enviada para %s", phone)
        return False

    url = f"{settings.evolution_api_url}/message/sendText/{settings.evolution_instance}"
    payload = {"number": phone, "text": text}
    headers = {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code in (200, 201):
                return True
            logger.error("WhatsApp erro %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.error("WhatsApp exception: %s", exc)
    return False


async def send_otp(phone: str, code: str) -> bool:
    text = (
        f"🔐 *Código de acesso*\n\n"
        f"Seu código é: *{code}*\n"
        f"Válido por 5 minutos.\n\n"
        f"Nunca compartilhe este código."
    )
    return await send_message(phone, text)


async def send_transaction_notification(
    phone: str,
    client_name: str,
    direction: str,
    amount_in: float,
    fee_pct: float,
    fee_amount: float,
    amount_out: float,
    usdt_balance: float,
    usd_balance: float,
    base_url: str,
) -> bool:
    if direction == "usdt_to_usd":
        dir_label = "USDT → USD"
        currency_in, currency_out = "USDT", "USD"
    else:
        dir_label = "USD → USDT"
        currency_in, currency_out = "USD", "USDT"

    text = (
        f"✅ *Nova transação registrada*\n\n"
        f"Olá, {client_name}!\n\n"
        f"• Tipo: {dir_label}\n"
        f"• Valor recebido: {amount_in:,.2f} {currency_in}\n"
        f"• Taxa ({fee_pct}%): {fee_amount:,.2f} {currency_in}\n"
        f"• Valor entregue: {amount_out:,.2f} {currency_out}\n\n"
        f"*Saldo atual:*\n"
        f"💲 USDT: {usdt_balance:,.2f}\n"
        f"💵 USD: {usd_balance:,.2f}\n\n"
        f"Acesse seu extrato: {base_url}/client/statement"
    )
    return await send_message(phone, text)


async def send_credit_approval_otp(
    phone: str,
    client_name: str,
    credit_amount: float,
    interest_pct: float,
    interest_days: int,
    code: str,
) -> bool:
    text = (
        f"🔔 *Aprovação de Crédito*\n\n"
        f"Olá, {client_name}!\n\n"
        f"Uma transação está sendo processada utilizando seu limite de crédito:\n\n"
        f"• Valor do crédito: *{credit_amount:,.2f}*\n"
        f"• Juros: *{interest_pct}% a cada {interest_days} dias*\n\n"
        f"Se você autoriza esta operação, informe o código abaixo ao operador:\n\n"
        f"🔑 *Código: {code}*\n\n"
        f"⚠️ Válido por 10 minutos. Não compartilhe com ninguém além do operador."
    )
    return await send_message(phone, text)


async def send_deposit_notification(
    phone: str,
    client_name: str,
    amount: float,
    tx_hash: str,
    usdt_balance: float,
    base_url: str,
) -> bool:
    text = (
        f"✅ *Depósito USDT confirmado!*\n\n"
        f"Olá, {client_name}!\n\n"
        f"• Valor recebido: {amount:,.6f} USDT\n"
        f"• TX: {tx_hash[:20]}...\n\n"
        f"*Saldo USDT atual: {usdt_balance:,.2f}*\n\n"
        f"Acesse seu extrato: {base_url}/client/statement"
    )
    return await send_message(phone, text)
