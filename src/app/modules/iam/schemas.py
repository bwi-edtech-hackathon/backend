"""Pydantic schemas for IAM endpoints."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import Plan, UserLanguage

# === Phone validation (Uzbekistan: +998XXXXXXXXX) ===
PHONE_RE = re.compile(r"^\+?998\d{9}$")


def _normalize_phone(v: str) -> str:
    v = v.strip().replace(" ", "").replace("-", "")
    if not v.startswith("+"):
        v = "+" + v
    if not PHONE_RE.fullmatch(v):
        raise ValueError("Phone must be +998XXXXXXXXX (Uzbekistan)")
    return v


class RegisterIn(BaseModel):
    phone: str = Field(..., description="+998XXXXXXXXX")
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=120)
    language: UserLanguage = UserLanguage.UZ
    email: EmailStr | None = None
    region: str | None = Field(None, max_length=80)
    target_grade: str | None = Field(None, max_length=8)
    exam_target_date: date | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return _normalize_phone(v)


class LoginIn(BaseModel):
    phone: str
    password: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return _normalize_phone(v)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str
    email: str | None
    full_name: str
    language: UserLanguage
    region: str | None
    school_id: uuid.UUID | None
    target_grade: str | None
    exam_target_date: date | None
    plan: Plan
    premium_until: datetime | None
    streak_days: int
    last_active_date: date | None
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=120)
    email: EmailStr | None = None
    language: UserLanguage | None = None
    region: str | None = Field(None, max_length=80)
    target_grade: str | None = Field(None, max_length=8)
    exam_target_date: date | None = None
