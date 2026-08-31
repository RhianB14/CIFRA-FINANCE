import hashlib
import secrets
import time

import pyotp
import segno

TOTP_ISSUER = "CIFRA"
TOTP_PERIOD = 30
TOTP_DRIFT_WINDOWS = 1
BACKUP_CODE_COUNT = 10


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(email: str, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name=TOTP_ISSUER,
    )


def qr_data_uri(uri: str) -> str:
    return segno.make(uri).png_data_uri(scale=6, border=2)


def _now() -> float:
    return time.time()


def verify_totp(
    secret: str,
    code: str,
    last_step: int | None,
    now: float | None = None,
) -> tuple[bool, int | None]:
    normalized = code.strip().replace(" ", "")
    if not normalized.isdigit() or len(normalized) != 6:
        return False, None
    totp = pyotp.TOTP(secret)
    current_step = int((now if now is not None else _now()) // TOTP_PERIOD)
    for offset in range(TOTP_DRIFT_WINDOWS, -1, -1):
        candidate_step = current_step - offset
        candidate = totp.at(candidate_step * TOTP_PERIOD)
        if normalized == candidate:
            if last_step is not None and candidate_step <= last_step:
                return False, None
            return True, candidate_step
    return False, None


def generate_backup_codes() -> list[str]:
    pool = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    codes: list[str] = []
    while len(codes) < BACKUP_CODE_COUNT:
        raw = "".join(secrets.choice(pool) for _ in range(8))
        code = "-".join((raw[:4], raw[4:]))
        if code not in codes:
            codes.append(code)
    return codes


def hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()
