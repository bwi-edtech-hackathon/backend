"""Unit tests for slugify helpers."""

from app.core.slugs import is_valid_slug, short_slug, slugify


def test_slugify_basic() -> None:
    assert slugify("Quadratic Equations") == "quadratic-equations"


def test_slugify_unicode() -> None:
    # Should produce ASCII-only slug
    s = slugify("Tarjima qilish — Algebra")
    assert is_valid_slug(s)


def test_slugify_empty_fallback() -> None:
    s = slugify("")
    assert is_valid_slug(s)
    assert len(s) >= 4


def test_short_slug_uniqueness_suffix() -> None:
    a = short_slug("Topic")
    b = short_slug("Topic")
    assert a != b
    assert a.startswith("topic-")
    assert b.startswith("topic-")
