import pyotp
import pytest

from app.core.crypto import SecretBoxError, decrypt_secret, encrypt_secret
from app.core.totp import (
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_code,
    provisioning_uri,
    verify_totp,
)

ISSUER = "CIFRA"


def test_generate_secret_is_base32_and_unique() -> None:
    first = generate_totp_secret()
    second = generate_totp_secret()
    assert first != second
    pyotp.TOTP(first).now()


def test_provisioning_uri_contains_params() -> None:
    seed = generate_totp_secret()
    uri = provisioning_uri("ana@example.com", seed)
    assert uri.startswith("otpauth://totp/")
    assert "ana%40example.com" in uri or "ana@example.com" in uri
    assert f"issuer={ISSUER}" in uri
    assert seed in uri


def test_verify_accepts_current_code() -> None:
    seed = generate_totp_secret()
    now = 1_800_000_000.0
    code = pyotp.TOTP(seed).at(int(now))
    accepted, step = verify_totp(seed, code, last_step=None, now=now)
    assert accepted is True
    assert step == int(now // 30)


def test_verify_rejects_garbage() -> None:
    seed = generate_totp_secret()
    accepted, step = verify_totp(seed, "not-a-code", last_step=None)
    assert accepted is False
    assert step is None


def test_verify_rejects_replay_of_same_step() -> None:
    seed = generate_totp_secret()
    now = 1_800_000_000.0
    code = pyotp.TOTP(seed).at(int(now))
    current_step = int(now // 30)
    accepted, _ = verify_totp(seed, code, last_step=current_step, now=now)
    assert accepted is False


def test_verify_rejects_code_two_windows_old() -> None:
    seed = generate_totp_secret()
    totp = pyotp.TOTP(seed)
    now = 1_800_000_000.0
    old_code = totp.at((int(now // 30) - 2) * 30)
    accepted, step = verify_totp(seed, old_code, last_step=None, now=now)
    assert accepted is False
    assert step is None


def test_verify_accepts_previous_window_and_reports_step() -> None:
    seed = generate_totp_secret()
    totp = pyotp.TOTP(seed)
    now = 1_800_000_000.0
    current_step = int(now // 30)
    previous_code = totp.at((current_step - 1) * 30)
    accepted, step = verify_totp(seed, previous_code, last_step=None, now=now)
    assert accepted is True
    assert step == current_step - 1


def test_encryption_roundtrip() -> None:
    seed = generate_totp_secret()
    sealed = encrypt_secret(seed)
    assert sealed != seed
    assert decrypt_secret(sealed) == seed


def test_encryption_is_nondeterministic() -> None:
    first = encrypt_secret("same-plaintext")
    second = encrypt_secret("same-plaintext")
    assert first != second


def test_decrypt_rejects_tampered_payload() -> None:
    sealed = encrypt_secret("plaintext")
    with pytest.raises(SecretBoxError):
        decrypt_secret(sealed[:-4] + "AAAA")


def test_backup_codes_format_and_count() -> None:
    codes = generate_backup_codes()
    assert len(codes) == 10
    assert len(set(codes)) == 10
    for code in codes:
        assert len(code) == 9
        assert code[4] == "-"


def test_backup_code_hash_is_sha256_hex() -> None:
    assert hash_backup_code("ABCD-EFGH") == hash_backup_code("ABCD-EFGH")
    digest = hash_backup_code("ABCD-EFGH")
    assert len(digest) == 64
    import hashlib

    assert digest == hashlib.sha256(b"ABCD-EFGH").hexdigest()
