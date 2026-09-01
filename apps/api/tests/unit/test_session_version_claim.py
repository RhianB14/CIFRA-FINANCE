from uuid import uuid4

import pytest

from app.core.settings import get_settings
from app.core.tokens import (
    TokenValidationError,
    create_access_token,
    decode_access_token,
)
from tests.unit.test_tokens import encode_custom

USER_ID = uuid4()


def signed_access_without_sv() -> str:
    import jwt as pyjwt

    return pyjwt.encode(
        {
            "sub": str(USER_ID),
            "typ": "access",
            "jti": "x",
            "iss": get_settings().jwt_issuer,
            "aud": get_settings().jwt_audience,
            "iat": 0,
            "exp": 10**10,
        },
        get_settings().jwt_signing_key,
        algorithm="HS256",
    )


def test_access_token_carries_session_version() -> None:
    payload = decode_access_token(create_access_token(USER_ID, session_version=7))
    assert payload["sv"] == 7


def test_decode_rejects_access_without_sv() -> None:
    with pytest.raises(TokenValidationError):
        decode_access_token(signed_access_without_sv())


def test_decode_rejects_sv_as_string() -> None:
    signed = encode_custom({"sub": str(USER_ID), "typ": "access", "jti": "x", "sv": "3"})
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_rejects_sv_as_bool() -> None:
    signed = encode_custom({"sub": str(USER_ID), "typ": "access", "jti": "x", "sv": True})
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_rejects_sv_zero() -> None:
    signed = encode_custom({"sub": str(USER_ID), "typ": "access", "jti": "x", "sv": 0})
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_rejects_sv_negative() -> None:
    signed = encode_custom({"sub": str(USER_ID), "typ": "access", "jti": "x", "sv": -2})
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_rejects_sv_float() -> None:
    signed = encode_custom({"sub": str(USER_ID), "typ": "access", "jti": "x", "sv": 3.5})
    with pytest.raises(TokenValidationError):
        decode_access_token(signed)


def test_decode_accepts_sv_one() -> None:
    signed = encode_custom({"sub": str(USER_ID), "typ": "access", "jti": "x", "sv": 1})
    payload = decode_access_token(signed)
    assert payload["sv"] == 1
