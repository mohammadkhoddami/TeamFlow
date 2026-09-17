"""Auth routes: thin HTTP adapters over services."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import DB, CurrentUser, RedisDep
from app.core.config import settings
from app.core.rate_limit import ip_rate_limiter
from app.schemas import (
    PasswordForgot,
    PasswordReset,
    RefreshedToken,
    Token,
    TokenRefresh,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


def _ip(request: Request) -> str:
    return request.client.host if request.client else None


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRead,
    summary="Create a new user account",
)
async def register(
    data: UserCreate,
    request: Request,
    db: DB,
    _rl: None = Depends(ip_rate_limiter("register", settings.register_rate_limit_max, settings.register_rate_limit_window)),
) -> UserRead:
    user = await auth.register_user(db, data, ip=_ip(request))
    return UserRead.model_validate(user)


# OAuth2PasswordRequestForm == x-www-form-urlencoded with "username"/"password".
# That is what the Swagger "Authorize" button submits, which is why login is
# form-encoded instead of JSON.
@router.post("/login", response_model=Token, summary="Login (OAuth2 password flow)")
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    db: DB,
    redis_client: RedisDep,
    _rl: None = Depends(ip_rate_limiter("auth_ip")),
) -> Token:
    return await auth.login(db, redis_client, form.username, form.password, ip=_ip(request))


@router.post("/refresh", response_model=RefreshedToken, summary="Rotate tokens")
async def refresh(data: TokenRefresh, db: DB, redis_client: RedisDep) -> RefreshedToken:
    return await auth.refresh_tokens(db, redis_client, data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout (revoke refresh token)")
async def logout(data: TokenRefresh, redis_client: RedisDep) -> None:
    await auth.logout(redis_client, data.refresh_token)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke all sessions")
async def logout_all(current_user: CurrentUser, redis_client: RedisDep) -> None:
    await auth.logout_all(redis_client, current_user)


@router.get("/me", response_model=UserRead, summary="Current user profile")
async def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@router.patch("/me", response_model=UserRead, summary="Update current user profile")
async def update_me(data: UserUpdate, current_user: CurrentUser, db: DB) -> UserRead:
    user = await auth.update_user(db, current_user.id, data)
    return UserRead.model_validate(user)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset email",
)
async def forgot_password(
    data: PasswordForgot,
    request: Request,
    db: DB,
    redis_client: RedisDep,
    _rl: None = Depends(
        ip_rate_limiter("password_reset", settings.password_reset_rate_limit_max, settings.password_reset_rate_limit_window)
    ),
) -> dict[str, str]:
    # Always the same response: no user enumeration via timing or status.
    await auth.request_password_reset(db, redis_client, data, ip=_ip(request))
    return {"detail": "If the account exists, a reset link has been sent"}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    data: PasswordReset,
    request: Request,
    db: DB,
    redis_client: RedisDep,
    _rl: None = Depends(
        ip_rate_limiter("password_reset", settings.password_reset_rate_limit_max, settings.password_reset_rate_limit_window)
    ),
) -> None:
    await auth.reset_password(db, redis_client, data, ip=_ip(request))
