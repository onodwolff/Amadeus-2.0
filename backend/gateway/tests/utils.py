"""Testing utilities for gateway API tests."""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.gateway.app.security import hash_password
from backend.gateway.db.models import Role, User


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    username: str,
    password: str,
    roles: Iterable[str],
    name: str | None = None,
    active: bool = True,
) -> User:
    """Create a user with the specified roles for integration tests."""

    role_list = list(roles)
    role_map: dict[str, Role] = {}
    if role_list:
        stmt = select(Role).where(Role.slug.in_(role_list))
        result = await session.execute(stmt)
        role_map = {role.slug: role for role in result.scalars().all()}
        missing = sorted(set(role_list) - set(role_map))
        if missing:
            raise AssertionError(f"Missing seeded roles: {missing}")

    user = User(
        email=email,
        username=username,
        name=name,
        password_hash=hash_password(password),
        active=active,
    )
    session.add(user)
    for slug in role_list:
        user.roles.append(role_map[slug])

    await session.commit()
    await session.refresh(user)
    return user
