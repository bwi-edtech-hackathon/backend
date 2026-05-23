"""Unit tests for ELO math + tier bands."""

from __future__ import annotations

import pytest

from app.modules.battle.elo import (
    apply_elo,
    expected_score,
    k_factor,
    next_tier_threshold,
    tier_for,
)


def test_k_factor_provisional() -> None:
    assert k_factor(1200, 0) == 40
    assert k_factor(1200, 9) == 40


def test_k_factor_normal() -> None:
    assert k_factor(1500, 50) == 24


def test_k_factor_master() -> None:
    assert k_factor(2100, 50) == 16


def test_expected_score_equal_ratings() -> None:
    assert expected_score(1500, 1500) == pytest.approx(0.5, abs=1e-6)


def test_apply_elo_upset() -> None:
    """Lower-rated player wins."""
    res = apply_elo(rating_a=1200, rating_b=1600, actual_a=1.0, battles_a=20, battles_b=20)
    assert res.delta_a > 0
    assert res.delta_b < 0
    assert res.delta_a == -res.delta_b  # symmetric when same K


def test_tier_bands() -> None:
    assert tier_for(1100) == "BRONZE"
    assert tier_for(1200) == "SILVER"
    assert tier_for(1499) == "SILVER"
    assert tier_for(1500) == "GOLD"
    assert tier_for(1799) == "GOLD"
    assert tier_for(1800) == "PLATINUM"
    assert tier_for(2400) == "PLATINUM"


def test_next_tier_threshold() -> None:
    assert next_tier_threshold(1100) == 1200
    assert next_tier_threshold(1400) == 1500
    assert next_tier_threshold(1700) == 1800
    assert next_tier_threshold(2000) is None
