"""User profile endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

try:
    from gateway.db.models import Role, User  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from backend.gateway.db.models import Role, User  # type: ignore

from ..dependencies import RequirePermissions, get_current_user, get_session
from ..security import hash_password, verify_password
from .auth import UserResource, serialize_user

router = APIRouter(prefix="/users", tags=["users"])


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


@router.get("/me", response_model=UserResource)
async def read_me(current_user: User = Depends(get_current_user)) -> UserResource:
    return serialize_user(current_user)


@router.patch(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def change_my_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    if not verify_password(current_user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid current password")

    stmt = select(User).where(User.id == current_user.id)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = hash_password(payload.new_password)
    await db.commit()


@router.get(
    "",
    response_model=list[UserResource],
    dependencies=[Depends(RequirePermissions("gateway.users.view"))],
)
async def list_users(db: AsyncSession = Depends(get_session)) -> list[UserResource]:
    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .order_by(User.id.asc())
    )
    result = await db.execute(stmt)
    users = result.scalars().unique().all()
    return [serialize_user(user) for user in users]


@router.get(
    "/{user_id}",
    response_model=UserResource,
    dependencies=[Depends(RequirePermissions("gateway.users.view"))],
)
async def get_user(user_id: int, db: AsyncSession = Depends(get_session)) -> UserResource:
    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return serialize_user(user)
