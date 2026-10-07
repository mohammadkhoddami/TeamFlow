"""MFA routes: login challenge verification + enrollment management."""

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import DB, CurrentUser, RedisDep
from app.core.rate_limit import ip_rate_limiter
from app.schemas.auth import Token
from app.schemas.mfa import MfaEnable, MfaSetup, MfaStatus, MfaVerify
from app.services import audit, auth, mfa

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post(
    "/verify",
    response_model=Token,
    summary="Complete an MFA login challenge and issue tokens",
)
async def verify_mfa(
    data: MfaVerify,
    request: Request,
    db: DB,
    redis_client: RedisDep,
    _rl: None = Depends(ip_rate_limiter("mfa_verify", 10, 60)),
) -> Token:
    return await auth.complete_mfa_login(
        db, redis_client, data.mfa_token, data.code, ip=_ip(request)
    )


@router.get("", response_model=MfaStatus, summary="MFA status for the current user")
async def mfa_status(current_user: CurrentUser, db: DB) -> MfaStatus:
    return MfaStatus(enabled=await mfa.enabled(db, current_user.id))


@router.post("/setup", response_model=MfaSetup, summary="Start TOTP enrollment")
async def mfa_setup(current_user: CurrentUser, db: DB) -> MfaSetup:
    secret, uri, plain_codes = await mfa.setup_mfa(db, current_user)
    await db.commit()
    return MfaSetup(secret=secret, otpauth_uri=uri, recovery_codes=plain_codes)


@router.post("/enable", response_model=MfaStatus, summary="Confirm TOTP enrollment")
async def mfa_enable(
    data: MfaEnable, request: Request, current_user: CurrentUser, db: DB
) -> MfaStatus:
    await mfa.enable_mfa(db, current_user, data.code)
    await audit.log(
        db, "user.mfa_enabled", actor_id=current_user.id, ip=_ip(request)
    )
    await db.commit()
    return MfaStatus(enabled=True)


@router.post(
    "/disable",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable MFA (TOTP or recovery code required)",
)
async def mfa_disable(
    data: MfaEnable, request: Request, current_user: CurrentUser, db: DB
) -> None:
    await mfa.disable_mfa(db, current_user, data.code)
    await audit.log(
        db, "user.mfa_disabled", actor_id=current_user.id, ip=_ip(request)
    )
    await db.commit()
