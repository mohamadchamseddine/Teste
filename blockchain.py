import io
import logging
import httpx
import qrcode
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

USDT_CONTRACT_MAINNET = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_DECIMALS = 6


def _derive_tron_address(mnemonic: str, index: int) -> tuple[str, str]:
    """Returns (tron_address, private_key_hex) for BIP44 path m/44'/195'/0'/0/index"""
    from bip_utils import (
        Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
    )
    seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
    bip44 = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON)
    child = bip44.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(index)
    address = child.PublicKey().ToAddress()
    priv_hex = child.PrivateKey().Raw().ToHex()
    return address, priv_hex


def get_next_deposit_address(index: int) -> Optional[str]:
    if not settings.tron_mnemonic:
        logger.warning("TRON_MNEMONIC não configurado — endereço de depósito não gerado")
        return None
    try:
        address, _ = _derive_tron_address(settings.tron_mnemonic, index)
        return address
    except Exception as exc:
        logger.error("Erro ao derivar endereço Tron (index=%d): %s", index, exc)
        return None


def generate_deposit_qr_png(address: str) -> bytes:
    qr_data = f"tron:{address}"
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def get_trc20_incoming(address: str, limit: int = 50) -> list[dict]:
    url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20"
    params = {
        "only_to": "true",
        "contract_address": USDT_CONTRACT_MAINNET,
        "limit": limit,
    }
    headers = {}
    if settings.trongrid_api_key:
        headers["TRON-PRO-API-KEY"] = settings.trongrid_api_key

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                return resp.json().get("data", [])
            logger.error("TronGrid erro %s para %s", resp.status_code, address)
    except Exception as exc:
        logger.error("TronGrid exception para %s: %s", address, exc)
    return []


def parse_trc20_amount(raw_value: str) -> float:
    try:
        return int(raw_value) / (10 ** USDT_DECIMALS)
    except Exception:
        return 0.0
