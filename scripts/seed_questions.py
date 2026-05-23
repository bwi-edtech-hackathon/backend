"""Seed fixture questions — STUB (Batch 2/3 will populate per subject).

Strategy (per C3=B+D):
  1. Pull official BMBA samples where structured data is available
     (https://uzbmb.uz/page/milliytest)
  2. Use Gemini to generate the rest in all 3 languages (uz/ru/en)
  3. Mark with source_tier=1 (official) or source_tier=3 (AI+review)
  4. Tag closed-type questions answerable in ≤30s with suitable_for_battle=True

For B1 this script is a placeholder so frontends don't 500 on empty queries.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


async def main() -> None:
    print("seed_questions: stub — implement per-subject in Batch 2/3")
    print("  Plan:")
    print("    - Math:    50 questions across Algebra/Geometry/Functions/Probability")
    print("    - Phys:    50 across Mechanics/Electricity/Optics/Thermo")
    print("    - Chem:    50 across Inorganic/Organic/Stoichiometry")
    print("    - Bio:     50 across Cell/Genetics/Ecology/Human-body")
    print("    - Hist:    50 across Pre-1900/Soviet-era/Modern-Uzbekistan")
    print("    - Geog:    50 across Physical/Economic/Uzbek-geography")
    print("    - UzbLit:  50 across Grammar/Classical/Modern")
    print("    - RusLit:  50 across Grammar/Classical/Modern")
    print("  All in uz/ru/en, with difficulty estimates and battle eligibility flags.")


if __name__ == "__main__":
    asyncio.run(main())
