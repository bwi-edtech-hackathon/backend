"""Stochastic AI bot for battles. Not an LLM — per spec §8.5.

Bots run as asyncio tasks inside the battle WebSocket handler.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from decimal import Decimal

from app.models.battle import BotTier

_ACCURACY = {
    BotTier.BRONZE: 0.60,
    BotTier.SILVER: 0.75,
    BotTier.GOLD: 0.88,
    BotTier.PLATINUM: 0.95,
}

_TIME_RANGE_MS = {
    BotTier.BRONZE: (8000, 15000),
    BotTier.SILVER: (5000, 12000),
    BotTier.GOLD: (4000, 8000),
    BotTier.PLATINUM: (3000, 6000),
}

_BOT_NAMES = [
    "Aziza", "Sherzod", "Madina", "Bekzod", "Nigora",
    "Javokhir", "Dilshoda", "Otabek", "Munisa", "Ruslan",
    "Gulnoza", "Asad", "Sevara", "Doniyor", "Lola",
]


@dataclass
class BotAnswer:
    answer: str
    time_ms: int
    is_correct: bool


def pick_bot_name() -> str:
    return random.choice(_BOT_NAMES)


def starting_rating(tier: BotTier) -> int:
    return {
        BotTier.BRONZE: 1000,
        BotTier.SILVER: 1300,
        BotTier.GOLD: 1600,
        BotTier.PLATINUM: 1900,
    }[tier]


class BattleBot:
    """Stochastic process: picks correct/wrong probabilistically given difficulty."""

    def __init__(self, tier: BotTier):
        self.tier = tier
        self.accuracy = _ACCURACY[tier]
        self.time_range_ms = _TIME_RANGE_MS[tier]

    async def answer(
        self,
        correct_answer: str,
        wrong_options: list[str],
        difficulty: Decimal | float = Decimal("0.5"),
    ) -> BotAnswer:
        """Sleep realistic time, then return answer (correct or random wrong)."""
        difficulty_f = float(difficulty)
        adjusted = self.accuracy * (1.0 - difficulty_f * 0.3)
        is_correct = random.random() < adjusted
        time_ms = random.randint(*self.time_range_ms)
        # Don't actually sleep here in tests; caller decides scheduling.
        await asyncio.sleep(0)
        if is_correct:
            return BotAnswer(answer=correct_answer, time_ms=time_ms, is_correct=True)
        if not wrong_options:
            return BotAnswer(answer=correct_answer, time_ms=time_ms, is_correct=True)
        return BotAnswer(answer=random.choice(wrong_options), time_ms=time_ms, is_correct=False)
