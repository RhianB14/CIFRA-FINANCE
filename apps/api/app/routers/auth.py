import json
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user, get_session, set_bypass_scope
from app.core.emails import normalize_email
from app.core.hibp import HIBPUnavailableError
from app.core.ratelimit import RateLimitExceeded, check_rate_limit, client_ip
from app.core.settings import get_settings
from app.core.tokens import (
    TokenValidationError,
    create_access_token,
    decode_access_token,
    decode_refresh_token,
)
from app.core.totp import qr_data_uri
from app.models import User
from app.schemas.auth import (
    ChallengeRequest,
    ConfirmTwoFactorRequest,
    DisableTwoFactorRequest,
    MeResponse,
    PasswordRecoveryRequest,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    SetupTwoFactorResponse,
    TokenPair,
    TwoFactorChallengeResponse,
    VerifyTwoFactorResponse,
)
from app.services import lockout
from app.services.audit import AuditEventType, record_audit_event
from app.services.auth import (
    AuthenticationError,
    EmailAlreadyRegisteredError,
    authenticate_user,
    get_user_by_email,
    register_user,
    start_session,
)
from app.services.mailer import Mailer, MailerError, get_mailer
from app.services.password_reset import (
    ResetStoreUnavailableError,
    ResetTokenInvalidError,
    issue_reset_token,
)
from app.services.password_reset import (
    reset_password as reset_password_service,
)
from app.services.rotation import (
    ReuseDetectedError,
    TokenExpiredError,
    TokenNotFoundError,
    revoke_session,
    rotate_refresh_token,
)
from app.services.session_revocation import (
    SessionStoreUnavailableError,
    session_invalid,
)
from app.services.two_factor import (
    TwoFactorAlreadyEnabledError,
    TwoFactorError,
    TwoFactorNotEnabledError,
    confirm_totp,
    disable_totp,
    setup_totp,
    verify_second_factor,
)

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2 = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

REGISTER_RATE_LIMIT = 3
LOGIN_RATE_LIMIT = 5
PASSWORD_RECOVERY_RATE_LIMIT = 3
RATE_LIMIT_WINDOW_SECONDS = 60
RECOVERY_WINDOW_SECONDS = 3600


def _credentials_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _rate_limit_error(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="too many requests",
        headers={"Retry-After": str(max(1, retry_after))},
    )


async def _enforce_rate_limit(
    request: Request,
    bucket: str,
    limit: int,
    window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
) -> None:
    settings = get_settings()
    peer = request.client.host if request.client is not None else None
    forwarded = request.headers.get("x-forwarded-for")
    identity = client_ip(peer, forwarded, settings)
    store = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await check_rate_limit(
            store,
            f"cifra:ratelimit:{bucket}:{identity}",
            limit,
            window_seconds,
        )
    except RateLimitExceeded as error:
        raise _rate_limit_error(error.retry_after) from None
    finally:
        await store.aclose()


def reset_store() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)


async def get_current_user(
    signed: Annotated[str | None, Depends(oauth2)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if signed is None:
        raise _credentials_error("missing bearer token")
    try:
        payload = decode_access_token(signed)
    except TokenValidationError:
        raise _credentials_error("invalid access token") from None
    user_id = uuid.UUID(str(payload["sub"]))
    session_version_value = payload["sv"]
    if isinstance(session_version_value, bool) or not isinstance(session_version_value, int):
        raise _credentials_error("invalid access token")
    session_version = session_version_value
    try:
        if await session_invalid(session, user_id, session_version):
            raise _credentials_error("session has been revoked")
    except SessionStoreUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="session dependency unavailable",
        ) from None
    user = await session.get(User, user_id)
    if user is None:
        raise _credentials_error("unknown user")
    if not user.is_active:
        raise _credentials_error("account is inactive")
    await bind_current_user(session, user_id)
    return user


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    http_request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    await _enforce_rate_limit(http_request, "register", REGISTER_RATE_LIMIT)
    await set_bypass_scope(session)
    try:
        _, access, refresh = await register_user(
            session, request.email, request.password, request.name
        )
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email is already registered"
        ) from None
    except HIBPUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="password breach service unavailable",
        ) from None
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="password does not meet security requirements",
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/login")
async def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair | TwoFactorChallengeResponse:
    await _enforce_rate_limit(request, "login", LOGIN_RATE_LIMIT)
    await set_bypass_scope(session)
    peer = request.client.host if request.client is not None else None
    identity = normalize_email(form.username)
    if await lockout.is_locked(identity):
        raise _credentials_error("invalid credentials") from None
    try:
        user = await authenticate_user(session, form.username, form.password)
    except AuthenticationError:
        failures = await lockout.register_failure(identity)
        locked_now = failures is not None and failures >= lockout.MAX_FAILURES
        if locked_now:
            await lockout.apply_lock(identity)
        await record_audit_event(
            session,
            event_type=AuditEventType.LOGIN_FAILED,
            actor_ip=peer,
            after={"outcome": "invalid_credentials", "account_locked": locked_now},
        )
        await session.commit()
        raise _credentials_error("invalid credentials") from None
    await lockout.reset_failures(identity)
    if user.totp_enabled:
        try:
            challenge_id = await _create_challenge(session, user)
        except SessionStoreUnavailableError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="session store unavailable",
            ) from None
        return TwoFactorChallengeResponse(challenge_id=challenge_id)
    access, refresh = await start_session(session, user)
    await record_audit_event(
        session,
        event_type=AuditEventType.LOGIN_SUCCEEDED,
        user_id=user.id,
        actor_ip=peer,
    )
    await session.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


CHALLENGE_KEY_PREFIX = "cifra:2fa-challenge:"
CHALLENGE_PURPOSE = "login-2fa"
CHALLENGE_ENTROPY_BYTES = 32


def _challenge_key(challenge_id: str) -> str:
    return CHALLENGE_KEY_PREFIX + challenge_id


class ChallengePayloadError(Exception):
    pass


@dataclass(frozen=True)
class ChallengeData:
    user_id: uuid.UUID
    session_version: int


async def _create_challenge(session: AsyncSession, user: User) -> str:
    ttl = get_settings().two_factor_challenge_ttl_seconds
    challenge_id = secrets.token_hex(CHALLENGE_ENTROPY_BYTES)
    payload = json.dumps(
        {
            "user_id": str(user.id),
            "session_version": user.session_version,
            "purpose": CHALLENGE_PURPOSE,
        },
        sort_keys=True,
    )
    store = redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await store.set(_challenge_key(challenge_id), payload, ex=ttl)
    except (RedisError, OSError) as error:
        raise SessionStoreUnavailableError("session dependency unavailable") from error
    finally:
        await store.aclose()
    return challenge_id


async def _consume_challenge(challenge_id: str) -> ChallengeData:
    store = redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        stored = await store.getdel(_challenge_key(challenge_id))
    except (RedisError, OSError) as error:
        raise SessionStoreUnavailableError("session dependency unavailable") from error
    finally:
        await store.aclose()
    if stored is None:
        raise _credentials_error("invalid or expired challenge")
    try:
        payload = json.loads(stored)
        data = ChallengeData(
            user_id=uuid.UUID(str(payload["user_id"])),
            session_version=int(payload["session_version"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ChallengePayloadError("challenge payload is invalid") from error
    return data


@router.post("/2fa/challenge")
async def two_factor_challenge(
    request: ChallengeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    await set_bypass_scope(session)
    try:
        data = await _consume_challenge(request.challenge_id)
    except SessionStoreUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="session dependency unavailable",
        ) from None
    except ChallengePayloadError:
        raise _credentials_error("invalid or expired challenge") from None
    user = await session.get(User, data.user_id)
    if user is None or not user.totp_enabled or not user.is_active:
        raise _credentials_error("invalid or expired challenge")
    if user.session_version != data.session_version:
        raise _credentials_error("invalid or expired challenge")
    try:
        await verify_second_factor(session, user, request.code, commit=False)
    except TwoFactorError:
        await record_audit_event(
            session,
            event_type=AuditEventType.TWO_FACTOR_CHALLENGE_FAILED,
            user_id=user.id,
            after={"outcome": "invalid_second_factor"},
        )
        await session.commit()
        raise _credentials_error("invalid second factor code") from None
    access, refresh = await start_session(session, user)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh")
async def refresh(
    request: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    await set_bypass_scope(session)
    try:
        new_refresh_jwt, _ = await rotate_refresh_token(session, request.refresh_token)
    except SessionStoreUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="session dependency unavailable",
        ) from None
    except (ReuseDetectedError, TokenNotFoundError, TokenExpiredError, TokenValidationError):
        raise _credentials_error("refresh token is invalid, expired or reused") from None
    payload = decode_refresh_token(new_refresh_jwt)
    user = await session.get(User, uuid.UUID(str(payload["sub"])))
    if user is None:
        raise _credentials_error("refresh token is invalid, expired or reused")
    access = create_access_token(user.id, session_version=user.session_version)
    return TokenPair(access_token=access, refresh_token=new_refresh_jwt)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await set_bypass_scope(session)
    try:
        revoked = await revoke_session(session, request.refresh_token)
    except (TokenNotFoundError, TokenValidationError):
        raise _credentials_error("refresh token is invalid") from None
    if revoked is not None:
        await record_audit_event(
            session,
            event_type=AuditEventType.LOGOUT_PERFORMED,
            user_id=revoked.user_id,
        )
        await session.commit()


@router.post("/password-recovery", status_code=status.HTTP_200_OK)
async def password_recovery(
    request: PasswordRecoveryRequest,
    http_request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> dict[str, str]:
    await _enforce_rate_limit(
        http_request,
        "recovery",
        PASSWORD_RECOVERY_RATE_LIMIT,
        RECOVERY_WINDOW_SECONDS,
    )
    await set_bypass_scope(session)
    peer = http_request.client.host if http_request.client is not None else None
    try:
        user = await get_user_by_email(session, request.email)
        if user is not None and user.is_active:
            token = await issue_reset_token(reset_store(), user.id)
            try:
                await mailer.send_password_reset(user.email, token)
            except MailerError:
                await record_audit_event(
                    session,
                    event_type=AuditEventType.PASSWORD_RESET_REQUESTED,
                    user_id=user.id,
                    actor_ip=peer,
                    after={"outcome": "delivery_failed"},
                )
                await session.commit()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="password reset delivery is unavailable",
                ) from None
            await record_audit_event(
                session,
                event_type=AuditEventType.PASSWORD_RESET_REQUESTED,
                user_id=user.id,
                actor_ip=peer,
                after={"outcome": "token_issued"},
            )
            await session.commit()
        else:
            await record_audit_event(
                session,
                event_type=AuditEventType.PASSWORD_RESET_REQUESTED,
                user_id=None,
                actor_ip=peer,
                after={"outcome": "no_such_user"},
            )
            await session.commit()
    except ResetStoreUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="password reset store unavailable",
        ) from None
    return {"status": "if the account exists, a reset link was sent"}


@router.post("/password-reset", status_code=status.HTTP_200_OK)
async def password_reset(
    request: PasswordResetRequest,
    http_request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    await set_bypass_scope(session)
    try:
        await reset_password_service(session, reset_store(), request.token, request.new_password)
    except ResetTokenInvalidError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reset token is invalid or expired",
        ) from None
    except ResetStoreUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="password reset store unavailable",
        ) from None
    return {"status": "password updated"}


@router.get("/me")
async def me(user: Annotated[User, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        totp_enabled=user.totp_enabled,
    )


@router.post("/2fa/setup")
async def setup_two_factor(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupTwoFactorResponse:
    try:
        uri = await setup_totp(session, user)
    except TwoFactorAlreadyEnabledError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="two factor is already enabled"
        ) from None
    return SetupTwoFactorResponse(otpauth_uri=uri, qr_data_uri=qr_data_uri(uri))


@router.post("/2fa/verify")
async def verify_two_factor(
    request: ConfirmTwoFactorRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VerifyTwoFactorResponse:
    try:
        codes = await confirm_totp(session, user, request.code)
    except TwoFactorAlreadyEnabledError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="two factor is already enabled"
        ) from None
    except TwoFactorError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid confirmation code"
        ) from None
    access, refresh = await start_session(session, user)
    return VerifyTwoFactorResponse(
        access_token=access,
        refresh_token=refresh,
        backup_codes=codes,
    )


@router.post("/2fa/disable", status_code=status.HTTP_200_OK)
async def disable_two_factor(
    request: DisableTwoFactorRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    try:
        await disable_totp(session, user, request.password, request.code)
        await session.commit()
    except TwoFactorNotEnabledError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="two factor is not enabled"
        ) from None
    except TwoFactorError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid code"
        ) from None
    return {"status": "disabled"}
