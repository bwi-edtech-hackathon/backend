"""Billing routes — plan info + premium grant history."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.billing import PremiumGrant

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


class PlanOut(BaseModel):
    plan: str
    premium_until: datetime | None
    is_premium_active: bool


class GrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source: str
    granted_at: datetime
    expires_at: datetime
    note: str | None


@router.get("/me/plan", response_model=PlanOut)
async def get_plan(user: CurrentUser) -> PlanOut:
    active = bool(
        user.premium_until and user.premium_until > datetime.now(user.premium_until.tzinfo)
    )
    return PlanOut(
        plan=user.plan.value,
        premium_until=user.premium_until,
        is_premium_active=active,
    )


@router.get("/me/grants", response_model=list[GrantOut])
async def list_grants(user: CurrentUser, db: DbSession) -> list[GrantOut]:
    rows = (
        await db.execute(
            select(PremiumGrant)
            .where(PremiumGrant.user_id == user.id)
            .order_by(PremiumGrant.granted_at.desc())
        )
    ).scalars().all()
    return [
        GrantOut(
            id=g.id,
            source=g.source.value,
            granted_at=g.granted_at,
            expires_at=g.expires_at,
            note=g.note,
        )
        for g in rows
    ]


@router.get("/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "billing", "status": "ok"}
