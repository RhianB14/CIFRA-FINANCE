from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt as pyjwt

from app.core.settings import get_settings

JWT_ALGORITHM = "HS256"


class TokenValidationError(Exception):
    pass


def _encode(payload: dict[str, object]) -> str:
    return pyjwt.encode(payload, get_settings().jwt_signing_key, algorithm=JWT_ALGORITHM)


def _decode(token: str, expected_type: str) -> dict[str, object]:
    settings = get_settings()
    try:
        payload = pyjwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=[JWT_ALGORITHM],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "jti", "typ", "iss", "aud"]},
        )
    except pyjwt.PyJWTError as error:
        raise TokenValidationError(str(error)) from error
    if payload.get("typ") != expected_type:
        raise TokenValidationError("unexpected token type")
    try:
        UUID(str(payload.get("sub")))
    except ValueError as error:
        raise TokenValidationError("invalid subject") from error
    return dict(payload)


def create_access_token(
    user_id: UUID,
    now: datetime | None = None,
    session_version: int = 1,
) -> str:
    settings = get_settings()
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.access_token_ttl_minutes)
    return _encode(
        {
            "sub": str(user_id),
            "typ": "access",
            "jti": uuid4().hex,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "sv": session_version,
        }
    )


def create_refresh_token(
    user_id: UUID,
    family_id: UUID,
    now: datetime | None = None,
) -> str:
    settings = get_settings()
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(days=settings.refresh_token_ttl_days)
    return _encode(
        {
            "sub": str(user_id),
            "typ": "refresh",
            "jti": uuid4().hex,
            "fam": str(family_id),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
    )


def decode_access_token(token: str) -> dict[str, object]:
    return _decode(token, "access")


def decode_refresh_token(token: str) -> dict[str, object]:
    return _decode(token, "refresh")
