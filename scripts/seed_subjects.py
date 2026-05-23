"""Seed the 8 BMBA subjects in 3 languages.

Usage:
    python scripts/seed_subjects.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make src importable when run from repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from app.core.db import async_session_factory  # noqa: E402
from app.core.slugs import slugify  # noqa: E402
from app.models.catalog import Subject, SubjectCode  # noqa: E402


SUBJECTS_SEED = [
    {
        "code": SubjectCode.MATH,
        "name_uz": "Matematika",
        "name_ru": "Математика",
        "name_en": "Mathematics",
        "has_essay": False,
        "format_notes": "Closed + open, no essay",
        "order_index": 1,
    },
    {
        "code": SubjectCode.PHYS,
        "name_uz": "Fizika",
        "name_ru": "Физика",
        "name_en": "Physics",
        "has_essay": False,
        "format_notes": "Closed + open, formulas",
        "order_index": 2,
    },
    {
        "code": SubjectCode.CHEM,
        "name_uz": "Kimyo",
        "name_ru": "Химия",
        "name_en": "Chemistry",
        "has_essay": False,
        "format_notes": "Closed + open, reactions",
        "order_index": 3,
    },
    {
        "code": SubjectCode.BIO,
        "name_uz": "Biologiya",
        "name_ru": "Биология",
        "name_en": "Biology",
        "has_essay": False,
        "format_notes": "Closed + open",
        "order_index": 4,
    },
    {
        "code": SubjectCode.HIST,
        "name_uz": "Tarix",
        "name_ru": "История",
        "name_en": "History",
        "has_essay": False,
        "format_notes": "Closed + open, weighted by era",
        "order_index": 5,
    },
    {
        "code": SubjectCode.GEOG,
        "name_uz": "Geografiya",
        "name_ru": "География",
        "name_en": "Geography",
        "has_essay": False,
        "format_notes": "Closed + open, maps",
        "order_index": 6,
    },
    {
        "code": SubjectCode.UZB_LIT,
        "name_uz": "O'zbek tili va adabiyoti",
        "name_ru": "Узбекский язык и литература",
        "name_en": "Uzbek language and literature",
        "has_essay": True,
        "format_notes": "Closed + open + essay",
        "order_index": 7,
    },
    {
        "code": SubjectCode.RUS_LIT,
        "name_uz": "Rus tili va adabiyoti",
        "name_ru": "Русский язык и литература",
        "name_en": "Russian language and literature",
        "has_essay": True,
        "format_notes": "Closed + open + essay",
        "order_index": 8,
    },
]


async def seed() -> None:
    async with async_session_factory() as db:
        created = 0
        for row in SUBJECTS_SEED:
            res = await db.execute(select(Subject).where(Subject.code == row["code"]))
            if res.scalar_one_or_none():
                print(f"⏭  {row['code'].value} already exists")
                continue
            subject = Subject(
                code=row["code"],
                slug=slugify(row["code"].value.lower().replace("_", "-")),
                name_uz=row["name_uz"],
                name_ru=row["name_ru"],
                name_en=row["name_en"],
                has_essay=row["has_essay"],
                format_notes=row["format_notes"],
                order_index=row["order_index"],
            )
            db.add(subject)
            created += 1
            print(f"✅ {row['code'].value} — {row['name_en']}")
        await db.commit()
        print(f"\nDone. Created {created} subjects.")


if __name__ == "__main__":
    asyncio.run(seed())
