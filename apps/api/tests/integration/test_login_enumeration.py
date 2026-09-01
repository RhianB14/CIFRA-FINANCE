import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.passwords import verify_password
from app.services.auth import AuthenticationError, authenticate_user, register_user

PASSWORD = "Tr0ub4dor&3-Correct-Horse"


@pytest.mark.asyncio
async def test_unknown_user_and_wrong_password_both_verify_argon2(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"timing-{uuid.uuid4().hex}@example.com"
    await register_user(db_session, email, PASSWORD, "Ana", hibp_enabled=False)
    calls: list[str] = []

    def counted(encoded: str, phrase: str) -> bool:
        calls.append(encoded)
        return verify_password(encoded, phrase)

    monkeypatch.setattr("app.services.auth.verify_password", counted)
    with pytest.raises(AuthenticationError, match="invalid credentials"):
        await authenticate_user(db_session, email, "Wrong-Password-123")
    known_count = len(calls)
    with pytest.raises(AuthenticationError, match="invalid credentials"):
        await authenticate_user(
            db_session,
            f"missing-{uuid.uuid4().hex}@example.com",
            "Wrong-Password-123",
        )
    unknown_count = len(calls) - known_count
    assert known_count == 1
    assert unknown_count == 1


@pytest.mark.asyncio
async def test_duplicate_registration_race_returns_domain_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.auth import EmailAlreadyRegisteredError

    email = f"race-{uuid.uuid4().hex}@example.com"
    await register_user(db_session, email, PASSWORD, "Ana", hibp_enabled=False)

    async def absent(session: AsyncSession, value: str) -> None:
        return None

    monkeypatch.setattr("app.services.auth.get_user_by_email", absent)
    with pytest.raises(EmailAlreadyRegisteredError):
        await register_user(db_session, email, PASSWORD, "Ana", hibp_enabled=False)
