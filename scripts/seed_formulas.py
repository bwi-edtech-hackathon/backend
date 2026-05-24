"""Seed the `formulas` table from the curated MVP set.

Each row carries:
  * the Unicode `expression` that the right-rail formula sheet renders
    (e.g. "D = b² − 4ac"), and
  * an optional `latex` form fed to the chat coach so Gemini matches
    notation when citing a formula.

Topic linkage is best-effort: when a `topic_en` field is present we look up
the matching `topics` row for that subject and store the FK so the chat
session can pull "formulas relevant to my current topic" without resorting
to substring matches at runtime.

Idempotent: matches on `slug`, updates in place if metadata changed.

Run with:
    python scripts/seed_formulas.py
or via the unified runner (already wires it in):
    python scripts/seed_all.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from app.core.db import async_session_factory  # noqa: E402
from app.core.slugs import slugify  # noqa: E402
from app.models.catalog import Subject, SubjectCode, Topic  # noqa: E402
from app.models.formula import Formula, FormulaKind  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Curated seed. Mirrors what used to live in
#   - backend/src/app/modules/exams/router.py::_FORMULAS_BY_SUBJECT
#   - backend/src/app/sse/chat_lesson.py::_TOPIC_HINTS
# `keywords` is the per-row fallback for matching when no topic_en is set.
# ─────────────────────────────────────────────────────────────────────────────


def _f(
    group: str,
    name: str,
    expression: str,
    latex: str | None = None,
    topic_en: str | None = None,
    keywords: list[str] | None = None,
) -> dict:
    return {
        "group": group,
        "name": name,
        "expression": expression,
        "latex": latex,
        "topic_en": topic_en,
        "keywords": keywords or [],
        "kind": FormulaKind.FORMULA,
        "href": None,
    }


def _r(group: str, name: str, host: str, href: str) -> dict:
    return {
        "group": group,
        "name": name,
        "expression": host,
        "latex": None,
        "topic_en": None,
        "keywords": [],
        "kind": FormulaKind.REFERENCE,
        "href": href,
    }


FORMULA_SEED: dict[SubjectCode, list[dict]] = {
    SubjectCode.MATH: [
        _f("Algebra", "Quadratic formula",
           "x = (−b ± √(b² − 4ac)) / 2a",
           latex=r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}",
           topic_en="Quadratic equations", keywords=["quadratic"]),
        _f("Algebra", "Discriminant",
           "D = b² − 4ac",
           latex=r"D = b^2 - 4ac",
           topic_en="Quadratic equations", keywords=["quadratic", "discriminant"]),
        _f("Algebra", "Vieta's theorem",
           "x₁ + x₂ = −b/a, x₁·x₂ = c/a",
           latex=r"x_1 + x_2 = -b/a,\ x_1 x_2 = c/a",
           topic_en="Quadratic equations", keywords=["vieta", "quadratic"]),
        _f("Algebra", "Difference of squares",
           "a² − b² = (a − b)(a + b)",
           latex=r"a^2 - b^2 = (a - b)(a + b)"),
        _f("Algebra", "Sum of cubes",
           "a³ + b³ = (a + b)(a² − ab + b²)",
           latex=r"a^3 + b^3 = (a + b)(a^2 - ab + b^2)"),
        _f("Algebra", "Binomial square",
           "(a ± b)² = a² ± 2ab + b²",
           latex=r"(a \pm b)^2 = a^2 \pm 2ab + b^2"),
        _f("Algebra", "Linear root",
           "x = −b/a   (a ≠ 0)",
           latex=r"x = -b/a\ (a \ne 0)",
           topic_en="Linear equations", keywords=["linear"]),
        _f("Algebra", "Absolute-value inequality (less)",
           "|x| < k ⇔ −k < x < k",
           latex=r"|x| < k \Leftrightarrow -k < x < k",
           topic_en="Inequalities", keywords=["inequality", "absolute"]),
        _f("Algebra", "Absolute-value inequality (greater)",
           "|x| > k ⇔ x < −k or x > k",
           latex=r"|x| > k \Leftrightarrow x < -k\ \text{or}\ x > k",
           topic_en="Inequalities", keywords=["inequality", "absolute"]),
        _f("Logarithms", "Product",
           "logₐ(xy) = logₐ x + logₐ y",
           latex=r"\log_a(xy) = \log_a x + \log_a y",
           topic_en="Logarithms", keywords=["logarithm", "log"]),
        _f("Logarithms", "Quotient",
           "logₐ(x/y) = logₐ x − logₐ y",
           latex=r"\log_a(x/y) = \log_a x - \log_a y",
           topic_en="Logarithms", keywords=["logarithm", "log"]),
        _f("Logarithms", "Power",
           "logₐ(xⁿ) = n·logₐ x",
           latex=r"\log_a(x^n) = n \log_a x",
           topic_en="Logarithms", keywords=["logarithm", "log"]),
        _f("Logarithms", "Change of base",
           "logₐ x = ln x / ln a",
           latex=r"\log_a x = \ln x / \ln a",
           topic_en="Logarithms", keywords=["logarithm", "log"]),
        _f("Trigonometry", "Pythagorean identity",
           "sin²θ + cos²θ = 1",
           latex=r"\sin^2\theta + \cos^2\theta = 1",
           topic_en="Trigonometry", keywords=["trig", "trigonometry"]),
        _f("Trigonometry", "Double angle (sin)",
           "sin 2θ = 2 sinθ cosθ",
           latex=r"\sin 2\theta = 2\sin\theta\cos\theta",
           topic_en="Trigonometry", keywords=["trig", "trigonometry"]),
        _f("Trigonometry", "Double angle (cos)",
           "cos 2θ = cos²θ − sin²θ",
           latex=r"\cos 2\theta = \cos^2\theta - \sin^2\theta",
           topic_en="Trigonometry", keywords=["trig", "trigonometry"]),
        _f("Trigonometry", "Tangent",
           "tan θ = sin θ / cos θ",
           latex=r"\tan\theta = \sin\theta/\cos\theta",
           topic_en="Trigonometry", keywords=["trig", "trigonometry"]),
        _f("Trigonometry", "Law of cosines",
           "c² = a² + b² − 2ab·cosγ",
           latex=r"c^2 = a^2 + b^2 - 2ab\cos\gamma",
           topic_en="Trigonometry", keywords=["trig", "trigonometry"]),
        _f("Geometry", "Circle area", "A = πr²", latex=r"A = \pi r^2", topic_en="Geometry"),
        _f("Geometry", "Circle circumference", "C = 2πr", latex=r"C = 2\pi r", topic_en="Geometry"),
        _f("Geometry", "Triangle area", "A = ½·b·h", latex=r"A = \tfrac{1}{2} b h", topic_en="Geometry"),
        _f("Geometry", "Sphere volume", "V = (4/3)πr³", latex=r"V = \tfrac{4}{3}\pi r^3", topic_en="Geometry"),
        _f("Geometry", "Cylinder volume", "V = πr²h", latex=r"V = \pi r^2 h", topic_en="Geometry"),
        _f("Sequences & series", "Arithmetic n-th term",
           "aₙ = a₁ + (n − 1)d",
           latex=r"a_n = a_1 + (n-1)d",
           topic_en="Sequences & series", keywords=["sequence", "arithmetic"]),
        _f("Sequences & series", "Arithmetic sum",
           "Sₙ = n/2 · (a₁ + aₙ)",
           latex=r"S_n = \tfrac{n}{2}(a_1 + a_n)",
           topic_en="Sequences & series", keywords=["sequence", "arithmetic"]),
        _f("Sequences & series", "Geometric n-th term",
           "aₙ = a₁ · qⁿ⁻¹",
           latex=r"a_n = a_1 q^{n-1}",
           topic_en="Sequences & series", keywords=["sequence", "geometric"]),
        _f("Sequences & series", "Geometric sum",
           "Sₙ = a₁ · (qⁿ − 1) / (q − 1)",
           latex=r"S_n = a_1(q^n - 1)/(q - 1)",
           topic_en="Sequences & series", keywords=["sequence", "geometric"]),
    ],
    SubjectCode.PHYS: [
        _f("Mechanics", "Newton's 2nd law", "F = m·a", latex=r"F = ma", topic_en="Newton's laws"),
        _f("Mechanics", "Kinetic energy", "Eₖ = ½·m·v²", latex=r"E_k = \tfrac{1}{2}mv^2", topic_en="Energy & work"),
        _f("Mechanics", "Momentum", "p = m·v", latex=r"p = mv", topic_en="Momentum"),
        _f("Mechanics", "Work", "W = F·d·cos θ", latex=r"W = Fd\cos\theta", topic_en="Energy & work"),
        _f("Mechanics", "Gravitational PE", "Eₚ = m·g·h", latex=r"E_p = mgh", topic_en="Energy & work"),
        _f("Kinematics", "Final velocity", "v = v₀ + a·t", latex=r"v = v_0 + at", topic_en="Kinematics"),
        _f("Kinematics", "Displacement", "s = v₀·t + ½·a·t²", latex=r"s = v_0 t + \tfrac{1}{2}at^2", topic_en="Kinematics"),
        _f("Kinematics", "Velocity²", "v² = v₀² + 2·a·s", latex=r"v^2 = v_0^2 + 2as", topic_en="Kinematics"),
        _f("Electricity", "Ohm's law", "U = I·R", latex=r"U = IR", topic_en="DC circuits"),
        _f("Electricity", "Power", "P = U·I = I²·R", latex=r"P = UI = I^2 R", topic_en="DC circuits"),
        _f("Electricity", "Capacitor charge", "Q = C·U", latex=r"Q = CU", topic_en="Electrostatics"),
        _f("Thermodynamics", "Ideal gas", "P·V = n·R·T", latex=r"PV = nRT", topic_en="Thermodynamics"),
        _f("Thermodynamics", "Heat", "Q = m·c·ΔT", latex=r"Q = mc\Delta T", topic_en="Thermodynamics"),
        _f("Thermodynamics", "1st law", "ΔU = Q − W", latex=r"\Delta U = Q - W", topic_en="Thermodynamics"),
    ],
    SubjectCode.CHEM: [
        _f("Stoichiometry", "Moles", "n = m / M", latex=r"n = m/M", topic_en="Stoichiometry"),
        _f("Stoichiometry", "Concentration", "c = n / V", latex=r"c = n/V", topic_en="Solutions"),
        _f("Stoichiometry", "Dilution", "c₁·V₁ = c₂·V₂", latex=r"c_1 V_1 = c_2 V_2", topic_en="Solutions"),
        _f("Gases", "Ideal gas", "P·V = n·R·T", latex=r"PV = nRT", topic_en="Gas laws"),
        _f("Gases", "Molar volume (STP)", "Vₘ = 22.4 L/mol", topic_en="Gas laws"),
        _f("Acid–base", "pH", "pH = −log[H⁺]", latex=r"\mathrm{pH} = -\log[H^+]", topic_en="Acids and bases"),
        _f("Acid–base", "Water equilibrium", "[H⁺]·[OH⁻] = 10⁻¹⁴", topic_en="Acids and bases"),
        _f("Acid–base", "pH + pOH", "pH + pOH = 14", topic_en="Acids and bases"),
        _f("Thermochemistry", "Heat absorbed", "Q = m·c·ΔT", latex=r"Q = mc\Delta T"),
        _f("Thermochemistry", "Reaction enthalpy", "ΔH = ΣHₚ − ΣHᵣ", latex=r"\Delta H = \Sigma H_p - \Sigma H_r"),
    ],
    SubjectCode.BIO: [
        _f("Genetics", "Hardy–Weinberg", "p² + 2pq + q² = 1", latex=r"p^2 + 2pq + q^2 = 1", topic_en="Genetics"),
        _f("Genetics", "Allele sum", "p + q = 1", latex=r"p + q = 1", topic_en="Genetics"),
        _f("Population", "Growth rate", "r = (B − D) / N", latex=r"r = (B - D)/N", topic_en="Ecology"),
        _f("Population", "Exponential growth", "N(t) = N₀·eʳᵗ", latex=r"N(t) = N_0 e^{rt}", topic_en="Ecology"),
        _f("Cellular", "Photosynthesis", "6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂", topic_en="Plants"),
        _f("Cellular", "Cellular respiration", "C₆H₁₂O₆ + 6O₂ → 6CO₂ + 6H₂O", topic_en="Cell biology"),
    ],
    SubjectCode.HIST: [
        _r("Primary sources", "Avesto (full text)", "avesta.org", "https://www.avesta.org/avesta.html"),
        _r("Primary sources", "Bobur-noma — Andijani text", "archive.org", "https://archive.org/details/baburnama"),
        _r("Primary sources", "Temur tuzuklari", "ziyouz.com", "https://ziyouz.uz/ilm-va-fan/tarix/temur-tuzuklari"),
        _r("Reference encyclopaedias", "O'zbekiston Milliy Ensiklopediyasi", "ensiklopediya.uz", "https://ensiklopediya.uz"),
        _r("Reference encyclopaedias", "Britannica — Central Asia", "britannica.com", "https://www.britannica.com/place/Central-Asia"),
        _r("Reference encyclopaedias", "UNESCO Silk Roads Programme", "en.unesco.org", "https://en.unesco.org/silkroad/"),
        _r("Timelines", "World History timeline", "worldhistory.org", "https://www.worldhistory.org/timeline/"),
        _r("Timelines", "Uzbekistan — chronological table", "uza.uz", "https://uza.uz/en/posts/uzbekistan-history"),
    ],
    SubjectCode.GEOG: [
        _r("Atlases & maps", "National Geographic MapMaker", "mapmaker.nationalgeographic.org", "https://mapmaker.nationalgeographic.org"),
        _r("Atlases & maps", "OpenStreetMap", "openstreetmap.org", "https://www.openstreetmap.org"),
        _r("Data sources", "World Bank Open Data", "data.worldbank.org", "https://data.worldbank.org"),
        _r("Data sources", "UN Statistics Division", "unstats.un.org", "https://unstats.un.org"),
        _r("Data sources", "Uzbekistan — Stat Committee", "stat.uz", "https://www.stat.uz/en"),
        _r("Climate & physical", "NASA Earth Observatory", "earthobservatory.nasa.gov", "https://earthobservatory.nasa.gov"),
        _r("Climate & physical", "Köppen climate classification", "britannica.com", "https://www.britannica.com/science/Koppen-climate-classification"),
    ],
    SubjectCode.UZB_LIT: [
        _r("Classic texts", "Alisher Navoiy — Xamsa", "ziyouz.com", "https://ziyouz.uz/ozbek-mumtoz-adabiyoti/alisher-navoiy"),
        _r("Classic texts", "Cho'lpon — She'rlar", "ziyouz.com", "https://ziyouz.uz/ozbek-adabiyoti/abdulhamid-cholpon"),
        _r("Classic texts", "Abdulla Qodiriy — O'tkan kunlar", "ziyouz.com", "https://ziyouz.uz/ozbek-adabiyoti/abdulla-qodiriy"),
        _r("Reference", "O'zbek tili — Adabiyot ensiklopediyasi", "ensiklopediya.uz", "https://ensiklopediya.uz"),
    ],
    SubjectCode.RUS_LIT: [
        _r("Тексты", "А. С. Пушкин — собрание", "rvb.ru", "https://rvb.ru/pushkin/"),
        _r("Тексты", "Ф. М. Достоевский", "rvb.ru", "https://rvb.ru/dostoevski/"),
        _r("Тексты", "Л. Н. Толстой", "tolstoy.ru", "https://tolstoy.ru/creativity/"),
    ],
}


async def _topic_lookup(db, subject_id) -> dict[str, "Topic"]:
    rows = (
        await db.execute(select(Topic).where(Topic.subject_id == subject_id))
    ).scalars().all()
    return {t.name_en.lower(): t for t in rows}


async def _upsert_formula(
    db, subject: Subject, topics_by_name: dict, idx: int, payload: dict
) -> bool:
    slug = slugify(f"{subject.code.value}-{payload['group']}-{payload['name']}")[:118]
    topic_id = None
    topic_en = payload.get("topic_en")
    if topic_en:
        match = topics_by_name.get(topic_en.lower())
        if match:
            topic_id = match.id

    existing = (
        await db.execute(select(Formula).where(Formula.slug == slug))
    ).scalar_one_or_none()
    if existing:
        existing.subject_id = subject.id
        existing.topic_id = topic_id
        existing.group_title = payload["group"]
        existing.name = payload["name"]
        existing.expression = payload["expression"]
        existing.latex = payload.get("latex")
        existing.href = payload.get("href")
        existing.kind = payload["kind"]
        existing.order_index = idx
        existing.keywords = payload.get("keywords") or []
        return False

    db.add(
        Formula(
            subject_id=subject.id,
            topic_id=topic_id,
            slug=slug,
            group_title=payload["group"],
            name=payload["name"],
            expression=payload["expression"],
            latex=payload.get("latex"),
            href=payload.get("href"),
            kind=payload["kind"],
            order_index=idx,
            keywords=payload.get("keywords") or [],
        )
    )
    return True


async def seed() -> None:
    async with async_session_factory() as db:
        subjects = (
            await db.execute(select(Subject))
        ).scalars().all()
        if not subjects:
            print("⚠  No subjects — run scripts/seed_subjects.py first.")
            return
        by_code = {s.code: s for s in subjects}

        totals = {"created": 0, "updated": 0}
        for code, rows in FORMULA_SEED.items():
            subj = by_code.get(code)
            if not subj:
                continue
            topics_by_name = await _topic_lookup(db, subj.id)
            created_here = 0
            updated_here = 0
            for idx, row in enumerate(rows):
                created = await _upsert_formula(db, subj, topics_by_name, idx, row)
                if created:
                    created_here += 1
                    totals["created"] += 1
                else:
                    updated_here += 1
                    totals["updated"] += 1
            await db.commit()
            print(
                f"✅ {code.value:<8s} formulas — created +{created_here:>2d} | "
                f"updated {updated_here:>2d}"
            )
        print(
            f"\n— Totals — created: {totals['created']} | "
            f"updated: {totals['updated']}"
        )


if __name__ == "__main__":
    asyncio.run(seed())
