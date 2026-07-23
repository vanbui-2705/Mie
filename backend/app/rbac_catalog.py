"""Version-controlled RBAC permission and default-role catalog."""
from __future__ import annotations

PERMISSIONS: tuple[str, ...] = (
    "user:read", "user:create", "user:update", "user:disable", "user:delete",
    "role:read", "role:create", "role:update", "role:delete",
    "permission:read", "permission:assign",
    "facebook_account:read", "facebook_account:create", "facebook_account:update",
    "facebook_account:delete", "facebook_account:check", "facebook_account:sync",
    "facebook_account:read:any", "facebook_account:update:any", "facebook_account:delete:any",
    "facebook_page:read", "facebook_page:post",
    "facebook_group:read", "facebook_group:share",
    "task:read", "task:create", "task:cancel", "task:delete",
    "task:read:any", "task:cancel:any",
    "scheduled_post:read", "scheduled_post:create", "scheduled_post:update", "scheduled_post:delete",
    "google_sheet:read", "google_sheet:create", "google_sheet:update", "google_sheet:delete",
    "rental:read", "rental:create", "rental:update", "rental:delete",
    "proxy:read", "proxy:manage", "settings:read", "settings:update",
    "browser_session:read", "browser_session:manage",
    "audit_log:read", "tenant:read:any", "tenant:manage:any",
)

OWN_RESOURCE_PERMISSIONS = frozenset(
    code for code in PERMISSIONS
    if not code.endswith(":any")
    and not code.startswith(("user:", "role:", "permission:", "audit_log:"))
)

ROLE_DEFINITIONS: dict[str, dict[str, object]] = {
    "user": {
        "display_name": "User",
        "description": "Manage only the signed-in user's own resources.",
        "permissions": OWN_RESOURCE_PERMISSIONS,
    },
    "staff": {
        "display_name": "Staff",
        "description": "Operate assigned automation resources without administration rights.",
        "permissions": OWN_RESOURCE_PERMISSIONS,
    },
    "manager": {
        "display_name": "Manager",
        "description": "Manage the signed-in user's automation resources and schedules.",
        "permissions": OWN_RESOURCE_PERMISSIONS,
    },
    "admin": {
        "display_name": "Administrator",
        "description": "Manage users and roles without implicit cross-tenant data access.",
        "permissions": OWN_RESOURCE_PERMISSIONS | {
            "user:read", "user:create", "user:update", "user:disable", "user:delete",
            "role:read", "permission:read", "permission:assign",
        },
    },
    "super_admin": {
        "display_name": "Super Administrator",
        "description": "Bootstrap owner with explicit cross-tenant permissions.",
        "permissions": frozenset(PERMISSIONS),
    },
}


def split_permission(code: str) -> tuple[str, str]:
    resource, action = code.split(":", 1)
    return resource, action


def legacy_permissions(role: str) -> frozenset[str]:
    definition = ROLE_DEFINITIONS.get(role) or ROLE_DEFINITIONS["user"]
    return frozenset(definition["permissions"])
