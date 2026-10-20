from fastapi import APIRouter, Depends, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.errors import AppError
from src.api.schemas import UserCreate, UserRead
from src.auth.dependencies import get_current_user
from src.auth.security import create_access_token, hash_password, verify_password
from src.config import AUTH_COOKIE_NAME, COOKIE_SECURE, JWT_EXPIRE_MINUTES, REGISTRATION_ENABLED
from src.db.models import User
from src.db.session import get_db
from src.repositories import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=JWT_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=UserRead, status_code=201)
async def register(payload: UserCreate, response: Response, db: AsyncSession = Depends(get_db)):
    if not REGISTRATION_ENABLED:
        raise AppError(403, "REGISTRATION_CLOSED", "当前仅向受邀创作者开放，请联系管理员开通账号。")
    repo = UserRepository(db)
    if await repo.get_by_email(str(payload.email)):
        raise AppError(409, "EMAIL_EXISTS", "该邮箱已注册，请直接登录。")
    try:
        user = await repo.create(str(payload.email), hash_password(payload.password))
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(409, "EMAIL_EXISTS", "该邮箱已注册，请直接登录。") from exc
    set_auth_cookie(response, create_access_token(user.id))
    return user


@router.post("/login", response_model=UserRead)
async def login(payload: UserCreate, response: Response, db: AsyncSession = Depends(get_db)):
    user = await UserRepository(db).get_by_email(str(payload.email))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise AppError(401, "INVALID_CREDENTIALS", "邮箱或密码不正确。")
    if not user.is_active:
        raise AppError(403, "FORBIDDEN", "该账号已停用。")
    set_auth_cookie(response, create_access_token(user.id))
    return user


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", secure=COOKIE_SECURE, samesite="lax")


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)):
    return user
