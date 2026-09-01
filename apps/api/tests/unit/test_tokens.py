from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt as pyjwt
import pytest

from app.core.settings import get_settings
from app.core.tokens import (
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)

USER_ID = uuid4()
FAMILY_ID = uuid4()


def make_settings_key() -> str:
    return get_settings().jwt_signing_key


def encode_custom(payload: dict[str, object]) -> str:
    base: dict[str, object] = {
        "iss": get_settings().jwt_issuer,
        "aud": get_settings().jwt_audience,
        "iat": 0,
        "exp": 10**10,
    }
    base.update(payload)
    return pyjwt.encode(base, make_settings_key(), algorithm="HS256")


def test_access_token_contains_expected_claims() -> None:
    now = datetime.now(UTC)
    signed = create_access_token(USER_ID, now=now)
    payload = pyjwt.decode(
        signed,
        make_settings_key(),
        algorithms=["HS256"],
        issuer=get_settings().jwt_issuer,
        audience=get_settings().jwt_audience,
    )
    assert payload["sub"] == str(USER_ID)
    assert payload["typ"] == "access"
    assert payload["iss"] == get_settings().jwt_issuer
    assert payload["aud"] == get_settings().jwt_audience
    assert payload["jti"]
    assert payload["exp"] - payload["iat"] == get_settings().access_token_ttl_minutes * 60


def test_refresh_token_contains_expected_claims() -> None:
    now = datetime.now(UTC)
    signed = create_refresh_token(USER_ID, FAMILY_ID, now=now)
    payload = pyjwt.decode(
        signed,
        make_settings_key(),
        algorithms=["HS256"],
        issuer=get_settings().jwt_issuer,
        audience=get_settings().jwt_audience,
    )
    assert payload["sub"] == str(USER_ID)
    assert payload["typ"] == "refresh"
    assert payload["fam"] == str(FAMILY_ID)
    assert payload["jti"]
    assert payload["exp"] - payload["iat"] == get_settings().refresh_token_ttl_days * 86400


def test_decode_access_rejects_refresh_token() -> None:
    refresh = create_refresh_token(USER_ID, FAMILY_ID)
    with pytest.raises(TokenValidationError):
        decode_access_token(refresh)


def test_decode_refresh_rejects_access_token() -> None:
    access = create_access_token(USER_ID)
    with pytest.raises(TokenValidationError):
        decode_refresh_token(access)


def test_decode_rejects_tampered_signature() -> None:
    signed = create_access_token(USER_ID)
    with pytest.raises(TokenValidationError):
        decode_access_token(signed + "x")


def test_decode_rejects_wrong_issuer() -> None:
    signed = encode_custom({"sub": str(USER_ID), "typ": "access", "jti": "x", "iss": "other"})
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_rejects_wrong_audience() -> None:
    signed = encode_custom({"sub": str(USER_ID), "typ": "access", "jti": "x", "aud": "other"})
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_rejects_expired_token() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    signed = create_access_token(USER_ID, now=past)
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_rejects_future_nbf() -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    signed = encode_custom(
        {"sub": str(USER_ID), "typ": "access", "jti": "x", "nbf": int(future.timestamp())}
    )
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_rejects_missing_jti() -> None:
    signed = encode_custom({"sub": str(USER_ID), "typ": "access", "jti": None})
    del signed
    raw = pyjwt.encode(
        {
            "sub": str(USER_ID),
            "typ": "access",
            "iss": get_settings().jwt_issuer,
            "aud": get_settings().jwt_audience,
            "iat": 0,
            "exp": 10**10,
        },
        make_settings_key(),
        algorithm="HS256",
    )
    with pytest.raises(TokenValidationError):
        decode_access_token(raw)


def test_decode_rejects_alg_none() -> None:
    raw = pyjwt.encode(
        {
            "sub": str(USER_ID),
            "typ": "access",
            "jti": "x",
            "iss": get_settings().jwt_issuer,
            "aud": get_settings().jwt_audience,
            "iat": 0,
            "exp": 10**10,
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(TokenValidationError):
        decode_access_token(raw)


def test_decode_rejects_non_uuid_subject() -> None:
    signed = encode_custom({"sub": "not-a-uuid", "typ": "access", "jti": "x"})
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_refresh_returns_payload() -> None:
    signed = create_refresh_token(USER_ID, FAMILY_ID)
    payload = decode_refresh_token(signed)
    assert payload["sub"] == str(USER_ID)
    assert payload["fam"] == str(FAMILY_ID)
