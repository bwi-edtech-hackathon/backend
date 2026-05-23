"""Slug helpers for URL-friendly identifiers (topics, exams, chat sessions)."""

import re
import secrets

from slugify import slugify as _slugify


def slugify(text: str, max_length: int = 80) -> str:
    """Lowercase ASCII slug. Empty input → random 8-char fallback."""
    if not text or not text.strip():
        return secrets.token_hex(4)
    base = _slugify(text, max_length=max_length, lowercase=True, separator="-")
    return base or secrets.token_hex(4)


def short_slug(text: str, suffix_length: int = 6) -> str:
    """Slug + random suffix to guarantee uniqueness without DB roundtrip."""
    return f"{slugify(text, max_length=40)}-{secrets.token_hex(suffix_length // 2)}"


_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def is_valid_slug(s: str) -> bool:
    return bool(_SLUG_RE.fullmatch(s))
