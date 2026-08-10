from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import ceil


class PlanCode(StrEnum):
    MINI = "mini"
    STANDARD = "standard"
    MAX = "max"


@dataclass(frozen=True, slots=True)
class PlanDefinition:
    code: PlanCode
    title: str
    monthly_price_kopecks: int
    device_limit: int


PLANS: dict[PlanCode, PlanDefinition] = {
    PlanCode.MINI: PlanDefinition(PlanCode.MINI, "Мини", 5_900, 3),
    PlanCode.STANDARD: PlanDefinition(PlanCode.STANDARD, "Стандарт", 8_900, 5),
    PlanCode.MAX: PlanDefinition(PlanCode.MAX, "Макс", 12_500, 8),
}

PRESET_DAYS = (14, 30, 90, 180)
MIN_CUSTOM_DAYS = 3


class DomainError(ValueError):
    pass


def calculate_price_kopecks(plan: PlanCode, days: int) -> int:
    """Linear v0.1 pricing. Long-term discounts can be added without changing the bot flow."""
    if days < MIN_CUSTOM_DAYS:
        raise DomainError(f"Минимальный срок подписки — {MIN_CUSTOM_DAYS} дня")
    monthly = PLANS[plan].monthly_price_kopecks
    return ceil(monthly * days / 30)


def referral_month_bonus(days: int) -> int:
    """One bonus day for every fully paid 30-day block, credited immediately."""
    return max(0, days // 30)
