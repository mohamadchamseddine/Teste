from typing import Optional, Any
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

import models


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def get_machine_name(request: Request) -> str:
    host = request.headers.get("Host", "unknown")
    ua = request.headers.get("User-Agent", "unknown")
    return f"{host} | {ua[:150]}"


async def log(
    db: AsyncSession,
    action: str,
    username: str,
    request: Optional[Request] = None,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    old_value: Optional[Any] = None,
    new_value: Optional[Any] = None,
) -> None:
    ip = get_client_ip(request) if request else "system"
    machine = get_machine_name(request) if request else "system"

    entry = models.AuditLog(
        user_id=user_id,
        username=username,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip,
        machine_name=machine,
    )
    db.add(entry)
    await db.flush()
