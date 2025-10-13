#!/usr/bin/env python3
"""Seed script to create or update the primary admin user."""

from __future__ import annotations

import argparse
import asyncio
from getpass import getpass
from typing import Optional

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from backend.gateway.config.settings import settings
from backend.gateway.app.security import hash_password
from backend.gateway.db.base import Base, create_engine, create_session, dispose_engine
from backend.gateway.db.models import (
    Permission,
    Role,
    User,
    UserRole,
    role_permissions_table,
)


async def _ensure_schema(database_url: str) -> None:
    engine = create_engine(database_url, echo=False, future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _seed_admin(
    *,
    database_url: str,
    email: str,
    username: str,
    password: str,
    name: Optional[str],
) -> None:
    await _ensure_schema(database_url)

    session = create_session()
    try:
        result = await session.execute(
            select(User).where(User.username == username)
        )
        user = result.scalars().first()

        hashed = hash_password(password)

        role_definitions = {
            UserRole.ADMIN.value: (
                "Administrator",
                "Full access to all administrative capabilities.",
            ),
            UserRole.MEMBER.value: (
                "Member",
                "Standard member access with management abilities.",
            ),
            UserRole.VIEWER.value: (
                "Viewer",
                "Read-only access to view gateway information.",
            ),
        }

        role_lookup: dict[str, Role] = {}
        for slug, (name, description) in role_definitions.items():
            stmt = select(Role).where(func.lower(Role.slug) == slug)
            result = await session.execute(stmt)
            role = result.scalars().first()
            if role is None:
                role = Role(slug=slug, name=name, description=description)
                session.add(role)
                await session.flush()
            role_lookup[slug] = role

        permissions_required = {
            "gateway.admin": (
                "Gateway Administrator",
                "Manage all gateway features and configuration.",
            ),
            "gateway.users.manage": (
                "Manage Gateway Users",
                "Create, update, and remove gateway user accounts.",
            ),
            "gateway.users.view": (
                "View Gateway Users",
                "View gateway user accounts and related information.",
            ),
        }

        permission_lookup: dict[str, Permission] = {}
        for code, (name, description) in permissions_required.items():
            stmt = select(Permission).where(func.lower(Permission.code) == code)
            result = await session.execute(stmt)
            permission = result.scalars().first()
            if permission is None:
                permission = Permission(code=code, name=name, description=description)
                session.add(permission)
                await session.flush()
            permission_lookup[code] = permission

        role_permissions = {
            UserRole.ADMIN.value: (
                "gateway.admin",
                "gateway.users.manage",
                "gateway.users.view",
            ),
            UserRole.MEMBER.value: (
                "gateway.users.manage",
                "gateway.users.view",
            ),
            UserRole.VIEWER.value: ("gateway.users.view",),
        }

        for role_slug, permission_codes in role_permissions.items():
            role = role_lookup[role_slug]
            result = await session.execute(
                select(Permission.code)
                .join(
                    role_permissions_table,
                    Permission.id == role_permissions_table.c.permission_id,
                )
                .where(role_permissions_table.c.role_id == role.id)
            )
            existing_codes = set(result.scalars())

            for code in permission_codes:
                if code in existing_codes:
                    continue

                permission = permission_lookup[code]
                await session.execute(
                    insert(role_permissions_table).values(
                        role_id=role.id,
                        permission_id=permission.id,
                    )
                )
                existing_codes.add(code)

        admin_role = role_lookup[UserRole.ADMIN.value]

        if user is None:
            user = User(
                email=email,
                username=username,
                name=name,
                password_hash=hashed,
            )
            user.roles.append(admin_role)
            session.add(user)
        else:
            user.email = email
            user.name = name
            user.password_hash = hashed
            if all(role.slug != admin_role.slug for role in user.roles):
                user.roles.append(admin_role)

        await session.commit()
    except IntegrityError as exc:  # pragma: no cover - interactive script guard
        await session.rollback()
        raise SystemExit(f"Failed to create admin user: {exc}") from exc
    finally:
        await session.close()
        await dispose_engine()

    print(f"Admin account ready: {username} <{email}>")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed an admin user for the gateway database")
    parser.add_argument("--email", required=True, help="Admin e-mail address")
    parser.add_argument("--username", required=True, help="Admin username")
    parser.add_argument("--name", default=None, help="Display name for the admin user")
    parser.add_argument(
        "--password",
        default=None,
        help="Admin password. If omitted, an interactive prompt is shown.",
    )
    parser.add_argument(
        "--database-url",
        default=settings.database_url,
        help="Database URL to connect to (defaults to configured application URL).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    password = args.password or getpass("Admin password: ")
    if not password:
        raise SystemExit("Password cannot be empty")

    asyncio.run(
        _seed_admin(
            database_url=args.database_url,
            email=args.email,
            username=args.username,
            password=password,
            name=args.name,
        )
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
