from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database import get_db
import models

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_pin(pin: str) -> str:
    return pwd_context.hash(pin)


def verify_pin(plain_pin: str, hashed_pin: Optional[str]) -> bool:
    if not hashed_pin:
        return False
    return pwd_context.verify(plain_pin, hashed_pin)


def create_token(subject: str, expires_hours: Optional[int] = None) -> str:
    hours = expires_hours or settings.access_token_expire_hours
    expire = datetime.now(timezone.utc) + timedelta(hours=hours)
    return jwt.encode({"sub": subject, "exp": expire}, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def get_token_from_request(request: Request, bearer: Optional[str] = None) -> Optional[str]:
    if bearer:
        return bearer
    return request.cookies.get("access_token")


async def get_current_user(
    request: Request,
    bearer: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> models.User:
    token = get_token_from_request(request, bearer)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")

    subject = decode_token(token)
    if not subject or not subject.startswith("op:"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    user_id = int(subject.split(":")[1])
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário inativo")
    return user


async def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != models.UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a administradores")
    return user


async def get_current_client(
    request: Request,
    bearer: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> models.Client:
    token = request.cookies.get("client_token") or bearer
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")

    subject = decode_token(token)
    if not subject or not subject.startswith("client:"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    client_id = int(subject.split(":")[1])
    result = await db.execute(select(models.Client).where(models.Client.id == client_id))
    client = result.scalar_one_or_none()

    if not client or not client.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cliente inativo")
    return client
