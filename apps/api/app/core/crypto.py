from cryptography.fernet import Fernet, InvalidToken

from app.core.settings import get_settings


class SecretBoxError(Exception):
    pass


def _box() -> Fernet:
    key = get_settings().totp_encryption_key
    if not key:
        raise SecretBoxError("totp encryption key is not configured")
    return Fernet(key.encode("utf-8"))


def encrypt_secret(plaintext: str) -> str:
    return _box().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(sealed: str) -> str:
    try:
        return _box().decrypt(sealed.encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise SecretBoxError("secret payload is invalid or was tampered with") from error
