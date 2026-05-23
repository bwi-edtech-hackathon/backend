"""ELO rating math + tier bands.

Tier bands (Q14 = A):
- Bronze:   < 1200
- Silver:   1200–1499
- Gold:     1500–1799
- Platinum: 1800+
"""

from __future__ import annotations

from dataclasses import dataclass


def k_factor(rating: int, battles_count: int) -> int:
    if battles_count < 10:
        return 40  # provisional
    if rating > 2000:
        return 16  # master
    return 24     # normal


def expected_score(rating_a: int, rating_b: int) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


@dataclass
class EloUpdate:
    new_rating_a: int
    new_rating_b: int
    delta_a: int
    delta_b: int


def apply_elo(
    rating_a: int,
    rating_b: int,
    actual_a: float,  # 1.0 win, 0.5 draw, 0.0 loss
    battles_a: int,
    battles_b: int,
) -> EloUpdate:
    exp_a = expected_score(rating_a, rating_b)
    exp_b = 1.0 - exp_a
    actual_b = 1.0 - actual_a
    k_a = k_factor(rating_a, battles_a)
    k_b = k_factor(rating_b, battles_b)
    delta_a = round(k_a * (actual_a - exp_a))
    delta_b = round(k_b * (actual_b - exp_b))
    return EloUpdate(
        new_rating_a=rating_a + delta_a,
        new_rating_b=rating_b + delta_b,
        delta_a=delta_a,
        delta_b=delta_b,
    )


def tier_for(rating: int) -> str:
    if rating < 1200:
        return "BRONZE"
    if rating < 1500:
        return "SILVER"
    if rating < 1800:
        return "GOLD"
    return "PLATINUM"


def next_tier_threshold(rating: int) -> int | None:
    if rating < 1200:
        return 1200
    if rating < 1500:
        return 1500
    if rating < 1800:
        return 1800
    return None
