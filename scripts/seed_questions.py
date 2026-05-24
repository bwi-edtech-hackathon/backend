"""Seed Math questions for the demo (BMBA-style: 35 closed + 10 open).

Run with:
    python scripts/seed_questions.py

Idempotent — re-running won't duplicate. Topics are created on the fly. The
question bank mirrors the topic coverage the frontend's mock data assumes:
quadratics, linear equations, inequalities, logarithms, functions, trigonometry,
sequences & series, probability, geometry.

These are NOT official BMBA questions — they're pedagogically valid practice
items written for the hackathon demo.
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from app.core.db import async_session_factory  # noqa: E402
from app.core.slugs import slugify  # noqa: E402
from app.models.catalog import (  # noqa: E402
    Question,
    QuestionType,
    Subject,
    SubjectCode,
    Topic,
)


# ─────────────────────────── Topic plan ───────────────────────────
TOPICS: list[dict] = [
    {"name_en": "Quadratic equations", "name_uz": "Kvadrat tenglamalar",  "name_ru": "Квадратные уравнения", "weight": 0.95},
    {"name_en": "Linear equations",    "name_uz": "Chiziqli tenglamalar", "name_ru": "Линейные уравнения",   "weight": 0.85},
    {"name_en": "Inequalities",        "name_uz": "Tengsizliklar",        "name_ru": "Неравенства",          "weight": 0.80},
    {"name_en": "Logarithms",          "name_uz": "Logarifmlar",          "name_ru": "Логарифмы",            "weight": 0.80},
    {"name_en": "Functions",           "name_uz": "Funksiyalar",          "name_ru": "Функции",              "weight": 0.85},
    {"name_en": "Trigonometry",        "name_uz": "Trigonometriya",       "name_ru": "Тригонометрия",        "weight": 0.85},
    {"name_en": "Sequences & series",  "name_uz": "Ketma-ketliklar",      "name_ru": "Последовательности",   "weight": 0.70},
    {"name_en": "Probability",         "name_uz": "Ehtimollik",           "name_ru": "Вероятность",          "weight": 0.65},
    {"name_en": "Geometry",            "name_uz": "Geometriya",           "name_ru": "Геометрия",            "weight": 0.90},
]


def _opt(a: str, b: str, c: str, d: str) -> dict:
    return {
        "A": {"en": a, "uz": a, "ru": a},
        "B": {"en": b, "uz": b, "ru": b},
        "C": {"en": c, "uz": c, "ru": c},
        "D": {"en": d, "uz": d, "ru": d},
    }


# ─────────────────────────── Closed-type bank (Section A) ───────────────────────────
# Each entry: (topic_name_en, body_en, options, correct, difficulty 0..1, battle_ok)
CLOSED: list[tuple[str, str, dict, str, float, bool]] = [
    # Quadratic equations
    ("Quadratic equations", "Find the discriminant of x² − 5x + 6 = 0.",
     _opt("D = 1", "D = 7", "D = −1", "D = 49"), "A", 0.30, True),
    ("Quadratic equations", "Solve x² − 7x + 12 = 0.",
     _opt("x = 3, x = 4", "x = 2, x = 6", "x = −3, x = −4", "no real roots"), "A", 0.30, True),
    ("Quadratic equations", "For which k does kx² − 4x + 1 = 0 have one root?",
     _opt("k = 4", "k = 0", "k = 1", "k = 2"), "A", 0.55, True),
    ("Quadratic equations", "x² + bx + 9 = 0 has a double root. b = ?",
     _opt("±6", "±3", "9", "0"), "A", 0.45, True),
    ("Quadratic equations", "Sum of roots of 2x² − 6x − 5 = 0 equals…",
     _opt("3", "−3", "5/2", "−5/2"), "A", 0.40, True),

    # Linear equations
    ("Linear equations", "Solve 3x − 7 = 2x + 5.",
     _opt("x = 12", "x = 2", "x = −12", "x = 5"), "A", 0.15, True),
    ("Linear equations", "If 5(x − 2) = 3x + 4, x = ?",
     _opt("3", "7", "5", "−5"), "A", 0.25, True),
    ("Linear equations", "The line y = 2x + 1 intersects the x-axis at…",
     _opt("(−1/2, 0)", "(1/2, 0)", "(0, 1)", "(0, −1)"), "A", 0.35, True),
    ("Linear equations", "Slope of the line through (1, 2) and (3, 8) is…",
     _opt("3", "2", "4", "6"), "A", 0.30, True),

    # Inequalities
    ("Inequalities", "Solve 2x − 3 ≥ 7.",
     _opt("x ≥ 2", "x ≥ 5", "x ≤ 5", "x ≥ 4"), "B", 0.20, True),
    ("Inequalities", "Which set satisfies |x − 3| < 5?",
     _opt("(−2, 8)", "(−5, 5)", "(3, 8)", "(−∞, 8)"), "A", 0.50, True),
    ("Inequalities", "x² − 4 ≤ 0 ⇔ ?",
     _opt("−2 ≤ x ≤ 2", "x ≤ −2 or x ≥ 2", "x ≤ 4", "all x"), "A", 0.55, True),
    ("Inequalities", "Solve 1/(x − 1) > 0.",
     _opt("x > 1", "x ≠ 1", "x < 1", "all x"), "A", 0.50, True),

    # Logarithms
    ("Logarithms", "log₂(32) − log₂(4) = ?",
     _opt("1", "3", "5", "8"), "B", 0.30, True),
    ("Logarithms", "If logₐ b = 3, then a^(2·logₐ b) = ?",
     _opt("b²", "b³", "b⁶", "a⁶"), "C", 0.55, True),
    ("Logarithms", "Solve log₃(x) = 4.",
     _opt("x = 12", "x = 64", "x = 81", "x = 7"), "C", 0.35, True),
    ("Logarithms", "log(100) + log(10) = ?",
     _opt("2", "3", "10", "20"), "B", 0.25, True),

    # Functions
    ("Functions", "If f(x) = 2x + 1, then f(3) = ?",
     _opt("5", "6", "7", "8"), "C", 0.10, True),
    ("Functions", "Domain of f(x) = √(x − 2) is…",
     _opt("x ≥ 2", "x > 2", "all x", "x ≤ 2"), "A", 0.30, True),
    ("Functions", "If g(x) = x² and h(x) = x + 1, then g(h(2)) = ?",
     _opt("9", "5", "7", "4"), "A", 0.40, True),
    ("Functions", "Range of y = sin x is…",
     _opt("[−1, 1]", "(−1, 1)", "ℝ", "[0, 1]"), "A", 0.30, True),

    # Trigonometry
    ("Trigonometry", "If sin θ = 3/5 and θ is acute, cos θ = ?",
     _opt("3/4", "4/5", "5/4", "1/5"), "B", 0.30, True),
    ("Trigonometry", "sin 30° + cos 60° = ?",
     _opt("1", "1/2", "√3/2", "0"), "A", 0.35, True),
    ("Trigonometry", "tan 45° = ?",
     _opt("0", "1", "√2", "√3"), "B", 0.10, True),
    ("Trigonometry", "If cos x = 0 and 0 ≤ x ≤ π, then x = ?",
     _opt("0", "π/4", "π/2", "π"), "C", 0.30, True),

    # Sequences & series
    ("Sequences & series", "5th term of arithmetic sequence 3, 7, 11, … equals…",
     _opt("15", "19", "21", "23"), "B", 0.20, True),
    ("Sequences & series", "Sum of 1 + 2 + 3 + … + 100 equals…",
     _opt("5050", "5000", "10100", "1010"), "A", 0.20, True),
    ("Sequences & series", "Geometric sequence: a₁ = 2, q = 3. a₄ = ?",
     _opt("18", "54", "24", "162"), "B", 0.40, True),
    ("Sequences & series", "Sum to infinity of 1 + 1/2 + 1/4 + … equals…",
     _opt("2", "1", "3/2", "diverges"), "A", 0.35, True),

    # Probability
    ("Probability", "Probability of rolling an even number on a fair die equals…",
     _opt("1/6", "1/3", "1/2", "2/3"), "C", 0.10, True),
    ("Probability", "Two coins are tossed. P(both heads) = ?",
     _opt("1/2", "1/4", "1/3", "1/8"), "B", 0.20, True),
    ("Probability", "A bag has 3 red and 7 blue balls. P(red) = ?",
     _opt("3/7", "7/10", "3/10", "1/3"), "C", 0.20, True),

    # Geometry
    ("Geometry", "Area of a circle with radius 4 (π ≈ 3.14) ≈ ?",
     _opt("12.56", "25.12", "50.24", "100.48"), "C", 0.25, True),
    ("Geometry", "Hypotenuse of a right triangle with legs 3 and 4 is…",
     _opt("5", "6", "7", "√7"), "A", 0.10, True),
    ("Geometry", "Volume of a cube with edge 3 cm equals…",
     _opt("9 cm³", "18 cm³", "27 cm³", "81 cm³"), "C", 0.20, True),
    ("Geometry", "Sum of interior angles of a hexagon equals…",
     _opt("360°", "540°", "720°", "900°"), "C", 0.40, True),
]


# ─────────────────────────── Open-type bank (Section B) ───────────────────────────
# (topic, body, correct_answer (list = accepted variants), difficulty)
OPEN_A: list[tuple[str, str, list, float]] = [
    ("Quadratic equations", "Find the smallest positive integer x for which x² − 4x − 5 > 0.", ["6"], 0.45),
    ("Linear equations",    "Find x: 4x − 9 = 2x + 7.", ["8"], 0.20),
    ("Inequalities",        "Find the largest integer x satisfying 3x − 2 < 7.", ["2"], 0.40),
    ("Logarithms",          "Solve log₂(x + 1) = 3.", ["7"], 0.35),
    ("Functions",           "If f(x) = x² − 4, find f(−3).", ["5"], 0.20),
    ("Trigonometry",        "Compute sin(π/2).", ["1"], 0.10),
    ("Sequences & series",  "Find the 10th term of arithmetic sequence with a₁ = 2, d = 3.", ["29"], 0.30),
    ("Probability",         "A die is rolled. Probability of getting 6, as a decimal to 2 d.p.", ["0.17", "1/6", "0.166", "0.166667"], 0.30),
    ("Geometry",            "Perimeter of a square with area 49 cm² is __ cm.", ["28"], 0.30),
    ("Geometry",            "How many sides does a regular polygon have if each interior angle is 120°?", ["6"], 0.45),
]


async def _ensure_topic(db, subject_id, plan: dict) -> Topic:
    existing = (
        await db.execute(
            select(Topic).where(
                Topic.subject_id == subject_id,
                Topic.slug == slugify(plan["name_en"]),
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    topic = Topic(
        subject_id=subject_id,
        slug=slugify(plan["name_en"]),
        depth=2,
        name_uz=plan["name_uz"],
        name_ru=plan["name_ru"],
        name_en=plan["name_en"],
        weight=Decimal(str(plan["weight"])),
    )
    db.add(topic)
    await db.flush()
    return topic


async def _ensure_question(
    db,
    *,
    subject_id,
    topic_id,
    body_en: str,
    qtype: QuestionType,
    options: dict | None,
    correct_answer,
    difficulty: float,
    points: float,
    suitable_for_battle: bool,
) -> bool:
    slug = slugify(body_en)[:78]
    existing = (
        await db.execute(select(Question).where(Question.slug == slug))
    ).scalar_one_or_none()
    if existing:
        return False
    q = Question(
        subject_id=subject_id,
        topic_id=topic_id,
        slug=slug,
        type=qtype,
        body_uz=body_en,
        body_ru=body_en,
        body_en=body_en,
        options=options,
        correct_answer=correct_answer,
        accepted_patterns=None,
        points=Decimal(str(points)),
        difficulty=Decimal(str(difficulty)),
        suitable_for_battle=suitable_for_battle,
        source_tier=3,
        source_note="hackathon-seed",
    )
    db.add(q)
    return True


async def seed() -> None:
    async with async_session_factory() as db:
        math = (
            await db.execute(select(Subject).where(Subject.code == SubjectCode.MATH))
        ).scalar_one_or_none()
        if not math:
            print("⚠ Math subject not found — run scripts/seed_subjects.py first")
            return

        # Topics
        topics_by_name: dict[str, Topic] = {}
        for plan in TOPICS:
            topic = await _ensure_topic(db, math.id, plan)
            topics_by_name[plan["name_en"]] = topic
        await db.commit()

        created_q = 0
        for topic_name, body, options, correct, difficulty, battle_ok in CLOSED:
            topic = topics_by_name[topic_name]
            if await _ensure_question(
                db,
                subject_id=math.id,
                topic_id=topic.id,
                body_en=body,
                qtype=QuestionType.CLOSED,
                options=options,
                correct_answer=correct,
                difficulty=difficulty,
                points=2.2,
                suitable_for_battle=battle_ok,
            ):
                created_q += 1
        for topic_name, body, accepted, difficulty in OPEN_A:
            topic = topics_by_name[topic_name]
            if await _ensure_question(
                db,
                subject_id=math.id,
                topic_id=topic.id,
                body_en=body,
                qtype=QuestionType.OPEN_A,
                options=None,
                correct_answer=accepted,
                difficulty=difficulty,
                points=3.2,
                suitable_for_battle=False,
            ):
                created_q += 1
        await db.commit()
        print(f"✅ Math: {len(topics_by_name)} topics, {created_q} new questions")


if __name__ == "__main__":
    asyncio.run(seed())
