from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceEstimate:
    estimated_cost: float
    price: float
    timeline_days: int


def calculate_price(
    hours: float,
    internal_hourly_cost: float,
    target_margin: float,
    timeline_days: int | None = None,
) -> PriceEstimate:
    if hours <= 0 or internal_hourly_cost <= 0:
        raise ValueError("Hours and internal hourly cost must be greater than zero.")
    if not 0 <= target_margin < 0.90:
        raise ValueError("Target margin must be between 0 and 0.90.")

    estimated_cost = hours * internal_hourly_cost
    price = estimated_cost / (1 - target_margin)
    days = timeline_days if timeline_days is not None else max(1, round(hours / 6))
    if days <= 0:
        raise ValueError("Timeline days must be greater than zero.")
    return PriceEstimate(round(estimated_cost, 2), round(price, 2), days)

