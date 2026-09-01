import hashlib
import hmac
from typing import Any, cast

import pytest

import app.core.totp as totp_module

hash_backup_code = cast(Any, vars(totp_module)["hash_backup_code"])


def test_backup_code_hash_requires_independent_pepper() -> None:
    code = "ABCD-EFGH"
    first_pepper = "pepper-a-with-at-least-thirty-two-bytes"
    second_pepper = "pepper-b-with-at-least-thirty-two-bytes"
    first = hash_backup_code(code, pepper=first_pepper)
    second = hash_backup_code(code, pepper=second_pepper)
    plain = hashlib.sha256(code.encode("utf-8")).hexdigest()
    expected = hmac.new(
        first_pepper.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert first == expected
    assert second != first
    assert first != plain


def test_backup_code_hash_rejects_missing_or_short_pepper() -> None:
    with pytest.raises(ValueError):
        hash_backup_code("ABCD-EFGH", pepper="")
    with pytest.raises(ValueError):
        hash_backup_code("ABCD-EFGH", pepper="short")
