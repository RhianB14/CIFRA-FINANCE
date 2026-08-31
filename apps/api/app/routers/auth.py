import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.settings import get_settings
from app.core.tokens import (
    TokenValidationError,
    create_access_token,
    decode_access_token,
    decode_refresh_token,
)
from app.models import User
from app.schemas.auth import (
    ChallengeRequest,
    ConfirmTwoFactorRequest,
    DisableTwoFactorRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    SetupTwoFactorResponse,
    TokenPair,
    VerifyTwoFactorResponse,
)
from app.services.auth import (
    AuthenticationError,
    EmailAlreadyRegisteredError,
    authenticate_user,
    register_user,
)
from app.services.rotation import (
    ReuseDetectedError,
    TokenExpiredError,
    TokenNotFoundError,
    issue_refresh_token,
    revoke_session,
    rotate_refresh_token,
)
from app.services.session_revocation import session_invalid
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
bearer = HTTPBearer(auto_error=False)


def _credentials_error(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None:
        raise _credentials_error("missing bearer token")
    try:
        payload = decode_access_token(credentials.credentials)
    except TokenValidationError:
        raise _credentials_error("invalid access token") from None
    user_id = uuid.UUID(str(payload["sub"]))
    raw_version = payload.get("sv", 1)
    session_version = int(raw_version) if isinstance(raw_version, int) else 1
    if await session_invalid(user_id, session_version):
        raise _credentials_error("session has been revoked")
    user = await session.get(User, user_id)
    if user is None:
        raise _credentials_error("unknown user")
    return user


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    try:
        _, access, refresh = await register_user(
            session, request.email, request.password, request.name
        )
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email is already registered"
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/login")
async def login(
    request: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair | dict[str, object]:
    try:
        user = await authenticate_user(session, request.email, request.password)
    except AuthenticationError:
        raise _credentials_error("invalid credentials") from None
    if user.totp_enabled:
        challenge_id = await _create_challenge(session, user)
        return {"challenge_id": challenge_id, "two_factor_required": True}
    access = create_access_token(user.id)
    refresh, _ = await issue_refresh_token(session, user.id)
    return TokenPair(access_token=access, refresh_token=refresh)


def _challenge_key(challenge_id: str) -> str:
    return "cifra:2fa-challenge:" + challenge_id


async def _create_challenge(session: AsyncSession, user: User) -> str:
    import redis.asyncio as redis

    challenge_id = uuid.uuid4().hex
    ttl = get_settings().two_factor_challenge_ttl_seconds
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await client.set(_challenge_key(challenge_id), str(user.id), ex=ttl)
    finally:
        await client.aclose()
    return challenge_id


async def _consume_challenge(challenge_id: str) -> uuid.UUID:
    import redis.asyncio as redis

    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        stored = await client.getdel(_challenge_key(challenge_id))
    finally:
        await client.aclose()
    if stored is None:
        raise _credentials_error("invalid or expired challenge")
    return uuid.UUID(stored)


@router.post("/2fa/challenge")
async def two_factor_challenge(
    request: ChallengeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    user_id = await _consume_challenge(request.challenge_id)
    user = await session.get(User, user_id)
    if user is None or not user.totp_enabled:
        raise _credentials_error("invalid or expired challenge")
    try:
        await verify_second_factor(session, user, request.code)
    except TwoFactorError:
        raise _credentials_error("invalid second factor code") from None
    access = create_access_token(user.id)
    refresh, _ = await issue_refresh_token(session, user.id)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh")
async def refresh(
    request: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    try:
        new_refresh_jwt, _ = await rotate_refresh_token(session, request.refresh_token)
    except (ReuseDetectedError, TokenNotFoundError, TokenExpiredError, TokenValidationError):
        raise _credentials_error("refresh token is invalid, expired or reused") from None
    payload = decode_refresh_token(new_refresh_jwt)
    access = create_access_token(uuid.UUID(str(payload["sub"])))
    return TokenPair(access_token=access, refresh_token=new_refresh_jwt)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        await revoke_session(session, request.refresh_token)
    except (TokenNotFoundError, TokenValidationError):
        raise _credentials_error("refresh token is invalid") from None


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
    return SetupTwoFactorResponse(otpauth_uri=uri)


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
    access = create_access_token(user.id)
    refresh, _ = await issue_refresh_token(session, user.id)
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
        await disable_totp(session, user, request.code)
    except TwoFactorNotEnabledError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="two factor is not enabled"
        ) from None
    except TwoFactorError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid code"
        ) from None
    return {"status": "disabled"}
