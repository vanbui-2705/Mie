"""Role, permission and user-role administration endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_session
from app.models.sqlmodels import Permission, Role, RolePermission, User, UserRole
from app.rbac import has_permission, require_permission
from app.services.permission_service import permission_codes_for_user, replace_user_roles, role_codes_for_user

router = APIRouter(prefix="/api", tags=["rbac"])


async def _role_response(session: AsyncSession, role: Role) -> dict:
    codes = list((await session.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role.id)
        .order_by(Permission.code)
    )).scalars())
    return {
        "id": str(role.id), "name": role.name, "display_name": role.display_name,
        "description": role.description, "is_system": role.is_system, "permissions": codes,
    }


@router.get("/roles", response_model=list[dict])
async def list_roles(
    actor: User = Depends(require_permission("role:read")),
    session: AsyncSession = Depends(get_session),
):
    roles = list((await session.execute(select(Role).order_by(Role.name))).scalars())
    return [await _role_response(session, role) for role in roles]


@router.post("/roles", response_model=dict, status_code=201)
async def create_role(
    body: dict,
    actor: User = Depends(require_permission("role:create")),
    session: AsyncSession = Depends(get_session),
):
    name = str(body.get("name") or "").strip().lower()
    if not name or not name.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid role name")
    if (await session.execute(select(Role.id).where(Role.name == name))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Role already exists")
    role = Role(
        name=name,
        display_name=str(body.get("display_name") or name.replace("_", " ").title()),
        description=str(body.get("description") or "") or None,
        is_system=False,
    )
    session.add(role)
    await session.flush()
    return await _role_response(session, role)


@router.patch("/roles/{role_id}", response_model=dict)
async def update_role(
    role_id: uuid.UUID,
    body: dict,
    actor: User = Depends(require_permission("role:update")),
    session: AsyncSession = Depends(get_session),
):
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=409, detail="System roles cannot be edited")
    if "display_name" in body:
        role.display_name = str(body["display_name"]).strip() or role.display_name
    if "description" in body:
        role.description = str(body["description"]).strip() or None
    await session.flush()
    return await _role_response(session, role)


@router.delete("/roles/{role_id}", response_model=dict)
async def delete_role(
    role_id: uuid.UUID,
    actor: User = Depends(require_permission("role:delete")),
    session: AsyncSession = Depends(get_session),
):
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=409, detail="System roles cannot be deleted")
    await session.delete(role)
    return {"deleted": True, "id": str(role_id)}


@router.get("/permissions", response_model=list[dict])
async def list_permissions(
    actor: User = Depends(require_permission("permission:read")),
    session: AsyncSession = Depends(get_session),
):
    rows = list((await session.execute(select(Permission).order_by(Permission.code))).scalars())
    return [{"id": str(row.id), "code": row.code, "resource": row.resource, "action": row.action, "description": row.description} for row in rows]


@router.put("/roles/{role_id}/permissions", response_model=dict)
async def set_role_permissions(
    role_id: uuid.UUID,
    body: dict,
    actor: User = Depends(require_permission("permission:assign")),
    session: AsyncSession = Depends(get_session),
):
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=409, detail="System role permissions are catalog-managed")
    codes = {str(code) for code in body.get("permissions", [])}
    permissions = list((await session.execute(select(Permission).where(Permission.code.in_(codes)))).scalars()) if codes else []
    if len(permissions) != len(codes):
        raise HTTPException(status_code=400, detail="Unknown permission code")
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for permission in permissions:
        session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    await session.flush()
    return await _role_response(session, role)


@router.get("/users/{user_id}/roles", response_model=dict)
async def get_user_roles(
    user_id: uuid.UUID,
    actor: User = Depends(require_permission("role:read")),
    session: AsyncSession = Depends(get_session),
):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": str(user_id), "roles": sorted(await role_codes_for_user(session, target))}


@router.put("/users/{user_id}/roles", response_model=dict)
async def set_user_roles(
    user_id: uuid.UUID,
    body: dict,
    actor: User = Depends(require_permission("permission:assign")),
    session: AsyncSession = Depends(get_session),
):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    role_names = {str(name) for name in body.get("roles", [])}
    if not role_names:
        raise HTTPException(status_code=400, detail="At least one role is required")
    if target.id == actor.id and role_names != await role_codes_for_user(session, target):
        raise HTTPException(status_code=409, detail="Users cannot change their own roles")
    if "super_admin" in role_names and not await has_permission(session, actor, "tenant:manage:any"):
        raise HTTPException(status_code=403, detail="Only a super administrator can assign super_admin")
    current = await role_codes_for_user(session, target)
    if "super_admin" in current and "super_admin" not in role_names:
        count = await session.scalar(
            select(func.count()).select_from(UserRole).join(Role).where(Role.name == "super_admin")
        )
        if int(count or 0) <= 1:
            raise HTTPException(status_code=409, detail="Cannot remove the last super administrator")
    try:
        await replace_user_roles(session, target, role_names, actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user_id": str(user_id), "roles": sorted(role_names)}


@router.get("/auth/me/permissions", response_model=dict)
async def my_permissions(
    actor: User = Depends(require_permission("facebook_account:read")),
    session: AsyncSession = Depends(get_session),
):
    return {
        "roles": sorted(await role_codes_for_user(session, actor)),
        "permissions": sorted(await permission_codes_for_user(session, actor)),
    }
