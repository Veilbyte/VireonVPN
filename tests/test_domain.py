import pytest

from vireon.domain import DomainError, PlanCode, calculate_price_kopecks, referral_month_bonus


def test_monthly_prices_match_product_definition() -> None:
    assert calculate_price_kopecks(PlanCode.MINI, 30) == 5900
    assert calculate_price_kopecks(PlanCode.STANDARD, 30) == 8900
    assert calculate_price_kopecks(PlanCode.MAX, 30) == 12500


def test_custom_duration_is_linear_and_minimum_three_days() -> None:
    assert calculate_price_kopecks(PlanCode.STANDARD, 3) == 890
    with pytest.raises(DomainError):
        calculate_price_kopecks(PlanCode.STANDARD, 2)


def test_referral_bonus_is_credited_for_full_paid_months() -> None:
    assert referral_month_bonus(29) == 0
    assert referral_month_bonus(30) == 1
    assert referral_month_bonus(180) == 6
    assert referral_month_bonus(365) == 12
