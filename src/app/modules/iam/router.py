"""IAM HTTP routes."""

from fastapi import APIRouter, status

from app.core.deps import CurrentUser, DbSession
from app.modules.iam import service
from app.modules.iam.schemas import (
    LoginIn,
    RefreshIn,
    RegisterIn,
    TokenPair,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.post(
    "/auth/register",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user with phone + password",
)
async def register(payload: RegisterIn, db: DbSession) -> TokenPair:
    user = await service.register_user(db, payload)
    return TokenPair(**service.issue_pair(user))


@router.post("/auth/login", response_model=TokenPair, summary="Login with phone + password")
async def login(payload: LoginIn, db: DbSession) -> TokenPair:
    user = await service.authenticate(db, payload)
    return TokenPair(**service.issue_pair(user))


@router.post("/auth/refresh", response_model=TokenPair, summary="Rotate refresh token")
async def refresh(payload: RefreshIn, db: DbSession) -> TokenPair:
    new_pair = await service.rotate_refresh(db, payload.refresh_token)
    return TokenPair(**new_pair)


@router.get("/users/me", response_model=UserOut, summary="Get current user profile", tags=["users"])
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/users/me", response_model=UserOut, summary="Update profile", tags=["users"])
async def update_me(payload: UserUpdate, user: CurrentUser, db: DbSession) -> UserOut:
    updated = await service.update_profile(db, user, payload)
    return UserOut.model_validate(updated)
