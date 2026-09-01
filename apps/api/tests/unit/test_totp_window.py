from uuid import uuid4

import pyotp

from app.core.settings import get_settings
from app.core.totp import verify_totp


def seed_and_now() -> tuple[str, float]:
    return pyotp.random_base32(), 1_800_000_000.0


USER_ID = uuid4()


def test_verify_accepts_future_step_within_symmetric_window() -> None:
    seed, now = seed_and_now()
    period = get_settings().totp_period
    current_step = int(now // period)
    totp = pyotp.TOTP(seed, interval=period)
    future_code = totp.at((current_step + 1) * period)
    accepted, step = verify_totp(seed, future_code, last_step=None, now=now)
    assert accepted is True
    assert step == current_step + 1


def test_future_acceptance_blocks_earlier_steps() -> None:
    seed, now = seed_and_now()
    period = get_settings().totp_period
    current_step = int(now // period)
    totp = pyotp.TOTP(seed, interval=period)
    future_code = totp.at((current_step + 1) * period)
    accepted, step = verify_totp(seed, future_code, last_step=None, now=now)
    assert accepted is True
    replay_of_current = totp.at(current_step * period)
    blocked, _ = verify_totp(seed, replay_of_current, last_step=step, now=now)
    assert blocked is False
    replay_of_previous = totp.at((current_step - 1) * period)
    blocked_previous, _ = verify_totp(seed, replay_of_previous, last_step=step, now=now)
    assert blocked_previous is False


def test_verify_rejects_future_step_beyond_window() -> None:
    seed, now = seed_and_now()
    period = get_settings().totp_period
    current_step = int(now // period)
    totp = pyotp.TOTP(seed, interval=period)
    distant_code = totp.at((current_step + 2) * period)
    accepted, step = verify_totp(seed, distant_code, last_step=None, now=now)
    assert accepted is False
    assert step is None


def test_search_order_is_deterministic() -> None:
    seed, now = seed_and_now()
    period = get_settings().totp_period
    totp = pyotp.TOTP(seed, interval=period)
    codes_by_step: dict[int, str] = {}
    for offset in (-1, 0, 1):
        step = int(now // period) + offset
        codes_by_step[step] = totp.at(step * period)
    for step, code in codes_by_step.items():
        accepted, reported = verify_totp(seed, code, last_step=None, now=now)
        assert accepted is True
        assert reported == step
