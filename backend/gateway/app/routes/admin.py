"""Administrative endpoints for managing users, roles and permissions."""
from __future__ import annotations

from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

try:
    from gateway.db.models import Permission, Role, User, UserRole, UserTokenPurpose  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from backend.gateway.db.models import (  # type: ignore
        Permission,
        Role,
        User,
        UserRole,
        UserTokenPurpose,
    )

from ..config import settings
from ..dependencies import RequirePermissions, get_email_dispatcher, get_session
from ..email import EmailDispatcher
from ..security import hash_password
from ..token_service import TokenService
from .auth import OperationStatus, UserResource, clear_backup_codes, revoke_user_sessions, serialize_user

router = APIRouter(prefix="/admin", tags=["admin"])

_MANAGE_USERS_PERMISSION = "gateway.users.manage"
_ADMIN_PERMISSION = "gateway.admin"


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    username: str | None = Field(default=None, min_length=3, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    roles: list[str] = Field(default_factory=lambda: [UserRole.MEMBER.value])
    active: bool = True

    model_config = ConfigDict(populate_by_name=True)


class AdminUserUpdate(BaseModel):
    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8)
    active: bool | None = None
    roles: list[str] | None = None

    model_config = ConfigDict(populate_by_name=True)


class PermissionResource(BaseModel):
    code: str
    name: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RoleResource(BaseModel):
    slug: str
    name: str
    description: str | None = None
    permissions: list[str]

    model_config = ConfigDict(from_attributes=True)


class RolePermissionUpdate(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class PermissionCreate(BaseModel):
    code: str = Field(min_length=3, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(populate_by_name=True)


async def _email_exists(db: AsyncSession, email: str, *, exclude_user: int | None = None) -> bool:
    stmt = select(User.id).where(func.lower(User.email) == email.lower())
    if exclude_user is not None:
        stmt = stmt.where(User.id != exclude_user)
    result = await db.execute(stmt)
    return result.scalars().first() is not None


async def _username_exists(db: AsyncSession, username: str, *, exclude_user: int | None = None) -> bool:
    stmt = select(User.id).where(func.lower(User.username) == username.lower())
    if exclude_user is not None:
        stmt = stmt.where(User.id != exclude_user)
    result = await db.execute(stmt)
    return result.scalars().first() is not None


async def _load_user(db: AsyncSession, user_id: int) -> User:
    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _load_role(db: AsyncSession, slug: str) -> Role:
    stmt = select(Role).options(selectinload(Role.permissions)).where(Role.slug == slug)
    result = await db.execute(stmt)
    role = result.scalars().first()
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


async def _apply_roles(db: AsyncSession, user: User, role_slugs: Iterable[str]) -> None:
    desired = list({slug for slug in role_slugs} or [UserRole.MEMBER.value])
    stmt = select(Role).options(selectinload(Role.permissions)).where(Role.slug.in_(desired))
    result = await db.execute(stmt)
    roles = result.scalars().all()
    found = {role.slug for role in roles}
    missing = sorted(set(desired) - found)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"missingRoles": missing},
        )
    await db.refresh(user, attribute_names=["roles"])
    user.roles.clear()
    user.roles.extend(roles)
    await db.flush()


def _clean_username(email: str, username: str | None) -> str:
    if username is None:
        return email.split("@", 1)[0]
    return username.strip()


def _clean_name(name: str | None) -> str | None:
    if name is None:
        return None
    cleaned = name.strip()
    return cleaned or None


def _serialize_permission(permission: Permission) -> PermissionResource:
    return PermissionResource(code=permission.code, name=permission.name, description=permission.description)


def _serialize_role(role: Role) -> RoleResource:
    return RoleResource(
        slug=role.slug,
        name=role.name,
        description=role.description,
        permissions=sorted({permission.code for permission in role.permissions}),
    )


@router.post(
    "/users/{user_id}/mfa/disable",
    response_model=OperationStatus,
    dependencies=[
        Depends(
            RequirePermissions(
                _MANAGE_USERS_PERMISSION,
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def admin_disable_user_mfa(
    user_id: int,
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    user = await _load_user(db, user_id)
    if not user.mfa_enabled:
        return OperationStatus(detail="Two-factor authentication already disabled")

    user.mfa_enabled = False
    user.mfa_secret = None
    await clear_backup_codes(db, user)
    revoked = await revoke_user_sessions(db, user)
    await db.flush()
    await db.commit()
    return OperationStatus(detail=f"Two-factor authentication disabled. Revoked {revoked} sessions.")


@router.post(
    "/users",
    response_model=UserResource,
    dependencies=[
        Depends(
            RequirePermissions(
                _MANAGE_USERS_PERMISSION,
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def create_user(
    payload: AdminUserCreate,
    db: AsyncSession = Depends(get_session),
    email_dispatcher: EmailDispatcher = Depends(get_email_dispatcher),
) -> UserResource:
    email = str(payload.email).strip().lower()
    username = _clean_username(email, payload.username)
    name = _clean_name(payload.name)

    if await _email_exists(db, email):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already in use")
    if await _username_exists(db, username):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Username already in use")

    user = User(
        email=email,
        username=username,
        name=name,
        password_hash=hash_password(payload.password),
        active=payload.active,
    )
    db.add(user)
    await db.flush()
    await _apply_roles(db, user, payload.roles)
    verification_record = None
    verification_token: str | None = None
    if not user.email_verified:
        token_service = TokenService(db)
        verification_record, verification_token = await token_service.issue(
            user=user,
            purpose=UserTokenPurpose.EMAIL_VERIFICATION,
            ttl_seconds=settings.auth.email_verification_token_ttl_seconds,
        )
    await db.commit()

    created = await _load_user(db, user.id)
    if verification_record is not None and verification_token is not None:
        await db.refresh(verification_record)
        await email_dispatcher.send_email_verification(
            email=created.email,
            token=verification_token,
            expires_at=verification_record.expires_at,
        )
    return serialize_user(created)


@router.patch(
    "/users/{user_id}",
    response_model=UserResource,
    dependencies=[
        Depends(
            RequirePermissions(
                _MANAGE_USERS_PERMISSION,
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: AsyncSession = Depends(get_session),
) -> UserResource:
    user = await _load_user(db, user_id)

    if payload.email is not None:
        email = str(payload.email).strip().lower()
        if await _email_exists(db, email, exclude_user=user.id):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already in use")
        user.email = email

    if payload.username is not None:
        username = payload.username.strip()
        if await _username_exists(db, username, exclude_user=user.id):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Username already in use")
        user.username = username

    if payload.name is not None:
        user.name = _clean_name(payload.name)

    if payload.password is not None:
        user.password_hash = hash_password(payload.password)

    if payload.active is not None:
        user.active = payload.active

    if payload.roles is not None:
        await _apply_roles(db, user, payload.roles)

    await db.commit()
    updated = await _load_user(db, user.id)
    return serialize_user(updated)


@router.get(
    "/users",
    response_model=list[UserResource],
    dependencies=[
        Depends(
            RequirePermissions(
                "gateway.users.view",
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
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
    "/users/{user_id}",
    response_model=UserResource,
    dependencies=[
        Depends(
            RequirePermissions(
                "gateway.users.view",
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def get_user(user_id: int, db: AsyncSession = Depends(get_session)) -> UserResource:
    user = await _load_user(db, user_id)
    return serialize_user(user)


@router.post(
    "/users/{user_id}/roles/{role_slug}",
    response_model=UserResource,
    dependencies=[
        Depends(
            RequirePermissions(
                _MANAGE_USERS_PERMISSION,
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def assign_role(
    user_id: int,
    role_slug: str,
    db: AsyncSession = Depends(get_session),
) -> UserResource:
    user = await _load_user(db, user_id)
    role = await _load_role(db, role_slug)
    if role not in user.roles:
        user.roles.append(role)
    await db.commit()
    updated = await _load_user(db, user.id)
    return serialize_user(updated)


@router.delete(
    "/users/{user_id}/roles/{role_slug}",
    response_model=UserResource,
    dependencies=[
        Depends(
            RequirePermissions(
                _MANAGE_USERS_PERMISSION,
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def remove_role(
    user_id: int,
    role_slug: str,
    db: AsyncSession = Depends(get_session),
) -> UserResource:
    user = await _load_user(db, user_id)
    role = await _load_role(db, role_slug)
    user.roles = [existing for existing in user.roles if existing.id != role.id]
    await db.commit()
    updated = await _load_user(db, user.id)
    return serialize_user(updated)


@router.get(
    "/permissions",
    response_model=list[PermissionResource],
    dependencies=[
        Depends(
            RequirePermissions(
                _MANAGE_USERS_PERMISSION,
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def list_permissions(db: AsyncSession = Depends(get_session)) -> list[PermissionResource]:
    stmt = select(Permission).order_by(Permission.code.asc())
    result = await db.execute(stmt)
    permissions = result.scalars().all()
    return [_serialize_permission(permission) for permission in permissions]


@router.post(
    "/permissions",
    response_model=PermissionResource,
    dependencies=[
        Depends(
            RequirePermissions(
                _ADMIN_PERMISSION,
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def create_permission(
    payload: PermissionCreate,
    db: AsyncSession = Depends(get_session),
) -> PermissionResource:
    code = payload.code.strip()
    stmt = select(Permission).where(func.lower(Permission.code) == code.lower())
    result = await db.execute(stmt)
    if result.scalars().first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Permission already exists")

    permission = Permission(
        code=code,
        name=payload.name.strip(),
        description=_clean_name(payload.description),
    )
    db.add(permission)
    await db.commit()
    await db.refresh(permission)
    return _serialize_permission(permission)


@router.get(
    "/roles",
    response_model=list[RoleResource],
    dependencies=[
        Depends(
            RequirePermissions(
                _MANAGE_USERS_PERMISSION,
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def list_roles(db: AsyncSession = Depends(get_session)) -> list[RoleResource]:
    stmt = select(Role).options(selectinload(Role.permissions)).order_by(Role.id.asc())
    result = await db.execute(stmt)
    roles = result.scalars().all()
    return [_serialize_role(role) for role in roles]


@router.post(
    "/roles/{role_slug}/permissions",
    response_model=RoleResource,
    dependencies=[
        Depends(
            RequirePermissions(
                _ADMIN_PERMISSION,
                roles=[UserRole.ADMIN.value],
            )
        )
    ],
)
async def set_role_permissions(
    role_slug: str,
    payload: RolePermissionUpdate,
    db: AsyncSession = Depends(get_session),
) -> RoleResource:
    role = await _load_role(db, role_slug)
    permissions: list[Permission] = []
    if payload.permissions:
        stmt = select(Permission).where(Permission.code.in_(payload.permissions))
        result = await db.execute(stmt)
        permissions = result.scalars().all()
        found_codes = {permission.code for permission in permissions}
        missing = sorted(set(payload.permissions) - found_codes)
        if missing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"missingPermissions": missing},
            )
    role.permissions = permissions
    await db.commit()
    updated = await _load_role(db, role.slug)
    return _serialize_role(updated)
