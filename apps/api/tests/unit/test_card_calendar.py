from datetime import date

import pytest

from app.services.cards import (
    build_installment_plan,
    invoice_due_date,
    invoice_period_for_purchase,
    occurred_at_for_period,
)


def test_purchase_before_closing_day_belongs_to_current_invoice() -> None:
    assert invoice_period_for_purchase(date(2026, 4, 24), 25) == (2026, 4)


def test_purchase_after_closing_day_belongs_to_next_invoice() -> None:
    assert invoice_period_for_purchase(date(2026, 4, 30), 25) == (2026, 5)


def test_purchase_on_closing_day_belongs_to_current_invoice() -> None:
    assert invoice_period_for_purchase(date(2026, 4, 25), 25) == (2026, 4)


def test_leap_year_installments_preserve_day_with_month_clamping() -> None:
    plan = build_installment_plan(date(2024, 2, 29), 25, 10000, 3)
    dates = [
        occurred_at_for_period(year, month, date(2024, 2, 29)).date()
        for year, month in plan.periods
    ]
    assert dates == [date(2024, 3, 29), date(2024, 4, 29), date(2024, 5, 29)]


def test_installment_residual_cents_are_distributed_to_earliest_installments() -> None:
    plan = build_installment_plan(date(2026, 1, 10), 25, 10001, 3)
    assert plan.amounts == [3334, 3334, 3333]
    assert sum(plan.amounts) == 10001
    assert len(plan.periods) == 3


def test_nonexistent_day_is_clamped_to_last_day_of_month() -> None:
    assert occurred_at_for_period(2025, 2, date(2025, 1, 31)).date() == date(2025, 2, 28)


def test_due_date_is_clamped_for_short_month() -> None:
    assert invoice_due_date(2025, 1, 31) == date(2025, 2, 28)


@pytest.mark.parametrize("installments", [0, 49])
def test_invalid_installment_count_is_rejected(installments: int) -> None:
    with pytest.raises(ValueError):
        build_installment_plan(date(2026, 1, 10), 25, 10000, installments)


def test_installment_amount_smaller_than_count_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_installment_plan(date(2026, 1, 10), 25, 2, 3)
