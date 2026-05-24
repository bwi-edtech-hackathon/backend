"""Seed topics + questions for all 8 BMBA subjects.

Per subject:
    • ~9 topics (depth=2) under the subject
    • 45 study questions (35 closed + 10 open)  -- suitable_for_battle = False
    • 50 battle questions (all closed)          -- suitable_for_battle = True

Total: 8 × 95 = 760 questions. Idempotent — re-running won't duplicate.

Run with:
    python scripts/seed_content.py
or via the unified runner:
    python scripts/seed_all.py
"""

from __future__ import annotations

import asyncio
import random
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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

Letter = str  # "A" | "B" | "C" | "D"


def opts(a: str, b: str, c: str, d: str) -> dict:
    return {
        "A": {"en": a, "uz": a, "ru": a},
        "B": {"en": b, "uz": b, "ru": b},
        "C": {"en": c, "uz": c, "ru": c},
        "D": {"en": d, "uz": d, "ru": d},
    }


def shuffle_options(correct_text: str, distractors: list[str], rng: random.Random) -> tuple[dict, Letter]:
    """Place correct text in a random slot, fill rest with distractors."""
    while len(distractors) < 3:
        distractors.append(f"None of the above {len(distractors)}")
    chosen = rng.sample(distractors, 3)
    pool = [correct_text] + chosen
    rng.shuffle(pool)
    letters = ["A", "B", "C", "D"]
    options = opts(pool[0], pool[1], pool[2], pool[3])
    correct_letter = letters[pool.index(correct_text)]
    return options, correct_letter


# ─────────────────────────────────────────────────────────────────────────────
# Topic plans per subject (depth=2; weights influence roadmap impact)
# ─────────────────────────────────────────────────────────────────────────────

TOPIC_PLANS: dict[SubjectCode, list[dict]] = {
    SubjectCode.MATH: [
        {"name_en": "Quadratic equations",  "name_uz": "Kvadrat tenglamalar",  "name_ru": "Квадратные уравнения", "weight": 0.95},
        {"name_en": "Linear equations",     "name_uz": "Chiziqli tenglamalar", "name_ru": "Линейные уравнения",   "weight": 0.85},
        {"name_en": "Inequalities",         "name_uz": "Tengsizliklar",        "name_ru": "Неравенства",          "weight": 0.80},
        {"name_en": "Logarithms",           "name_uz": "Logarifmlar",          "name_ru": "Логарифмы",            "weight": 0.80},
        {"name_en": "Functions",            "name_uz": "Funksiyalar",          "name_ru": "Функции",              "weight": 0.85},
        {"name_en": "Trigonometry",         "name_uz": "Trigonometriya",       "name_ru": "Тригонометрия",        "weight": 0.85},
        {"name_en": "Sequences & series",   "name_uz": "Ketma-ketliklar",      "name_ru": "Последовательности",   "weight": 0.70},
        {"name_en": "Probability",          "name_uz": "Ehtimollik",           "name_ru": "Вероятность",          "weight": 0.65},
        {"name_en": "Geometry",             "name_uz": "Geometriya",           "name_ru": "Геометрия",            "weight": 0.90},
    ],
    SubjectCode.PHYS: [
        {"name_en": "Kinematics",           "name_uz": "Kinematika",           "name_ru": "Кинематика",           "weight": 0.95},
        {"name_en": "Newton's laws",        "name_uz": "Nyuton qonunlari",     "name_ru": "Законы Ньютона",       "weight": 0.90},
        {"name_en": "Energy & work",        "name_uz": "Energiya va ish",      "name_ru": "Энергия и работа",     "weight": 0.85},
        {"name_en": "Momentum",             "name_uz": "Impuls",               "name_ru": "Импульс",              "weight": 0.75},
        {"name_en": "Thermodynamics",       "name_uz": "Termodinamika",        "name_ru": "Термодинамика",        "weight": 0.80},
        {"name_en": "Electrostatics",       "name_uz": "Elektrostatika",       "name_ru": "Электростатика",       "weight": 0.75},
        {"name_en": "DC circuits",          "name_uz": "Doimiy tok",           "name_ru": "Постоянный ток",       "weight": 0.85},
        {"name_en": "Optics",               "name_uz": "Optika",               "name_ru": "Оптика",               "weight": 0.70},
        {"name_en": "Waves",                "name_uz": "To'lqinlar",           "name_ru": "Волны",                "weight": 0.65},
    ],
    SubjectCode.CHEM: [
        {"name_en": "Atomic structure",     "name_uz": "Atom tuzilishi",       "name_ru": "Строение атома",       "weight": 0.85},
        {"name_en": "Periodic table",       "name_uz": "Davriy jadval",        "name_ru": "Периодическая таблица","weight": 0.80},
        {"name_en": "Chemical bonding",     "name_uz": "Kimyoviy bog'lar",     "name_ru": "Химическая связь",     "weight": 0.85},
        {"name_en": "Stoichiometry",        "name_uz": "Stexiometriya",        "name_ru": "Стехиометрия",         "weight": 0.95},
        {"name_en": "Acids and bases",      "name_uz": "Kislota va asoslar",   "name_ru": "Кислоты и основания",  "weight": 0.80},
        {"name_en": "Redox reactions",      "name_uz": "Oksidlanish-qaytarilish","name_ru":"Окислительно-восстановительные", "weight": 0.75},
        {"name_en": "Organic chemistry",    "name_uz": "Organik kimyo",        "name_ru": "Органическая химия",   "weight": 0.85},
        {"name_en": "Solutions",            "name_uz": "Eritmalar",            "name_ru": "Растворы",             "weight": 0.70},
        {"name_en": "Gas laws",             "name_uz": "Gaz qonunlari",        "name_ru": "Законы газов",         "weight": 0.65},
    ],
    SubjectCode.BIO: [
        {"name_en": "Cell biology",         "name_uz": "Hujayra biologiyasi",  "name_ru": "Клеточная биология",   "weight": 0.90},
        {"name_en": "Genetics",             "name_uz": "Genetika",             "name_ru": "Генетика",             "weight": 0.95},
        {"name_en": "Human anatomy",        "name_uz": "Inson anatomiyasi",    "name_ru": "Анатомия человека",    "weight": 0.85},
        {"name_en": "Plants",               "name_uz": "O'simliklar",          "name_ru": "Растения",             "weight": 0.70},
        {"name_en": "Animals",              "name_uz": "Hayvonlar",            "name_ru": "Животные",             "weight": 0.65},
        {"name_en": "Evolution",            "name_uz": "Evolyutsiya",          "name_ru": "Эволюция",             "weight": 0.75},
        {"name_en": "Ecology",              "name_uz": "Ekologiya",            "name_ru": "Экология",             "weight": 0.70},
        {"name_en": "Microbiology",         "name_uz": "Mikrobiologiya",       "name_ru": "Микробиология",        "weight": 0.65},
        {"name_en": "Biochemistry",         "name_uz": "Biokimyo",             "name_ru": "Биохимия",             "weight": 0.80},
    ],
    SubjectCode.HIST: [
        {"name_en": "Ancient Uzbekistan",   "name_uz": "Qadimgi O'zbekiston",  "name_ru": "Древний Узбекистан",   "weight": 0.85},
        {"name_en": "Timurid era",          "name_uz": "Temuriylar davri",     "name_ru": "Эпоха Тимуридов",      "weight": 0.95},
        {"name_en": "Khanates period",      "name_uz": "Xonliklar davri",      "name_ru": "Период ханств",        "weight": 0.80},
        {"name_en": "Russian Empire",       "name_uz": "Rus imperiyasi",       "name_ru": "Российская империя",   "weight": 0.75},
        {"name_en": "Soviet era",           "name_uz": "Sovet davri",          "name_ru": "Советская эпоха",      "weight": 0.80},
        {"name_en": "Independence",         "name_uz": "Mustaqillik",          "name_ru": "Независимость",        "weight": 0.95},
        {"name_en": "World history",        "name_uz": "Jahon tarixi",         "name_ru": "Всемирная история",    "weight": 0.70},
        {"name_en": "Cultural figures",     "name_uz": "Madaniyat arboblari",  "name_ru": "Деятели культуры",     "weight": 0.65},
        {"name_en": "Modern Uzbekistan",    "name_uz": "Zamonaviy O'zbekiston","name_ru": "Современный Узбекистан","weight": 0.75},
    ],
    SubjectCode.GEOG: [
        {"name_en": "Physical geography",   "name_uz": "Fizik geografiya",     "name_ru": "Физическая география", "weight": 0.85},
        {"name_en": "Uzbekistan regions",   "name_uz": "O'zbekiston viloyatlari","name_ru":"Регионы Узбекистана", "weight": 0.95},
        {"name_en": "Rivers and lakes",     "name_uz": "Daryolar va ko'llar",  "name_ru": "Реки и озёра",         "weight": 0.80},
        {"name_en": "Climate",              "name_uz": "Iqlim",                "name_ru": "Климат",               "weight": 0.75},
        {"name_en": "Continents",           "name_uz": "Materiklar",           "name_ru": "Материки",             "weight": 0.70},
        {"name_en": "Population",           "name_uz": "Aholi",                "name_ru": "Население",            "weight": 0.65},
        {"name_en": "Natural resources",    "name_uz": "Tabiiy boyliklar",     "name_ru": "Природные ресурсы",    "weight": 0.75},
        {"name_en": "Capitals & countries", "name_uz": "Davlatlar va poytaxtlar","name_ru":"Страны и столицы",    "weight": 0.85},
        {"name_en": "Cartography",          "name_uz": "Kartografiya",         "name_ru": "Картография",          "weight": 0.60},
    ],
    SubjectCode.UZB_LIT: [
        {"name_en": "Grammar",              "name_uz": "Grammatika",           "name_ru": "Грамматика",           "weight": 0.95},
        {"name_en": "Phonetics",            "name_uz": "Fonetika",             "name_ru": "Фонетика",             "weight": 0.75},
        {"name_en": "Morphology",           "name_uz": "Morfologiya",          "name_ru": "Морфология",           "weight": 0.85},
        {"name_en": "Syntax",               "name_uz": "Sintaksis",            "name_ru": "Синтаксис",            "weight": 0.80},
        {"name_en": "Vocabulary",           "name_uz": "Leksika",              "name_ru": "Лексика",              "weight": 0.70},
        {"name_en": "Classical literature", "name_uz": "Mumtoz adabiyot",      "name_ru": "Классическая литература","weight": 0.90},
        {"name_en": "Modern literature",    "name_uz": "Zamonaviy adabiyot",   "name_ru": "Современная литература","weight": 0.80},
        {"name_en": "Poetry",               "name_uz": "She'riyat",            "name_ru": "Поэзия",               "weight": 0.85},
        {"name_en": "Authors",              "name_uz": "Mualliflar",           "name_ru": "Авторы",               "weight": 0.75},
    ],
    SubjectCode.RUS_LIT: [
        {"name_en": "Grammar",              "name_uz": "Grammatika",           "name_ru": "Грамматика",           "weight": 0.95},
        {"name_en": "Phonetics",            "name_uz": "Fonetika",             "name_ru": "Фонетика",             "weight": 0.75},
        {"name_en": "Morphology",           "name_uz": "Morfologiya",          "name_ru": "Морфология",           "weight": 0.85},
        {"name_en": "Syntax",               "name_uz": "Sintaksis",            "name_ru": "Синтаксис",            "weight": 0.80},
        {"name_en": "Vocabulary",           "name_uz": "Leksika",              "name_ru": "Лексика",              "weight": 0.70},
        {"name_en": "19th century lit",     "name_uz": "XIX asr adabiyoti",    "name_ru": "Литература XIX века",  "weight": 0.90},
        {"name_en": "20th century lit",     "name_uz": "XX asr adabiyoti",     "name_ru": "Литература XX века",   "weight": 0.85},
        {"name_en": "Poetry",               "name_uz": "She'riyat",            "name_ru": "Поэзия",               "weight": 0.80},
        {"name_en": "Authors",              "name_uz": "Mualliflar",           "name_ru": "Авторы",               "weight": 0.75},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Question banks per subject (mix of hand-written + template-generated)
# ─────────────────────────────────────────────────────────────────────────────

ClosedRow = tuple[str, str, dict, Letter, float]   # topic_en, body, options, correct, difficulty
OpenRow = tuple[str, str, list, float]             # topic_en, body, accepted, difficulty


def _q(topic: str, body: str, correct: str, distractors: list[str], diff: float, rng: random.Random) -> ClosedRow:
    options, letter = shuffle_options(correct, list(distractors), rng)
    return (topic, body, options, letter, diff)


def gen_math(rng: random.Random) -> tuple[list[ClosedRow], list[OpenRow]]:
    closed: list[ClosedRow] = []
    open_q: list[OpenRow] = []

    # Quadratic equations — multiple solved instances
    for a, b, c in [(1, -5, 6), (1, -7, 12), (1, -3, 2), (1, -9, 20), (1, -8, 15),
                    (1, 1, -6), (1, 2, -8), (1, -2, -15), (1, 4, -5), (1, -6, 8)]:
        d = b * b - 4 * a * c
        closed.append(_q("Quadratic equations",
                         f"Find the discriminant of x² + ({b})x + ({c}) = 0.",
                         f"D = {d}", [f"D = {d + 4}", f"D = {abs(d) - 1}", f"D = {-d}"],
                         0.30 + rng.random() * 0.2, rng))
        # roots when D > 0
        if d >= 0:
            r1 = (-b - int(d ** 0.5)) // 2 if (d ** 0.5).is_integer() else None
            r2 = (-b + int(d ** 0.5)) // 2 if (d ** 0.5).is_integer() else None
            if r1 is not None and r2 is not None and r1 * a * a + b * r1 + c == 0:
                roots = sorted([r1, r2])
                closed.append(_q("Quadratic equations",
                                 f"Solve x² + ({b})x + ({c}) = 0.",
                                 f"x = {roots[0]}, x = {roots[1]}",
                                 [f"x = {roots[0]+1}, x = {roots[1]+1}",
                                  f"x = {-roots[0]}, x = {-roots[1]}",
                                  "no real roots"],
                                 0.35, rng))

    # Vieta + parametric forms
    closed += [
        _q("Quadratic equations", "Sum of roots of x² − 7x + 12 = 0 equals…",
           "7", ["−7", "12", "5"], 0.30, rng),
        _q("Quadratic equations", "Product of roots of 2x² − 8x + 6 = 0 equals…",
           "3", ["−3", "4", "6"], 0.45, rng),
        _q("Quadratic equations", "x² + bx + 9 = 0 has a double root. |b| = ?",
           "6", ["3", "9", "0"], 0.45, rng),
    ]

    # Linear equations
    for a, b in [(3, -7), (5, -2), (2, -10), (4, -8), (6, -1), (7, -14), (3, 6), (4, -12), (5, 15), (2, -6)]:
        # ax + b = 0 → x = -b/a
        if -b % a == 0:
            x = -b // a
            closed.append(_q("Linear equations",
                             f"Solve {a}x + ({b}) = 0.",
                             f"x = {x}",
                             [f"x = {x+1}", f"x = {-x}", f"x = {x-2}"],
                             0.20, rng))

    closed += [
        _q("Linear equations", "Slope of the line through (1, 2) and (3, 8) is…",
           "3", ["2", "4", "6"], 0.30, rng),
        _q("Linear equations", "The line y = 2x + 1 intersects the x-axis at…",
           "(−1/2, 0)", ["(1/2, 0)", "(0, 1)", "(0, −1)"], 0.35, rng),
        _q("Linear equations", "Solve 3(x − 2) = 12.",
           "6", ["4", "8", "2"], 0.25, rng),
    ]

    # Inequalities
    closed += [
        _q("Inequalities", "Solve 2x − 3 ≥ 7.", "x ≥ 5",
           ["x ≥ 2", "x ≤ 5", "x ≥ 4"], 0.20, rng),
        _q("Inequalities", "Solve |x − 3| < 5.", "(−2, 8)",
           ["(−5, 5)", "(3, 8)", "(−∞, 8)"], 0.50, rng),
        _q("Inequalities", "x² − 4 ≤ 0 is equivalent to…", "−2 ≤ x ≤ 2",
           ["x ≤ −2 or x ≥ 2", "x ≤ 4", "all x"], 0.45, rng),
        _q("Inequalities", "Solve 1/(x − 1) > 0.", "x > 1",
           ["x ≠ 1", "x < 1", "all x"], 0.50, rng),
        _q("Inequalities", "Solve 5 − 2x ≤ 1.", "x ≥ 2",
           ["x ≤ 2", "x > 2", "x ≥ 3"], 0.30, rng),
        _q("Inequalities", "Solve x² > 9.", "x < −3 or x > 3",
           ["−3 < x < 3", "x > 3", "x < 9"], 0.50, rng),
    ]

    # Logarithms
    closed += [
        _q("Logarithms", "log₂(32) − log₂(4) = ?", "3",
           ["1", "5", "8"], 0.30, rng),
        _q("Logarithms", "Solve log₃(x) = 4.", "81",
           ["12", "64", "7"], 0.35, rng),
        _q("Logarithms", "log(100) + log(10) = ?", "3",
           ["2", "10", "20"], 0.25, rng),
        _q("Logarithms", "If logₐ b = 3, then a^(2·logₐ b) = ?", "b⁶",
           ["b²", "b³", "a⁶"], 0.55, rng),
        _q("Logarithms", "log₅(125) = ?", "3",
           ["2", "5", "25"], 0.20, rng),
        _q("Logarithms", "log₂(1/8) = ?", "−3",
           ["3", "−1/3", "1/3"], 0.35, rng),
        _q("Logarithms", "Solve 2^x = 16.", "4",
           ["8", "2", "16"], 0.25, rng),
    ]

    # Functions
    closed += [
        _q("Functions", "If f(x) = 2x + 1, then f(3) = ?", "7",
           ["5", "6", "8"], 0.10, rng),
        _q("Functions", "Domain of f(x) = √(x − 2) is…", "x ≥ 2",
           ["x > 2", "all x", "x ≤ 2"], 0.30, rng),
        _q("Functions", "If g(x) = x² and h(x) = x + 1, then g(h(2)) = ?", "9",
           ["5", "7", "4"], 0.40, rng),
        _q("Functions", "Range of y = sin x is…", "[−1, 1]",
           ["(−1, 1)", "ℝ", "[0, 1]"], 0.30, rng),
        _q("Functions", "If f(x) = x² − 3x, f(−2) = ?", "10",
           ["−2", "4", "−10"], 0.30, rng),
        _q("Functions", "Inverse of f(x) = 2x − 4 is…", "(x + 4)/2",
           ["(x − 4)/2", "2x + 4", "(4 − x)/2"], 0.45, rng),
    ]

    # Trigonometry
    closed += [
        _q("Trigonometry", "If sin θ = 3/5 and θ is acute, cos θ = ?", "4/5",
           ["3/4", "5/4", "1/5"], 0.30, rng),
        _q("Trigonometry", "sin 30° + cos 60° = ?", "1",
           ["1/2", "√3/2", "0"], 0.30, rng),
        _q("Trigonometry", "tan 45° = ?", "1",
           ["0", "√2", "√3"], 0.10, rng),
        _q("Trigonometry", "cos 0° = ?", "1",
           ["0", "−1", "1/2"], 0.10, rng),
        _q("Trigonometry", "If cos x = 0 and 0 ≤ x ≤ π, then x = ?", "π/2",
           ["0", "π/4", "π"], 0.30, rng),
        _q("Trigonometry", "sin²θ + cos²θ = ?", "1",
           ["0", "2", "sin 2θ"], 0.10, rng),
        _q("Trigonometry", "sin 90° = ?", "1",
           ["0", "−1", "√3/2"], 0.10, rng),
    ]

    # Sequences & series
    closed += [
        _q("Sequences & series", "5th term of arithmetic sequence 3, 7, 11, … equals…",
           "19", ["15", "21", "23"], 0.20, rng),
        _q("Sequences & series", "Sum 1 + 2 + … + 100 equals…",
           "5050", ["5000", "10100", "1010"], 0.20, rng),
        _q("Sequences & series", "Geometric sequence: a₁ = 2, q = 3. a₄ = ?",
           "54", ["18", "24", "162"], 0.40, rng),
        _q("Sequences & series", "Sum to infinity of 1 + 1/2 + 1/4 + … equals…",
           "2", ["1", "3/2", "diverges"], 0.35, rng),
        _q("Sequences & series", "10th term of 2, 5, 8, 11, … equals…",
           "29", ["27", "30", "32"], 0.25, rng),
        _q("Sequences & series", "Common ratio of 3, 12, 48, 192, … is…",
           "4", ["3", "6", "9"], 0.30, rng),
    ]

    # Probability
    closed += [
        _q("Probability", "P(rolling an even number on a fair die) = ?", "1/2",
           ["1/6", "1/3", "2/3"], 0.10, rng),
        _q("Probability", "Two coins are tossed. P(both heads) = ?", "1/4",
           ["1/2", "1/3", "1/8"], 0.20, rng),
        _q("Probability", "Bag: 3 red, 7 blue. P(red) = ?", "3/10",
           ["3/7", "7/10", "1/3"], 0.20, rng),
        _q("Probability", "P(rolling a 5 on a fair die) = ?", "1/6",
           ["1/5", "5/6", "1/3"], 0.15, rng),
        _q("Probability", "P(drawing an Ace from 52 cards) = ?", "1/13",
           ["1/4", "4/13", "1/52"], 0.30, rng),
    ]

    # Geometry
    closed += [
        _q("Geometry", "Area of a circle with radius 4 (π ≈ 3.14) ≈ ?", "50.24",
           ["12.56", "25.12", "100.48"], 0.25, rng),
        _q("Geometry", "Hypotenuse of legs 3 and 4 is…", "5",
           ["6", "7", "√7"], 0.10, rng),
        _q("Geometry", "Volume of a cube with edge 3 cm is…", "27 cm³",
           ["9 cm³", "18 cm³", "81 cm³"], 0.20, rng),
        _q("Geometry", "Sum of interior angles of a hexagon equals…", "720°",
           ["360°", "540°", "900°"], 0.40, rng),
        _q("Geometry", "Sum of interior angles of a triangle equals…", "180°",
           ["90°", "270°", "360°"], 0.10, rng),
        _q("Geometry", "Circumference of a circle with radius 5 (π ≈ 3.14) ≈ ?", "31.4",
           ["15.7", "78.5", "62.8"], 0.25, rng),
        _q("Geometry", "Area of triangle with base 6 and height 4 is…", "12",
           ["10", "24", "20"], 0.15, rng),
    ]

    # Open-ended
    open_q += [
        ("Quadratic equations", "Smallest positive integer x with x² − 4x − 5 > 0.", ["6"], 0.45),
        ("Linear equations",    "Find x: 4x − 9 = 2x + 7.", ["8"], 0.20),
        ("Inequalities",        "Largest integer x with 3x − 2 < 7.", ["2"], 0.40),
        ("Logarithms",          "Solve log₂(x + 1) = 3.", ["7"], 0.35),
        ("Functions",           "If f(x) = x² − 4, find f(−3).", ["5"], 0.20),
        ("Trigonometry",        "Compute sin(π/2).", ["1"], 0.10),
        ("Sequences & series",  "10th term of arithmetic sequence a₁ = 2, d = 3.", ["29"], 0.30),
        ("Probability",         "P(rolling a 6), as a decimal to 2 d.p.", ["0.17", "1/6", "0.166667"], 0.30),
        ("Geometry",            "Perimeter of a square with area 49 cm² is __ cm.", ["28"], 0.30),
        ("Geometry",            "Sides of a regular polygon with interior angle 120°.", ["6"], 0.45),
    ]

    return closed, open_q


def gen_physics(rng: random.Random) -> tuple[list[ClosedRow], list[OpenRow]]:
    closed: list[ClosedRow] = []
    open_q: list[OpenRow] = []

    # Kinematics
    for u, a, t in [(0, 10, 2), (5, 2, 3), (0, 9.8, 1), (10, 0, 5), (4, 2, 4),
                    (0, 5, 4), (8, 3, 2), (0, 10, 5), (12, 0, 3), (6, 4, 2)]:
        v = u + a * t
        closed.append(_q("Kinematics",
                         f"Object starts at {u} m/s, accelerates at {a} m/s². Velocity after {t} s?",
                         f"{v} m/s", [f"{v+1} m/s", f"{u} m/s", f"{a*t} m/s"],
                         0.30, rng))

    closed += [
        _q("Kinematics", "Acceleration due to gravity (Earth) is approximately…", "9.8 m/s²",
           ["9.81 km/s", "1.6 m/s²", "10 m/h²"], 0.10, rng),
        _q("Kinematics", "Distance = ½at² requires…", "uniform acceleration from rest",
           ["constant velocity", "free fall on Moon", "uniform deceleration to rest"], 0.40, rng),
        _q("Kinematics", "SI unit of velocity is…", "m/s",
           ["m/s²", "km", "N"], 0.10, rng),
    ]

    # Newton's laws
    for m, a in [(2, 5), (3, 4), (5, 2), (10, 1), (4, 6), (1, 9.8), (7, 3), (6, 5), (8, 2.5), (12, 3)]:
        F = m * a
        closed.append(_q("Newton's laws",
                         f"Net force on a {m} kg mass with acceleration {a} m/s²?",
                         f"{F} N", [f"{F+1} N", f"{m+a} N", f"{m/a if a else 0} N"],
                         0.30, rng))

    closed += [
        _q("Newton's laws", "Newton's 1st law (inertia) states an object…",
           "stays in motion at constant velocity unless acted on by a net force",
           ["always accelerates",
            "loses kinetic energy",
            "obeys conservation of charge"], 0.30, rng),
        _q("Newton's laws", "Action–reaction is which law?", "Third",
           ["First", "Second", "Zeroth"], 0.20, rng),
    ]

    # Energy & work
    for m, h in [(2, 5), (3, 4), (5, 2), (10, 1), (4, 6), (1, 10), (7, 3), (6, 5), (8, 2.5), (12, 3)]:
        PE = m * 9.8 * h
        closed.append(_q("Energy & work",
                         f"Potential energy of {m} kg at height {h} m (g = 9.8 m/s²)?",
                         f"{PE:.1f} J", [f"{PE+10:.1f} J", f"{m*h:.1f} J", f"{m*9.8:.1f} J"],
                         0.35, rng))

    closed += [
        _q("Energy & work", "SI unit of work is…", "Joule",
           ["Newton", "Watt", "Pascal"], 0.10, rng),
        _q("Energy & work", "Power = ?", "Work / time",
           ["Force × time", "Force × distance", "Mass × velocity"], 0.20, rng),
        _q("Energy & work", "Kinetic energy formula is…", "(1/2)mv²",
           ["mgh", "mv", "ma"], 0.20, rng),
    ]

    # Momentum
    closed += [
        _q("Momentum", "Momentum of 5 kg moving at 4 m/s is…", "20 kg·m/s",
           ["9 kg·m/s", "1.25 kg·m/s", "20 N"], 0.20, rng),
        _q("Momentum", "Impulse equals…", "Change in momentum",
           ["Force × mass", "Work done", "Power × time"], 0.30, rng),
        _q("Momentum", "Conservation of momentum holds when…", "Net external force is zero",
           ["Mass is constant", "Velocity is zero", "All collisions are elastic"], 0.40, rng),
    ]

    # Thermodynamics
    closed += [
        _q("Thermodynamics", "Absolute zero on the Kelvin scale is…", "0 K",
           ["−273 K", "100 K", "273 K"], 0.20, rng),
        _q("Thermodynamics", "Specific heat capacity of water is approximately…", "4186 J/(kg·K)",
           ["1000 J/(kg·K)", "100 J/(kg·K)", "419 J/(kg·K)"], 0.30, rng),
        _q("Thermodynamics", "1st law of thermodynamics is…", "Conservation of energy",
           ["Entropy never decreases", "PV = nRT", "Heat flows hot to cold"], 0.30, rng),
        _q("Thermodynamics", "Convert 25 °C to Kelvin.", "298 K",
           ["25 K", "248 K", "273 K"], 0.20, rng),
    ]

    # Electrostatics
    closed += [
        _q("Electrostatics", "Unit of electric charge is…", "Coulomb",
           ["Volt", "Ohm", "Newton"], 0.10, rng),
        _q("Electrostatics", "Force between two charges depends on…", "Product of charges and 1/r²",
           ["Their masses", "Speed of light", "Temperature"], 0.30, rng),
        _q("Electrostatics", "Like charges…", "repel each other",
           ["attract", "have no force", "cancel"], 0.10, rng),
        _q("Electrostatics", "Electric field unit is…", "V/m",
           ["A/m", "Wb/m²", "C/m"], 0.30, rng),
    ]

    # DC circuits
    for V, R in [(12, 4), (9, 3), (24, 6), (5, 10), (6, 2), (10, 5), (15, 3), (20, 4), (6, 12), (18, 9)]:
        I = V / R
        closed.append(_q("DC circuits",
                         f"Current through R = {R} Ω at V = {V} V?",
                         f"{I:g} A", [f"{V+R} A", f"{V*R} A", f"{V-R} A"],
                         0.25, rng))

    closed += [
        _q("DC circuits", "Ohm's law states…", "V = IR",
           ["V = IR²", "I = VR", "R = V·I"], 0.10, rng),
        _q("DC circuits", "Power dissipated by resistor is…", "I²R",
           ["IR", "V/I", "I/R"], 0.20, rng),
    ]

    # Optics
    closed += [
        _q("Optics", "Speed of light in vacuum is approximately…", "3 × 10⁸ m/s",
           ["3 × 10⁶ m/s", "3 × 10¹⁰ m/s", "1 × 10⁸ m/s"], 0.20, rng),
        _q("Optics", "Snell's law relates…", "Angles of incidence and refraction",
           ["Voltage and current", "Speed and momentum", "Mass and weight"], 0.35, rng),
        _q("Optics", "A convex lens converges light at the…", "Focal point",
           ["Vertex", "Center of curvature", "Optical axis"], 0.30, rng),
    ]

    # Waves
    closed += [
        _q("Waves", "Wave speed equals…", "Frequency × wavelength",
           ["Amplitude × period", "Frequency / wavelength", "Period × amplitude"], 0.25, rng),
        _q("Waves", "Sound is a…", "Longitudinal wave",
           ["Transverse wave", "Standing wave only", "Electromagnetic wave"], 0.30, rng),
        _q("Waves", "Doppler effect describes…", "Apparent change in frequency with motion",
           ["Reflection of waves", "Wave interference", "Wave absorption"], 0.40, rng),
    ]

    # Open-ended
    open_q += [
        ("Kinematics", "Velocity (m/s) after 4 s at 3 m/s² from rest.", ["12"], 0.20),
        ("Newton's laws", "Force (N) needed to accelerate 5 kg at 2 m/s².", ["10"], 0.20),
        ("Energy & work", "Kinetic energy (J) of 2 kg at 3 m/s.", ["9"], 0.25),
        ("Momentum", "Momentum (kg·m/s) of 4 kg at 5 m/s.", ["20"], 0.20),
        ("Thermodynamics", "Convert 100 °C to Kelvin.", ["373"], 0.25),
        ("Electrostatics", "Unit symbol for charge.", ["C"], 0.15),
        ("DC circuits", "Current (A) through 2 Ω at 6 V.", ["3"], 0.25),
        ("Optics", "Speed of light c in scientific notation (m/s, simplest).", ["3e8", "3*10^8", "300000000"], 0.40),
        ("Waves", "Wavelength (m) if v = 340 m/s and f = 170 Hz.", ["2"], 0.40),
        ("Kinematics", "Distance (m) covered in 3 s at constant 5 m/s.", ["15"], 0.20),
    ]

    return closed, open_q


def gen_chem(rng: random.Random) -> tuple[list[ClosedRow], list[OpenRow]]:
    closed: list[ClosedRow] = []
    open_q: list[OpenRow] = []

    elements = [
        ("H", "Hydrogen", 1), ("He", "Helium", 2), ("Li", "Lithium", 3),
        ("C", "Carbon", 6), ("N", "Nitrogen", 7), ("O", "Oxygen", 8),
        ("F", "Fluorine", 9), ("Na", "Sodium", 11), ("Mg", "Magnesium", 12),
        ("Al", "Aluminum", 13), ("Si", "Silicon", 14), ("P", "Phosphorus", 15),
        ("S", "Sulfur", 16), ("Cl", "Chlorine", 17), ("K", "Potassium", 19),
        ("Ca", "Calcium", 20), ("Fe", "Iron", 26), ("Cu", "Copper", 29),
        ("Zn", "Zinc", 30), ("Ag", "Silver", 47), ("Au", "Gold", 79),
    ]

    # Atomic structure / Periodic table
    for sym, name, z in elements:
        closed.append(_q("Atomic structure",
                         f"Atomic number of {name} ({sym}) is…",
                         str(z), [str(z + 1), str(z - 1), str(z + 2)],
                         0.20, rng))

    closed += [
        _q("Periodic table", "Noble gases are in group…", "18",
           ["1", "2", "17"], 0.20, rng),
        _q("Periodic table", "Element with chemical symbol K is…", "Potassium",
           ["Krypton", "Kalium", "Copper"], 0.30, rng),
        _q("Periodic table", "Most abundant gas in Earth's atmosphere is…", "Nitrogen",
           ["Oxygen", "Argon", "Carbon dioxide"], 0.20, rng),
        _q("Chemical bonding", "NaCl is an example of…", "Ionic bonding",
           ["Covalent bonding", "Metallic bonding", "Hydrogen bonding"], 0.20, rng),
        _q("Chemical bonding", "H₂O has which type of bond?", "Polar covalent",
           ["Ionic", "Non-polar covalent", "Metallic"], 0.25, rng),
        _q("Chemical bonding", "Number of bonds carbon typically forms is…", "4",
           ["2", "3", "5"], 0.20, rng),
    ]

    # Stoichiometry
    closed += [
        _q("Stoichiometry", "Avogadro's number is approximately…", "6.022 × 10²³",
           ["1.6 × 10⁻¹⁹", "9.81 × 10⁸", "3 × 10⁸"], 0.30, rng),
        _q("Stoichiometry", "Molar mass of H₂O is…", "18 g/mol",
           ["16 g/mol", "20 g/mol", "10 g/mol"], 0.25, rng),
        _q("Stoichiometry", "Moles in 18 g of water are…", "1",
           ["2", "18", "0.5"], 0.30, rng),
        _q("Stoichiometry", "Balanced: H₂ + Cl₂ → 2HCl. Mol HCl from 1 mol Cl₂ is…", "2",
           ["1", "3", "4"], 0.30, rng),
        _q("Stoichiometry", "Mass of 2 mol CO₂ is…", "88 g",
           ["44 g", "66 g", "176 g"], 0.40, rng),
    ]

    # Acids and bases
    closed += [
        _q("Acids and bases", "pH of pure water at 25 °C is…", "7",
           ["1", "10", "14"], 0.10, rng),
        _q("Acids and bases", "HCl is a…", "Strong acid",
           ["Strong base", "Weak acid", "Salt"], 0.20, rng),
        _q("Acids and bases", "NaOH is a…", "Strong base",
           ["Weak acid", "Strong acid", "Buffer"], 0.20, rng),
        _q("Acids and bases", "pH 4 means the solution is…", "Acidic",
           ["Basic", "Neutral", "Buffered"], 0.20, rng),
        _q("Acids and bases", "Neutralization produces…", "Salt + water",
           ["Acid + base", "Gas + water", "Salt + base"], 0.30, rng),
    ]

    # Redox
    closed += [
        _q("Redox reactions", "Oxidation is…", "Loss of electrons",
           ["Gain of electrons", "Loss of protons", "Loss of mass"], 0.25, rng),
        _q("Redox reactions", "Reduction is…", "Gain of electrons",
           ["Loss of electrons", "Loss of protons", "Gain of mass"], 0.25, rng),
        _q("Redox reactions", "Oxidation state of O in H₂O is…", "−2",
           ["+2", "0", "−1"], 0.35, rng),
        _q("Redox reactions", "Strong oxidizing agent: KMnO₄ is…", "Purple solid",
           ["Colorless gas", "White powder", "Yellow liquid"], 0.40, rng),
    ]

    # Organic chemistry
    closed += [
        _q("Organic chemistry", "Methane formula is…", "CH₄",
           ["C₂H₆", "C₂H₄", "CH₃"], 0.10, rng),
        _q("Organic chemistry", "Ethanol functional group is…", "−OH",
           ["−COOH", "−NH₂", "−CHO"], 0.20, rng),
        _q("Organic chemistry", "Alkanes have general formula…", "CₙH₂ₙ₊₂",
           ["CₙH₂ₙ", "CₙH₂ₙ₋₂", "CₙHₙ"], 0.30, rng),
        _q("Organic chemistry", "Benzene formula is…", "C₆H₆",
           ["C₆H₁₂", "C₆H₁₄", "C₅H₆"], 0.25, rng),
        _q("Organic chemistry", "Acetic acid is also called…", "Ethanoic acid",
           ["Methanoic acid", "Propanoic acid", "Citric acid"], 0.30, rng),
    ]

    # Solutions
    closed += [
        _q("Solutions", "Molarity is…", "Moles solute per liter of solution",
           ["Moles per kg solvent", "Mass percent", "Volume percent"], 0.20, rng),
        _q("Solutions", "Solubility usually increases with…", "Temperature (for most solids)",
           ["Pressure (for solids)", "Decreasing temperature", "Higher pH"], 0.30, rng),
        _q("Solutions", "Universal solvent is…", "Water",
           ["Ethanol", "Acetone", "Benzene"], 0.10, rng),
    ]

    # Gas laws
    closed += [
        _q("Gas laws", "Ideal gas law is…", "PV = nRT",
           ["P/V = nRT", "PV = mRT", "P + V = nRT"], 0.20, rng),
        _q("Gas laws", "STP temperature is…", "273 K",
           ["298 K", "100 K", "0 K"], 0.25, rng),
        _q("Gas laws", "At STP, 1 mol of ideal gas occupies…", "22.4 L",
           ["1 L", "12 L", "100 L"], 0.30, rng),
    ]

    open_q += [
        ("Atomic structure", "Number of protons in oxygen.", ["8"], 0.20),
        ("Periodic table", "Symbol of sodium.", ["Na"], 0.15),
        ("Chemical bonding", "Molecular formula of methane.", ["CH4"], 0.20),
        ("Stoichiometry", "Molar mass of NaCl (g/mol, integer).", ["58"], 0.30),
        ("Acids and bases", "pH of neutral water.", ["7"], 0.10),
        ("Redox reactions", "Oxidation state of H in HCl.", ["+1", "1"], 0.30),
        ("Organic chemistry", "Number of carbons in propane.", ["3"], 0.20),
        ("Solutions", "Molarity (M) of 1 mol in 2 L.", ["0.5"], 0.25),
        ("Gas laws", "Volume (L) of 2 mol ideal gas at STP.", ["44.8"], 0.35),
        ("Atomic structure", "Element with atomic number 1.", ["H", "Hydrogen"], 0.10),
    ]
    return closed, open_q


def gen_bio(rng: random.Random) -> tuple[list[ClosedRow], list[OpenRow]]:
    closed: list[ClosedRow] = []
    open_q: list[OpenRow] = []

    closed += [
        # Cell biology
        _q("Cell biology", "Powerhouse of the cell is…", "Mitochondria",
           ["Nucleus", "Ribosome", "Golgi apparatus"], 0.20, rng),
        _q("Cell biology", "Cell wall is found in…", "Plant cells",
           ["Animal cells", "Bacteria only", "Red blood cells"], 0.25, rng),
        _q("Cell biology", "DNA is mainly stored in the…", "Nucleus",
           ["Cytoplasm", "Mitochondria only", "Membrane"], 0.20, rng),
        _q("Cell biology", "Ribosomes are responsible for…", "Protein synthesis",
           ["Photosynthesis", "Respiration", "Digestion"], 0.25, rng),
        _q("Cell biology", "Cell membrane is mainly composed of…", "Phospholipid bilayer",
           ["Cellulose", "Chitin", "Lignin"], 0.30, rng),
        _q("Cell biology", "Site of photosynthesis is the…", "Chloroplast",
           ["Mitochondrion", "Vacuole", "Lysosome"], 0.20, rng),

        # Genetics
        _q("Genetics", "Mendel is known as the father of…", "Genetics",
           ["Evolution", "Anatomy", "Microbiology"], 0.20, rng),
        _q("Genetics", "DNA stands for…", "Deoxyribonucleic acid",
           ["Dinitric acid", "Diribonucleic acid", "Deuterium nucleic acid"], 0.20, rng),
        _q("Genetics", "Base pair: Adenine pairs with…", "Thymine",
           ["Cytosine", "Guanine", "Uracil"], 0.20, rng),
        _q("Genetics", "Base pair: Cytosine pairs with…", "Guanine",
           ["Adenine", "Thymine", "Uracil"], 0.20, rng),
        _q("Genetics", "Human somatic cells contain how many chromosomes?", "46",
           ["23", "44", "48"], 0.30, rng),
        _q("Genetics", "RNA contains which base instead of thymine?", "Uracil",
           ["Cytosine", "Adenine", "Guanine"], 0.30, rng),

        # Human anatomy
        _q("Human anatomy", "Largest organ in the human body is…", "Skin",
           ["Liver", "Brain", "Lungs"], 0.20, rng),
        _q("Human anatomy", "Heart has how many chambers?", "4",
           ["2", "3", "6"], 0.20, rng),
        _q("Human anatomy", "Oxygen is exchanged in the…", "Alveoli",
           ["Bronchi", "Trachea", "Pleura"], 0.30, rng),
        _q("Human anatomy", "Red blood cells carry oxygen using…", "Hemoglobin",
           ["Insulin", "Albumin", "Keratin"], 0.25, rng),
        _q("Human anatomy", "Bile is produced by the…", "Liver",
           ["Pancreas", "Kidney", "Spleen"], 0.30, rng),

        # Plants
        _q("Plants", "Photosynthesis produces oxygen and…", "Glucose",
           ["Starch only", "Carbon dioxide", "Water vapor"], 0.20, rng),
        _q("Plants", "Stomata regulate…", "Gas exchange",
           ["Water uptake from roots", "Nutrient transport", "Flower color"], 0.30, rng),
        _q("Plants", "Xylem transports…", "Water",
           ["Sugars", "Oxygen", "Hormones"], 0.30, rng),
        _q("Plants", "Phloem transports…", "Sugars",
           ["Water only", "Nitrogen", "Cellulose"], 0.30, rng),
        _q("Plants", "Chlorophyll is mainly which color?", "Green",
           ["Red", "Blue", "Yellow"], 0.10, rng),

        # Animals
        _q("Animals", "Cold-blooded animal example…", "Lizard",
           ["Whale", "Sparrow", "Human"], 0.30, rng),
        _q("Animals", "Mammals reproduce by…", "Giving live birth (mostly)",
           ["Laying eggs only", "Binary fission", "Spore formation"], 0.20, rng),
        _q("Animals", "Insects have how many legs?", "6",
           ["4", "8", "10"], 0.10, rng),

        # Evolution
        _q("Evolution", "Theory of natural selection was proposed by…", "Charles Darwin",
           ["Mendel", "Pasteur", "Lamarck"], 0.20, rng),
        _q("Evolution", "Fossils are evidence of…", "Evolution",
           ["Genetics only", "Photosynthesis", "Respiration"], 0.20, rng),
        _q("Evolution", "Vestigial organs suggest…", "Common ancestry",
           ["Spontaneous generation", "Equal fitness", "Genetic drift only"], 0.40, rng),

        # Ecology
        _q("Ecology", "Group of same species in an area is a…", "Population",
           ["Community", "Ecosystem", "Biome"], 0.25, rng),
        _q("Ecology", "Top of the food chain is a…", "Apex predator",
           ["Producer", "Decomposer", "Herbivore"], 0.20, rng),
        _q("Ecology", "Producers in an ecosystem are usually…", "Plants",
           ["Carnivores", "Decomposers", "Bacteria only"], 0.20, rng),

        # Microbiology
        _q("Microbiology", "Bacteria are which type of cell?", "Prokaryotic",
           ["Eukaryotic", "Multicellular", "Plant"], 0.30, rng),
        _q("Microbiology", "Penicillin was discovered by…", "Alexander Fleming",
           ["Louis Pasteur", "Robert Koch", "Charles Darwin"], 0.30, rng),
        _q("Microbiology", "Yeast is a…", "Fungus",
           ["Bacterium", "Virus", "Protist"], 0.25, rng),

        # Biochemistry
        _q("Biochemistry", "Building blocks of proteins are…", "Amino acids",
           ["Fatty acids", "Sugars", "Nucleotides"], 0.25, rng),
        _q("Biochemistry", "Building blocks of DNA are…", "Nucleotides",
           ["Amino acids", "Lipids", "Sugars"], 0.25, rng),
        _q("Biochemistry", "Enzymes are mostly…", "Proteins",
           ["Carbohydrates", "Lipids", "Nucleic acids"], 0.25, rng),
        _q("Biochemistry", "Glucose is a…", "Monosaccharide",
           ["Polysaccharide", "Disaccharide", "Lipid"], 0.25, rng),
    ]

    # Pad more with simple recall to ensure 50+ closed
    closed += [
        _q("Cell biology", "Animal cells contain a cell wall.", "False",
           ["True", "Only liver cells", "Only skin cells"], 0.20, rng),
        _q("Cell biology", "Lysosomes function as the cell's…", "Digestive system",
           ["Energy producer", "Storage tank", "DNA repository"], 0.30, rng),
        _q("Genetics", "A heterozygous genotype is…", "Aa",
           ["AA", "aa", "AB"], 0.30, rng),
        _q("Human anatomy", "Kidney filters…", "Blood",
           ["Air", "Lymph only", "Bile"], 0.20, rng),
        _q("Human anatomy", "Skeletal muscle is under…", "Voluntary control",
           ["Hormonal control only", "Autonomic control", "No control"], 0.30, rng),
        _q("Plants", "Roots primarily absorb…", "Water and minerals",
           ["Sunlight", "CO₂", "Oxygen"], 0.15, rng),
        _q("Ecology", "Carbon cycle involves…", "CO₂ exchange between life and atmosphere",
           ["Salt deposition", "Phosphorus runoff only", "Tectonic shifts"], 0.30, rng),
    ]

    open_q += [
        ("Cell biology", "Number of chromosomes in human somatic cells.", ["46"], 0.30),
        ("Genetics", "Base that pairs with Adenine in DNA.", ["T", "Thymine"], 0.20),
        ("Human anatomy", "Number of chambers in human heart.", ["4"], 0.20),
        ("Plants", "Gas produced by photosynthesis.", ["O2", "oxygen"], 0.20),
        ("Animals", "Number of legs on an insect.", ["6"], 0.10),
        ("Evolution", "Surname of the scientist who proposed natural selection.", ["Darwin"], 0.20),
        ("Ecology", "Word for total of all populations in an area.", ["community"], 0.30),
        ("Microbiology", "Type of organism that causes the flu.", ["virus"], 0.25),
        ("Biochemistry", "Building blocks of proteins.", ["amino acids"], 0.30),
        ("Cell biology", "Organelle responsible for ATP production.", ["mitochondria", "mitochondrion"], 0.25),
    ]

    return closed, open_q


def gen_history(rng: random.Random) -> tuple[list[ClosedRow], list[OpenRow]]:
    closed: list[ClosedRow] = []
    open_q: list[OpenRow] = []

    closed += [
        # Ancient
        _q("Ancient Uzbekistan", "Ancient Persian satrapy covering modern Uzbekistan was…", "Sogdiana",
           ["Lydia", "Babylonia", "Phoenicia"], 0.40, rng),
        _q("Ancient Uzbekistan", "Famous trade route through Uzbekistan was the…", "Silk Road",
           ["Spice Route", "Amber Road", "Tea Road"], 0.20, rng),
        _q("Ancient Uzbekistan", "Alexander the Great conquered Sogdiana around…", "329 BCE",
           ["100 CE", "1200 BCE", "500 CE"], 0.50, rng),
        _q("Ancient Uzbekistan", "Sogdians were famous as…", "Merchants",
           ["Sailors", "Astronomers", "Conquerors"], 0.40, rng),

        # Timurid
        _q("Timurid era", "Founder of the Timurid Empire was…", "Amir Temur",
           ["Babur", "Ulugh Beg", "Shaybani Khan"], 0.20, rng),
        _q("Timurid era", "Amir Temur was born in…", "1336",
           ["1206", "1450", "1483"], 0.30, rng),
        _q("Timurid era", "Capital of the Timurid Empire was…", "Samarkand",
           ["Bukhara", "Khiva", "Tashkent"], 0.20, rng),
        _q("Timurid era", "Ulugh Beg was famous for his work in…", "Astronomy",
           ["Music", "Trade", "Naval warfare"], 0.30, rng),
        _q("Timurid era", "The Registan ensemble is located in…", "Samarkand",
           ["Bukhara", "Tashkent", "Khiva"], 0.25, rng),

        # Khanates
        _q("Khanates period", "Three Uzbek khanates in 18th–19th century were Bukhara, Khiva, and…", "Kokand",
           ["Tashkent", "Andijan", "Margilan"], 0.30, rng),
        _q("Khanates period", "Bukhara khanate's center was…", "Bukhara city",
           ["Kokand", "Khiva", "Tashkent"], 0.20, rng),
        _q("Khanates period", "Khiva khanate ruled over part of…", "Khorezm region",
           ["Ferghana valley", "Pamir mountains", "Caspian shore"], 0.30, rng),

        # Russian Empire
        _q("Russian Empire", "Russian Empire annexed the Kokand Khanate in…", "1876",
           ["1700", "1900", "1810"], 0.45, rng),
        _q("Russian Empire", "Russian general who conquered Tashkent in 1865 was…", "Chernyaev",
           ["Skobelev", "Suvorov", "Kornilov"], 0.55, rng),

        # Soviet era
        _q("Soviet era", "Uzbek SSR was established in…", "1924",
           ["1917", "1936", "1945"], 0.40, rng),
        _q("Soviet era", "First president of Uzbek SSR (post-1990 reform) was…", "Islam Karimov",
           ["Sharaf Rashidov", "Yahyo Babayev", "Ergash Khodjayev"], 0.40, rng),
        _q("Soviet era", "Sharaf Rashidov was first secretary of Uzbek SSR…", "in the 1960s–80s",
           ["in the 1920s", "in the 1990s", "in WWII only"], 0.50, rng),

        # Independence
        _q("Independence", "Uzbekistan declared independence on…", "September 1, 1991",
           ["August 8, 1991", "December 25, 1991", "March 21, 1992"], 0.20, rng),
        _q("Independence", "Capital of independent Uzbekistan is…", "Tashkent",
           ["Samarkand", "Bukhara", "Nukus"], 0.10, rng),
        _q("Independence", "First president of independent Uzbekistan was…", "Islam Karimov",
           ["Shavkat Mirziyoyev", "Abdulla Aripov", "Nuriddin Mukhitdinov"], 0.20, rng),
        _q("Independence", "Constitution of Uzbekistan was adopted in…", "1992",
           ["1991", "1995", "2002"], 0.40, rng),

        # World history
        _q("World history", "World War II ended in…", "1945",
           ["1939", "1918", "1941"], 0.10, rng),
        _q("World history", "Great French Revolution began in…", "1789",
           ["1789 BCE", "1815", "1848"], 0.20, rng),
        _q("World history", "Berlin Wall fell in…", "1989",
           ["1991", "1985", "1979"], 0.30, rng),
        _q("World history", "USSR collapsed in…", "1991",
           ["1985", "1989", "1993"], 0.20, rng),

        # Cultural figures
        _q("Cultural figures", "Author of \"Boburnoma\" was…", "Babur",
           ["Alisher Navoiy", "Furqat", "Cholpon"], 0.30, rng),
        _q("Cultural figures", "Alisher Navoiy was a famous…", "Poet",
           ["General", "Mathematician", "Astronomer"], 0.20, rng),
        _q("Cultural figures", "Hamza Hakimzoda Niyozi is associated with…", "Modern Uzbek literature",
           ["Classical poetry", "Mongol period", "Medieval astronomy"], 0.50, rng),
        _q("Cultural figures", "Al-Khwarizmi is famous for work in…", "Mathematics (algebra)",
           ["Surgery", "Astronomy only", "Poetry"], 0.30, rng),

        # Modern Uzbekistan
        _q("Modern Uzbekistan", "Current president of Uzbekistan (since 2016) is…", "Shavkat Mirziyoyev",
           ["Islam Karimov", "Abdulla Aripov", "Erkin Vohidov"], 0.20, rng),
        _q("Modern Uzbekistan", "Aral Sea problem is mainly a…", "Environmental disaster",
           ["Political dispute only", "Cultural shift", "Economic boom"], 0.30, rng),
        _q("Modern Uzbekistan", "Currency of Uzbekistan is the…", "Sum (UZS)",
           ["Tenge", "Ruble", "Manat"], 0.20, rng),
    ]

    # Pad to >50
    closed += [
        _q("Timurid era", "Amir Temur defeated which Ottoman sultan?", "Bayezid I",
           ["Suleiman I", "Mehmed II", "Selim I"], 0.50, rng),
        _q("Ancient Uzbekistan", "Zoroastrianism was widespread in pre-Islamic…", "Central Asia",
           ["East Africa", "Iberia", "Scandinavia"], 0.40, rng),
        _q("World history", "American Declaration of Independence was signed in…", "1776",
           ["1789", "1812", "1776 BCE"], 0.20, rng),
        _q("Khanates period", "Slavery in Khiva khanate was abolished in…", "1873",
           ["1700", "1900", "1865"], 0.60, rng),
        _q("Cultural figures", "Ibn Sina (Avicenna) was a famous…", "Physician/philosopher",
           ["Painter", "Poet only", "Sailor"], 0.25, rng),
        _q("Modern Uzbekistan", "Member of which regional union is Uzbekistan?", "Shanghai Cooperation Organisation",
           ["NATO", "EU", "ASEAN"], 0.40, rng),
        _q("Independence", "Capital was moved from Samarkand to Tashkent in…", "1930",
           ["1991", "1865", "1924"], 0.50, rng),
    ]

    open_q += [
        ("Timurid era", "Founder of the Timurid Empire (last name).", ["Temur", "Timur"], 0.20),
        ("Independence", "Year Uzbekistan gained independence.", ["1991"], 0.20),
        ("World history", "Year WWII ended.", ["1945"], 0.10),
        ("Ancient Uzbekistan", "Famous trade route through Central Asia (2 words).", ["Silk Road"], 0.20),
        ("Cultural figures", "Author of Boburnoma.", ["Babur"], 0.30),
        ("Modern Uzbekistan", "Currency of Uzbekistan (3 letters).", ["UZS", "sum"], 0.20),
        ("Khanates period", "Last khan to fall under Russian rule's khanate (3 names possible).", ["Kokand", "Khiva", "Bukhara"], 0.45),
        ("Soviet era", "Year Uzbek SSR was established.", ["1924"], 0.40),
        ("Timurid era", "Famous astronomer-grandson of Amir Temur.", ["Ulugh Beg", "Ulug'bek"], 0.30),
        ("Independence", "Day in September when Independence is celebrated.", ["1"], 0.20),
    ]

    return closed, open_q


def gen_geog(rng: random.Random) -> tuple[list[ClosedRow], list[OpenRow]]:
    closed: list[ClosedRow] = []
    open_q: list[OpenRow] = []

    # Uzbekistan regions (12 viloyats)
    regions = [
        ("Tashkent region", "Tashkent"),
        ("Samarkand region", "Samarkand"),
        ("Bukhara region", "Bukhara"),
        ("Andijan region", "Andijan"),
        ("Ferghana region", "Ferghana"),
        ("Namangan region", "Namangan"),
        ("Khorezm region", "Urgench"),
        ("Surkhandarya region", "Termez"),
        ("Kashkadarya region", "Karshi"),
        ("Navoiy region", "Navoiy"),
        ("Jizzakh region", "Jizzakh"),
        ("Sirdaryo region", "Guliston"),
    ]
    for region, capital in regions:
        closed.append(_q("Uzbekistan regions",
                         f"Administrative center of {region} is…",
                         capital, [r[1] for r in regions if r[1] != capital][:3],
                         0.30, rng))

    closed += [
        _q("Physical geography", "Highest mountain range bordering Uzbekistan is…", "Tian Shan",
           ["Caucasus", "Ural", "Atlas"], 0.30, rng),
        _q("Physical geography", "Largest desert in Central Asia is…", "Karakum",
           ["Gobi", "Sahara", "Patagonian"], 0.30, rng),
        _q("Physical geography", "Plateau between Amu Darya and Syr Darya is the…", "Kyzylkum desert",
           ["Pamir plateau", "Tibet plateau", "Ustyurt plateau"], 0.50, rng),
        _q("Rivers and lakes", "Longest river in Uzbekistan is…", "Amu Darya",
           ["Syr Darya", "Zarafshan", "Chirchik"], 0.20, rng),
        _q("Rivers and lakes", "Aral Sea is shared between Uzbekistan and…", "Kazakhstan",
           ["Turkmenistan", "Kyrgyzstan", "Tajikistan"], 0.30, rng),
        _q("Rivers and lakes", "River flowing through Tashkent is the…", "Chirchik",
           ["Amu Darya", "Syr Darya", "Zarafshan"], 0.35, rng),
        _q("Climate", "Climate of Uzbekistan is mainly…", "Continental arid",
           ["Tropical", "Polar", "Maritime"], 0.30, rng),
        _q("Climate", "Hottest month in Tashkent is usually…", "July",
           ["January", "April", "October"], 0.25, rng),
        _q("Continents", "Largest continent is…", "Asia",
           ["Africa", "North America", "Antarctica"], 0.20, rng),
        _q("Continents", "Smallest continent is…", "Australia",
           ["Antarctica", "Europe", "South America"], 0.20, rng),
        _q("Continents", "Uzbekistan is on which continent?", "Asia",
           ["Europe", "Africa", "Antarctica"], 0.10, rng),
        _q("Population", "Most populous country in the world is…", "India",
           ["China", "USA", "Indonesia"], 0.40, rng),
        _q("Population", "Capital with largest population in Central Asia is…", "Tashkent",
           ["Almaty", "Bishkek", "Dushanbe"], 0.40, rng),
        _q("Natural resources", "Uzbekistan is a top world producer of…", "Cotton",
           ["Coffee", "Rubber", "Cocoa"], 0.20, rng),
        _q("Natural resources", "Major mineral exported by Uzbekistan is…", "Gold",
           ["Silver only", "Platinum", "Diamonds"], 0.30, rng),
        _q("Natural resources", "Largest natural gas field in Uzbekistan is…", "Gazli",
           ["Pamir", "Surgut", "Kursk"], 0.55, rng),
        _q("Capitals & countries", "Capital of Kazakhstan is…", "Astana",
           ["Almaty", "Bishkek", "Ashgabat"], 0.30, rng),
        _q("Capitals & countries", "Capital of Kyrgyzstan is…", "Bishkek",
           ["Astana", "Tashkent", "Dushanbe"], 0.30, rng),
        _q("Capitals & countries", "Capital of Tajikistan is…", "Dushanbe",
           ["Khujand", "Astana", "Bishkek"], 0.30, rng),
        _q("Capitals & countries", "Capital of Turkmenistan is…", "Ashgabat",
           ["Mary", "Tashkent", "Bishkek"], 0.30, rng),
        _q("Cartography", "Lines of longitude measure…", "East-west position",
           ["North-south position", "Altitude", "Climate"], 0.30, rng),
        _q("Cartography", "Equator is at latitude…", "0°",
           ["90° N", "180°", "23.5° N"], 0.20, rng),
        _q("Cartography", "Prime meridian passes through…", "Greenwich",
           ["Paris", "Moscow", "New York"], 0.30, rng),
    ]

    # Pad to >50
    closed += [
        _q("Physical geography", "Caspian Sea borders Uzbekistan.", "False",
           ["True", "Partially", "Through Khorezm"], 0.30, rng),
        _q("Uzbekistan regions", "Total number of viloyats in Uzbekistan is…", "12",
           ["10", "14", "8"], 0.30, rng),
        _q("Rivers and lakes", "Source of the Amu Darya is in the…", "Pamir mountains",
           ["Tian Shan", "Hindu Kush only", "Karakum"], 0.50, rng),
        _q("Climate", "Average annual precipitation in much of Uzbekistan is…", "Low",
           ["Very high", "Above 2000 mm", "Tropical-level"], 0.40, rng),
        _q("Capitals & countries", "Uzbekistan is doubly landlocked, sharing borders with…", "5 countries",
           ["3 countries", "4 countries", "6 countries"], 0.45, rng),
    ]

    open_q += [
        ("Uzbekistan regions", "Capital city of Uzbekistan.", ["Tashkent"], 0.10),
        ("Uzbekistan regions", "Number of viloyats in Uzbekistan.", ["12"], 0.30),
        ("Rivers and lakes", "Longest river of Uzbekistan (2 words).", ["Amu Darya"], 0.20),
        ("Climate", "Hottest month in Tashkent.", ["July"], 0.25),
        ("Continents", "Continent Uzbekistan is part of.", ["Asia"], 0.10),
        ("Natural resources", "Top agricultural export of Uzbekistan.", ["cotton"], 0.20),
        ("Capitals & countries", "Capital of Tajikistan.", ["Dushanbe"], 0.30),
        ("Cartography", "Imaginary line of 0° latitude.", ["equator"], 0.20),
        ("Population", "Most populous country in the world.", ["India"], 0.40),
        ("Physical geography", "Largest desert in Central Asia.", ["Karakum"], 0.30),
    ]

    return closed, open_q


def gen_uzb_lit(rng: random.Random) -> tuple[list[ClosedRow], list[OpenRow]]:
    closed: list[ClosedRow] = []
    open_q: list[OpenRow] = []

    closed += [
        # Authors / classical lit
        _q("Authors", "Author of \"Xamsa\" is…", "Alisher Navoiy",
           ["Furqat", "Cholpon", "Babur"], 0.25, rng),
        _q("Authors", "Mirzo Ulug'bek is famous as a…", "Ruler and astronomer",
           ["Poet only", "Painter", "Sailor"], 0.30, rng),
        _q("Authors", "Bobur is famous as the author of…", "Boburnoma",
           ["Mahbub ul-qulub", "Xamsa", "Qutadg'u Bilig"], 0.30, rng),
        _q("Authors", "Cholpon was a prominent 20th-century…", "Poet",
           ["Painter", "Composer", "Astronomer"], 0.30, rng),
        _q("Authors", "Abdulla Qodiriy is the author of…", "O'tkan kunlar",
           ["Boburnoma", "Sarob", "Qutlug' qon"], 0.35, rng),
        _q("Authors", "Oybek wrote the historical novel…", "Navoiy",
           ["O'tkan kunlar", "Qutlug' qon", "Mehrobdan chayon"], 0.40, rng),
        _q("Authors", "Erkin Vohidov was a famous…", "Poet",
           ["Painter", "Astronomer", "Scientist"], 0.30, rng),
        _q("Authors", "Author of \"Mehrobdan chayon\" is…", "Abdulla Qodiriy",
           ["Cholpon", "Aybek", "Furqat"], 0.45, rng),

        # Classical literature
        _q("Classical literature", "Alisher Navoiy lived in the…", "15th century",
           ["12th century", "18th century", "20th century"], 0.30, rng),
        _q("Classical literature", "\"Xamsa\" consists of…", "Five poems",
           ["Three poems", "Seven poems", "Ten poems"], 0.40, rng),
        _q("Classical literature", "Yusuf Has Hajib wrote…", "Qutadg'u Bilig",
           ["Boburnoma", "Xamsa", "Devoni lug'otit turk"], 0.50, rng),
        _q("Classical literature", "Mahmud Kashgari wrote…", "Devoni lug'otit turk",
           ["Boburnoma", "Xamsa", "Qutadg'u Bilig"], 0.45, rng),

        # Modern literature
        _q("Modern literature", "\"O'tkan kunlar\" was published in…", "1922",
           ["1900", "1950", "1989"], 0.50, rng),
        _q("Modern literature", "Theme of \"O'tkan kunlar\" centers on…", "Jadid era Uzbek life",
           ["Soviet industrialization", "Mongol invasions", "Ancient Sogdiana"], 0.45, rng),

        # Poetry
        _q("Poetry", "Ghazal is a form of…", "Lyric poetry",
           ["Epic prose", "Drama", "Novel"], 0.30, rng),
        _q("Poetry", "Rubai contains how many lines?", "4",
           ["2", "8", "14"], 0.30, rng),
        _q("Poetry", "Aruz is a system of…", "Poetic meter",
           ["Grammar", "Punctuation", "Music notation"], 0.40, rng),

        # Grammar
        _q("Grammar", "Number of vowels in Uzbek (Cyrillic-era) is…", "6",
           ["5", "7", "10"], 0.30, rng),
        _q("Grammar", "Word order of typical Uzbek sentence is…", "Subject-Object-Verb",
           ["Subject-Verb-Object", "Verb-Subject-Object", "Object-Subject-Verb"], 0.30, rng),
        _q("Grammar", "Uzbek belongs to which language family?", "Turkic",
           ["Slavic", "Indo-European", "Semitic"], 0.20, rng),
        _q("Grammar", "Uzbek script today is mainly…", "Latin",
           ["Arabic only", "Cyrillic only", "Greek"], 0.25, rng),
        _q("Grammar", "Plural suffix in Uzbek is…", "-lar",
           ["-da", "-ni", "-ga"], 0.25, rng),

        # Morphology
        _q("Morphology", "Possessive suffix for \"my\" in Uzbek is…", "-(i)m",
           ["-ing", "-i", "-imiz"], 0.40, rng),
        _q("Morphology", "Uzbek is an agglutinative language, meaning it uses…", "Suffix chaining",
           ["Tone for meaning", "Prefix chaining", "Inflection with vowel mutation"], 0.40, rng),
        _q("Morphology", "Tense suffix -di indicates…", "Past tense",
           ["Future", "Present continuous", "Conditional"], 0.30, rng),

        # Phonetics
        _q("Phonetics", "Vowel harmony in Uzbek (historically) groups vowels by…", "Front/back",
           ["High/low only", "Round/unround only", "Voiced/unvoiced"], 0.45, rng),

        # Syntax
        _q("Syntax", "Adjective usually appears…", "Before the noun",
           ["After the verb", "After the noun", "Between subjects"], 0.30, rng),
        _q("Syntax", "Verb in Uzbek typically appears…", "At the end",
           ["At the beginning", "After subject and before object", "Anywhere"], 0.30, rng),

        # Vocabulary
        _q("Vocabulary", "Word \"kitob\" means…", "Book",
           ["Tree", "Door", "City"], 0.10, rng),
        _q("Vocabulary", "Word \"maktab\" means…", "School",
           ["Hospital", "Library", "House"], 0.10, rng),
        _q("Vocabulary", "Word \"ona\" means…", "Mother",
           ["Father", "Sister", "Friend"], 0.10, rng),
        _q("Vocabulary", "Plural of \"talaba\" is…", "talabalar",
           ["talab", "talabani", "talabaga"], 0.20, rng),
    ]

    # Pad to >50
    closed += [
        _q("Authors", "Hamid Olimjon was a…", "Poet",
           ["Painter", "Mathematician", "Composer"], 0.30, rng),
        _q("Classical literature", "Author of \"Mahbub ul-qulub\" is…", "Alisher Navoiy",
           ["Babur", "Furqat", "Cholpon"], 0.40, rng),
        _q("Modern literature", "Pirimqul Qodirov wrote the historical novel…", "Yulduzli tunlar",
           ["O'tkan kunlar", "Sarob", "Boburnoma"], 0.50, rng),
        _q("Poetry", "Quatrain stanza is also called…", "Murabba/rubai",
           ["Ghazal", "Sonnet", "Haiku"], 0.30, rng),
        _q("Grammar", "Definite accusative suffix in Uzbek is…", "-ni",
           ["-da", "-ga", "-dan"], 0.30, rng),
        _q("Vocabulary", "\"Yaxshi\" means…", "Good",
           ["Bad", "Big", "Quiet"], 0.10, rng),
        _q("Vocabulary", "\"Salom\" means…", "Hello",
           ["Goodbye", "Thanks", "Yes"], 0.10, rng),
    ]

    open_q += [
        ("Authors", "Author of Boburnoma.", ["Babur"], 0.20),
        ("Authors", "Author of O'tkan kunlar.", ["Abdulla Qodiriy", "Qodiriy"], 0.30),
        ("Classical literature", "Number of poems in Navoiy's Xamsa.", ["5"], 0.30),
        ("Modern literature", "Year O'tkan kunlar was first published.", ["1922"], 0.50),
        ("Poetry", "Lines in a rubai.", ["4"], 0.20),
        ("Grammar", "Word order of a typical Uzbek sentence (3 letters).", ["SOV"], 0.30),
        ("Vocabulary", "English word for 'maktab'.", ["school"], 0.10),
        ("Vocabulary", "English word for 'ona'.", ["mother"], 0.10),
        ("Morphology", "Plural suffix in Uzbek.", ["lar", "-lar"], 0.30),
        ("Syntax", "Position of the verb in Uzbek sentence (last/first/middle).", ["last"], 0.25),
    ]

    return closed, open_q


def gen_rus_lit(rng: random.Random) -> tuple[list[ClosedRow], list[OpenRow]]:
    closed: list[ClosedRow] = []
    open_q: list[OpenRow] = []

    closed += [
        # Authors
        _q("Authors", "Author of \"War and Peace\" is…", "Tolstoy",
           ["Dostoevsky", "Chekhov", "Turgenev"], 0.20, rng),
        _q("Authors", "Author of \"Crime and Punishment\" is…", "Dostoevsky",
           ["Tolstoy", "Pushkin", "Gogol"], 0.20, rng),
        _q("Authors", "Author of \"Eugene Onegin\" is…", "Pushkin",
           ["Lermontov", "Dostoevsky", "Tolstoy"], 0.25, rng),
        _q("Authors", "Author of \"A Hero of Our Time\" is…", "Lermontov",
           ["Pushkin", "Gogol", "Turgenev"], 0.35, rng),
        _q("Authors", "Author of \"Dead Souls\" is…", "Gogol",
           ["Tolstoy", "Bunin", "Chekhov"], 0.30, rng),
        _q("Authors", "Author of \"Fathers and Sons\" is…", "Turgenev",
           ["Tolstoy", "Dostoevsky", "Bunin"], 0.30, rng),
        _q("Authors", "Author of \"The Cherry Orchard\" is…", "Chekhov",
           ["Tolstoy", "Pushkin", "Lermontov"], 0.30, rng),
        _q("Authors", "Author of \"The Master and Margarita\" is…", "Bulgakov",
           ["Sholokhov", "Pasternak", "Solzhenitsyn"], 0.30, rng),
        _q("Authors", "Author of \"Doctor Zhivago\" is…", "Pasternak",
           ["Bulgakov", "Sholokhov", "Akhmatova"], 0.35, rng),
        _q("Authors", "Anna Akhmatova was a famous…", "Poet",
           ["Painter", "Composer", "Scientist"], 0.20, rng),

        # 19th century
        _q("19th century lit", "Pushkin's main work in verse is…", "Eugene Onegin",
           ["Dead Souls", "The Idiot", "Resurrection"], 0.25, rng),
        _q("19th century lit", "Gogol is best known for…", "Satirical realism",
           ["Romantic poetry", "Symbolism", "Avant-garde drama"], 0.40, rng),
        _q("19th century lit", "\"The Idiot\" was written by…", "Dostoevsky",
           ["Tolstoy", "Pushkin", "Lermontov"], 0.30, rng),
        _q("19th century lit", "Pushkin died in…", "1837",
           ["1799", "1857", "1825"], 0.40, rng),

        # 20th century
        _q("20th century lit", "Sholokhov wrote about…", "Don Cossacks",
           ["Aristocratic salons", "Pirates", "Industrial workers"], 0.30, rng),
        _q("20th century lit", "Solzhenitsyn's \"One Day in the Life of Ivan Denisovich\" depicts…", "A Soviet labor camp day",
           ["A village wedding", "Civil war battles", "Naval expedition"], 0.25, rng),
        _q("20th century lit", "Soviet literary doctrine after 1934 was…", "Socialist realism",
           ["Symbolism", "Futurism", "Romanticism"], 0.40, rng),

        # Poetry
        _q("Poetry", "Number of feet in iambic pentameter is…", "5",
           ["4", "6", "8"], 0.40, rng),
        _q("Poetry", "Boris Pasternak won the Nobel Prize in…", "1958",
           ["1948", "1968", "1933"], 0.50, rng),
        _q("Poetry", "Mayakovsky is associated with…", "Futurism",
           ["Symbolism", "Acmeism", "Imagism"], 0.40, rng),

        # Grammar
        _q("Grammar", "Russian has how many grammatical cases?", "6",
           ["4", "5", "8"], 0.30, rng),
        _q("Grammar", "Russian alphabet has how many letters?", "33",
           ["26", "30", "36"], 0.25, rng),
        _q("Grammar", "Russian belongs to which language family?", "Slavic (Indo-European)",
           ["Turkic", "Uralic", "Semitic"], 0.20, rng),
        _q("Grammar", "Russian noun has gender…", "Masculine, feminine, neuter",
           ["Only masculine and feminine", "Animate vs inanimate only", "Genderless"], 0.20, rng),
        _q("Grammar", "Russian script is…", "Cyrillic",
           ["Latin", "Arabic", "Greek"], 0.10, rng),

        # Morphology
        _q("Morphology", "Russian verbs distinguish two main…", "Aspects",
           ["Genders", "Cases", "Voices"], 0.40, rng),
        _q("Morphology", "Perfective aspect in Russian typically denotes…", "Completed action",
           ["Ongoing action", "Future tense only", "Habit"], 0.30, rng),
        _q("Morphology", "Nominative case is used for the…", "Subject",
           ["Direct object", "Indirect object", "Possessor"], 0.30, rng),
        _q("Morphology", "Russian noun ending -а/-я is typically…", "Feminine",
           ["Masculine", "Neuter", "Plural only"], 0.30, rng),

        # Phonetics
        _q("Phonetics", "Russian \"ё\" is always…", "Stressed",
           ["Unstressed", "Silent", "Optional"], 0.30, rng),
        _q("Phonetics", "Voicing assimilation in Russian works…", "Right-to-left",
           ["Left-to-right", "Both directions equally", "Doesn't occur"], 0.50, rng),

        # Syntax
        _q("Syntax", "Default Russian word order is…", "Subject-Verb-Object",
           ["Subject-Object-Verb", "Verb-Subject-Object", "Object-Verb-Subject"], 0.30, rng),
        _q("Syntax", "Russian sentences can omit…", "Subject pronouns (often)",
           ["All verbs", "All nouns", "All articles (there are none)"], 0.30, rng),

        # Vocabulary
        _q("Vocabulary", "Russian word \"книга\" means…", "Book",
           ["Tree", "Hand", "Sky"], 0.10, rng),
        _q("Vocabulary", "Russian word \"школа\" means…", "School",
           ["Library", "Hospital", "Office"], 0.10, rng),
        _q("Vocabulary", "Russian word \"мама\" means…", "Mom",
           ["Aunt", "Sister", "Friend"], 0.10, rng),
    ]

    # Pad to >50
    closed += [
        _q("19th century lit", "Russian novel about Napoleonic Wars is…", "War and Peace",
           ["Anna Karenina", "Crime and Punishment", "Idiot"], 0.20, rng),
        _q("Authors", "Pen name of Anton Pavlovich was…", "Chekhov",
           ["Tolstoy", "Bulgakov", "Gogol"], 0.10, rng),
        _q("Modern literature", "\"Quiet Don\" Nobel-winning author…", "Sholokhov",
           ["Pasternak", "Bulgakov", "Bunin"], 0.40, rng),
        _q("Poetry", "Form with 14 lines is a…", "Sonnet",
           ["Ghazal", "Rubai", "Haiku"], 0.30, rng),
        _q("Grammar", "Soft sign in Russian (Ь) marks…", "Palatalization",
           ["Stress", "Vowel length", "Plural"], 0.40, rng),
        _q("Vocabulary", "Russian word \"да\" means…", "Yes",
           ["No", "Maybe", "Always"], 0.10, rng),
        _q("Vocabulary", "Russian word \"спасибо\" means…", "Thank you",
           ["Hello", "Goodbye", "Sorry"], 0.10, rng),
        _q("Vocabulary", "Russian word \"вода\" means…", "Water",
           ["Fire", "Stone", "Bread"], 0.15, rng),
        _q("Vocabulary", "Russian word \"дом\" means…", "House",
           ["Tree", "Road", "Window"], 0.10, rng),
        _q("19th century lit", "Author of the play \"The Government Inspector\" is…", "Gogol",
           ["Chekhov", "Pushkin", "Tolstoy"], 0.30, rng),
        _q("20th century lit", "Sholokhov won the Nobel Prize in literature in…", "1965",
           ["1958", "1933", "1970"], 0.50, rng),
        _q("Authors", "Anna Akhmatova's main genre was…", "Poetry",
           ["Drama", "Historical novel", "Essay"], 0.20, rng),
        _q("Grammar", "Russian noun ending -о/-е is typically…", "Neuter",
           ["Masculine", "Feminine", "Common"], 0.40, rng),
        _q("Morphology", "Genitive case in Russian often denotes…", "Possession or absence",
           ["Subject of sentence", "Direct object only", "Location only"], 0.40, rng),
    ]

    open_q += [
        ("Authors", "Author of War and Peace.", ["Tolstoy"], 0.20),
        ("Authors", "Author of Crime and Punishment.", ["Dostoevsky"], 0.20),
        ("19th century lit", "Year Pushkin died.", ["1837"], 0.40),
        ("20th century lit", "Surname of Master and Margarita author.", ["Bulgakov"], 0.30),
        ("Grammar", "Number of cases in Russian grammar.", ["6"], 0.30),
        ("Grammar", "Number of letters in the Russian alphabet.", ["33"], 0.25),
        ("Poetry", "Number of lines in a sonnet.", ["14"], 0.30),
        ("Vocabulary", "English word for 'книга'.", ["book"], 0.10),
        ("Vocabulary", "English word for 'школа'.", ["school"], 0.10),
        ("Morphology", "Aspect of perfective verbs (completed/ongoing).", ["completed"], 0.30),
    ]

    return closed, open_q


SUBJECT_GENERATORS = {
    SubjectCode.MATH: gen_math,
    SubjectCode.PHYS: gen_physics,
    SubjectCode.CHEM: gen_chem,
    SubjectCode.BIO: gen_bio,
    SubjectCode.HIST: gen_history,
    SubjectCode.GEOG: gen_geog,
    SubjectCode.UZB_LIT: gen_uzb_lit,
    SubjectCode.RUS_LIT: gen_rus_lit,
}


# ─────────────────────────────────────────────────────────────────────────────
# Persistence layer (idempotent)
# ─────────────────────────────────────────────────────────────────────────────

async def _ensure_topic(db, subject_id, plan: dict, order_index: int) -> Topic:
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
        order_index=order_index,
        name_uz=plan["name_uz"],
        name_ru=plan["name_ru"],
        name_en=plan["name_en"],
        weight=Decimal(str(plan["weight"])),
    )
    db.add(topic)
    await db.flush()
    return topic


_SLUG_COLLISIONS: set[str] = set()


def _unique_question_slug(base: str, subject_code: str, idx: int) -> str:
    raw = f"{subject_code.lower()}-{idx:03d}-{base}"
    slug = slugify(raw)[:78]
    # Avoid collisions across reruns of generator (deterministic suffix)
    if slug in _SLUG_COLLISIONS:
        slug = slugify(f"{raw}-{idx}")[:78]
    _SLUG_COLLISIONS.add(slug)
    return slug


async def _ensure_question(
    db,
    *,
    subject_id,
    subject_code: str,
    topic_id,
    body_en: str,
    qtype: QuestionType,
    options: dict | None,
    correct_answer,
    difficulty: float,
    points: float,
    suitable_for_battle: bool,
    idx: int,
) -> bool:
    slug = _unique_question_slug(body_en, subject_code, idx)
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
        difficulty=Decimal(str(round(difficulty, 3))),
        suitable_for_battle=suitable_for_battle,
        source_tier=3,
        source_note="hackathon-seed-v2",
    )
    db.add(q)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────

async def seed_subject(db, subject: Subject, gen) -> dict:
    rng = random.Random(hash(subject.code.value) & 0xFFFFFFFF)
    # Topics
    plans = TOPIC_PLANS[subject.code]
    topic_map: dict[str, Topic] = {}
    for i, plan in enumerate(plans):
        topic = await _ensure_topic(db, subject.id, plan, i)
        topic_map[plan["name_en"]] = topic
    await db.commit()

    # Generate pool — many closed + some open
    closed_pool, open_pool = gen(rng)

    # Battle pool: 50 closed (first 50, varied difficulty)
    battle_pool = closed_pool[:50]
    # Study pool: 35 closed (50–85 if available, else fill from start) + 10 open
    study_closed = closed_pool[50:85] if len(closed_pool) > 50 else []
    if len(study_closed) < 35:
        # Reuse extra closed items beyond 50 plus tail of closed pool
        study_closed = closed_pool[max(0, len(closed_pool) - 35):]
    study_open = open_pool[:10]
    # Final padding to reach desired counts
    while len(battle_pool) < 50 and len(closed_pool) > 0:
        battle_pool.append(closed_pool[len(battle_pool) % len(closed_pool)])
    while len(study_closed) < 35 and len(closed_pool) > 0:
        study_closed.append(closed_pool[(len(study_closed) + 7) % len(closed_pool)])
    while len(study_open) < 10 and len(open_pool) > 0:
        study_open.append(open_pool[len(study_open) % len(open_pool)])

    counters = {"battle": 0, "closed": 0, "open": 0, "skipped": 0}

    # Persist battle questions (suitable_for_battle = True)
    for i, (topic_name, body, options, correct, diff) in enumerate(battle_pool):
        topic = topic_map.get(topic_name)
        if not topic:
            counters["skipped"] += 1
            continue
        created = await _ensure_question(
            db,
            subject_id=subject.id,
            subject_code=subject.code.value,
            topic_id=topic.id,
            body_en=body,
            qtype=QuestionType.CLOSED,
            options=options,
            correct_answer=correct,
            difficulty=diff,
            points=2.0,
            suitable_for_battle=True,
            idx=i,
        )
        if created:
            counters["battle"] += 1

    # Persist study-closed (suitable_for_battle = False)
    for i, (topic_name, body, options, correct, diff) in enumerate(study_closed):
        topic = topic_map.get(topic_name)
        if not topic:
            counters["skipped"] += 1
            continue
        created = await _ensure_question(
            db,
            subject_id=subject.id,
            subject_code=subject.code.value,
            topic_id=topic.id,
            body_en=body,
            qtype=QuestionType.CLOSED,
            options=options,
            correct_answer=correct,
            difficulty=diff,
            points=2.2,
            suitable_for_battle=False,
            idx=1000 + i,
        )
        if created:
            counters["closed"] += 1

    # Persist study-open
    for i, (topic_name, body, accepted, diff) in enumerate(study_open):
        topic = topic_map.get(topic_name)
        if not topic:
            counters["skipped"] += 1
            continue
        created = await _ensure_question(
            db,
            subject_id=subject.id,
            subject_code=subject.code.value,
            topic_id=topic.id,
            body_en=body,
            qtype=QuestionType.OPEN_A,
            options=None,
            correct_answer=accepted,
            difficulty=diff,
            points=3.2,
            suitable_for_battle=False,
            idx=2000 + i,
        )
        if created:
            counters["open"] += 1

    await db.commit()
    return counters


async def seed() -> None:
    async with async_session_factory() as db:
        subjects = (
            await db.execute(select(Subject).order_by(Subject.order_index))
        ).scalars().all()
        if not subjects:
            print("⚠  Subjects table is empty. Run scripts/seed_subjects.py first.")
            return

        grand_total = {"battle": 0, "closed": 0, "open": 0}
        for subj in subjects:
            gen = SUBJECT_GENERATORS.get(subj.code)
            if not gen:
                print(f"⏭  {subj.code.value} — no generator defined, skipping")
                continue
            counts = await seed_subject(db, subj, gen)
            for k in ("battle", "closed", "open"):
                grand_total[k] += counts[k]
            print(
                f"✅ {subj.code.value:<8s} "
                f"battle +{counts['battle']:>2d} | "
                f"study closed +{counts['closed']:>2d} | "
                f"open +{counts['open']:>2d}"
            )

        print(
            "\n— Totals — "
            f"battle: {grand_total['battle']} | "
            f"study closed: {grand_total['closed']} | "
            f"open: {grand_total['open']}"
        )


if __name__ == "__main__":
    asyncio.run(seed())
