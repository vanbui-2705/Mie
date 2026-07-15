"""Idempotent RBAC catalog seeding for tests and controlled bootstrap flows."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sqlmodels import Permission, Role, RolePermission, User, UserRole
from app.rbac_catalog import PERMISSIONS, ROLE_DEFINITIONS, split_permission


async def seed_rbac(session: AsyncSession, *, assign_legacy_users: bool = True) -> None:
    permissions = {row.code: row for row in (await session.execute(select(Permission))).scalars()}
    for code in PERMISSIONS:
        if code not in permissions:
            resource, action = split_permission(code)
            item = Permission(code=code, resource=resource, action=action, is_system=True)
            session.add(item)
            permissions[code] = item

    roles = {row.name: row for row in (await session.execute(select(Role))).scalars()}
    for name, definition in ROLE_DEFINITIONS.items():
        if name not in roles:
            item = Role(
                name=name,
                display_name=str(definition["display_name"]),
                description=str(definition["description"]),
                is_system=True,
            )
            session.add(item)
            roles[name] = item
    await session.flush()

    for name, definition in ROLE_DEFINITIONS.items():
        role = roles[name]
        desired = set(definition["permissions"])
        await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        for code in desired:
            session.add(RolePermission(role_id=role.id, permission_id=permissions[code].id))

    if assign_legacy_users:
        users = list((await session.execute(select(User).order_by(User.created_at, User.id))).scalars())
        assigned = set((await session.execute(select(UserRole.user_id))).scalars())
        first_admin_assigned = False
        for user in users:
            if user.id in assigned:
                continue
            role_name = user.role if user.role in roles else "user"
            if role_name == "admin" and not first_admin_assigned:
                role_name = "super_admin"
                first_admin_assigned = True
                user.role = "super_admin"
            session.add(UserRole(user_id=user.id, role_id=roles[role_name].id))
    await session.flush()
