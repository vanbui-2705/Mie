"""Database-backed effective role and permission resolution."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sqlmodels import Permission, Role, RolePermission, User, UserRole
from app.rbac_catalog import legacy_permissions


async def role_codes_for_user(session: AsyncSession, user: User) -> set[str]:
    result = await session.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    roles = set(result.scalars().all())
    return roles or {user.role or "user"}


async def permission_codes_for_user(session: AsyncSession, user: User) -> set[str]:
    result = await session.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user.id)
    )
    permissions = set(result.scalars().all())
    if permissions:
        return permissions
    has_assigned_role = (await session.execute(
        select(UserRole.user_id).where(UserRole.user_id == user.id).limit(1)
    )).scalar_one_or_none()
    if has_assigned_role is not None:
        return set()
    return set(legacy_permissions(user.role or "user"))


async def replace_user_roles(
    session: AsyncSession,
    target: User,
    role_names: set[str],
    assigned_by: User,
) -> None:
    roles = list((await session.execute(select(Role).where(Role.name.in_(role_names)))).scalars())
    if len(roles) != len(role_names):
        known = {role.name for role in roles}
        missing = sorted(role_names - known)
        raise ValueError(f"Unknown roles: {', '.join(missing)}")
    existing = list((await session.execute(select(UserRole).where(UserRole.user_id == target.id))).scalars())
    for item in existing:
        await session.delete(item)
    for role in roles:
        session.add(UserRole(user_id=target.id, role_id=role.id, assigned_by_user_id=assigned_by.id))
    target.role = "super_admin" if "super_admin" in role_names else sorted(role_names)[0]
    await session.flush()
