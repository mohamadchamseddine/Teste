from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import hash_password, verify_password, create_token, get_current_user
from schemas import LoginRequest, TokenResponse, UserOut
import models
import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(models.User).where(models.User.username == data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        await audit.log(
            db, action="login_failed", username=data.username,
            request=request, entity_type="session",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário inativo")

    token = create_token(f"op:{user.id}")

    await audit.log(
        db, action="login", username=user.username,
        request=request, user_id=user.id, entity_type="session",
    )
    await db.commit()

    response.set_cookie("access_token", token, httponly=True, samesite="lax")
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await audit.log(
        db, action="logout", username=current_user.username,
        request=request, user_id=current_user.id, entity_type="session",
    )
    await db.commit()
    response.delete_cookie("access_token")
    return {"detail": "Logout realizado"}


@router.get("/me", response_model=UserOut)
async def me(current_user: models.User = Depends(get_current_user)):
    return current_user
