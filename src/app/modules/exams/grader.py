"""Question grading + Rasch score estimation."""

from __future__ import annotations

import re
from decimal import Decimal

from app.models.catalog import Question, QuestionType


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def grade_answer(question: Question, submitted) -> tuple[bool, Decimal]:
    """Return (is_correct, points_awarded). Open_B + Essay → 0 here; LLM-graded async."""
    if submitted is None or submitted == "":
        return False, Decimal("0.00")

    points = question.points
    if question.type == QuestionType.CLOSED:
        ok = str(submitted).strip().upper() == str(question.correct_answer).strip().upper()
        return ok, points if ok else Decimal("0.00")

    if question.type == QuestionType.MULTI_SELECT:
        if not isinstance(submitted, list):
            return False, Decimal("0.00")
        correct_set = set(map(str.upper, question.correct_answer or []))
        sub_set = set(map(str.upper, map(str, submitted)))
        ok = sub_set == correct_set
        return ok, points if ok else Decimal("0.00")

    if question.type == QuestionType.MATCHING:
        if not isinstance(submitted, dict):
            return False, Decimal("0.00")
        expected = {str(k): str(v).lower() for k, v in (question.correct_answer or {}).items()}
        actual = {str(k): str(v).lower() for k, v in submitted.items()}
        ok = expected == actual
        return ok, points if ok else Decimal("0.00")

    if question.type == QuestionType.OPEN_A:
        text = _normalize(str(submitted))
        # Exact-match against any item in correct_answer list
        accepted = question.correct_answer
        if isinstance(accepted, list):
            for variant in accepted:
                if _normalize(str(variant)) == text:
                    return True, points
        elif isinstance(accepted, str):
            if _normalize(accepted) == text:
                return True, points
        # Regex patterns
        for pattern in question.accepted_patterns or []:
            try:
                if re.fullmatch(pattern, text, flags=re.IGNORECASE):
                    return True, points
            except re.error:
                continue
        return False, Decimal("0.00")

    # OPEN_B and ESSAY: deferred to LLM async; provisional 0 points.
    return False, Decimal("0.00")


def estimate_rasch(answers: list[dict]) -> Decimal:
    """Cheap Rasch surrogate: weighted sum of correct × (1 + difficulty).

    Each answer is {"is_correct": bool, "points": float, "difficulty": float}.
    Final score is normalised to 0–100 scale matching BMBA grading.
    """
    if not answers:
        return Decimal("0.00")
    max_total = sum(float(a["points"]) * (1.0 + float(a["difficulty"])) for a in answers)
    earned = sum(
        float(a["points"]) * (1.0 + float(a["difficulty"]))
        for a in answers
        if a.get("is_correct")
    )
    if max_total == 0:
        return Decimal("0.00")
    score = (earned / max_total) * 100.0
    return Decimal(f"{score:.2f}")


def grade_for_score(score: Decimal) -> str:
    s = float(score)
    if s >= 70:
        return "A+"
    if s >= 65:
        return "A"
    if s >= 60:
        return "B+"
    if s >= 55:
        return "B"
    if s >= 50:
        return "C+"
    if s >= 46:
        return "C"
    return "F"
