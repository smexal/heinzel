"""Roles and permissions.

Permissions come from two places: the core catalogue below and the `permissions` of every
module manifest. Roles are per tenant and hold permission ids; the system role `admin`
holds the wildcard `*`. Module permissions name their default roles in the manifest
(`default_roles`), which seeds the system role `staff`.
"""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from heinzel_api.manifests import Manifest
from heinzel_api.models import PermissionSeeded, Role, RoleAssignment, RolePermission

WILDCARD = "*"

CORE_PERMISSIONS: dict[str, dict[str, str]] = {
    "core.users.manage": {"de": "Benutzer verwalten"},
    "core.roles.manage": {"de": "Rollen und Berechtigungen verwalten"},
    "core.modules.manage": {"de": "Module verwalten"},
    "core.settings.manage": {"de": "Einstellungen verwalten"},
    "core.audit.read": {"de": "Audit-Log einsehen"},
}

SYSTEM_ROLES: dict[str, dict[str, str]] = {
    "admin": {"name": "Administration", "description": "Alle Berechtigungen"},
    "staff": {"name": "Mitarbeitende", "description": "Standardrolle für alle Mitarbeitenden"},
}


def catalogue(manifests: dict[str, Manifest]) -> dict[str, dict[str, str]]:
    perms = dict(CORE_PERMISSIONS)
    for manifest in manifests.values():
        for p in manifest.permissions:
            perms[p.id] = p.label
    return perms


def defaults_for(role_key: str, manifests: dict[str, Manifest]) -> set[str]:
    if role_key == "admin":
        return {WILDCARD}
    return {p.id for m in manifests.values() for p in m.permissions if role_key in p.default_roles}


def ensure_system_roles(
    session: Session, tenant_id: UUID, manifests: dict[str, Manifest]
) -> dict[str, Role]:
    """Create missing system roles and apply manifest defaults for permissions this tenant
    has not seen yet (a newly installed module). Permissions an admin removed later stay
    removed: each default is applied once per tenant."""
    seen = set(
        session.scalars(
            select(PermissionSeeded.permission).where(PermissionSeeded.tenant_id == tenant_id)
        )
    )
    roles: dict[str, Role] = {}
    for key, meta in SYSTEM_ROLES.items():
        role = session.scalar(select(Role).where(Role.tenant_id == tenant_id, Role.key == key))
        if role is None:
            role = Role(tenant_id=tenant_id, key=key, is_system=True, **meta)
            session.add(role)
            session.flush()
        have = set(
            session.scalars(
                select(RolePermission.permission).where(RolePermission.role_id == role.id)
            )
        )
        for perm in sorted(defaults_for(key, manifests) - have - seen):
            session.add(RolePermission(tenant_id=tenant_id, role_id=role.id, permission=perm))
        roles[key] = role
    for perm in sorted(set(catalogue(manifests)) - seen):
        session.add(PermissionSeeded(tenant_id=tenant_id, permission=perm))
    session.flush()
    return roles


def assign_role(session: Session, tenant_id: UUID, user_id: UUID, role_id: UUID) -> None:
    exists = session.get(RoleAssignment, {"user_id": user_id, "role_id": role_id})
    if exists is None:
        session.add(RoleAssignment(tenant_id=tenant_id, user_id=user_id, role_id=role_id))
        session.flush()


def unassign_role(session: Session, user_id: UUID, role_id: UUID) -> None:
    session.execute(
        delete(RoleAssignment).where(
            RoleAssignment.user_id == user_id, RoleAssignment.role_id == role_id
        )
    )


def user_role_keys(session: Session, user_id: UUID) -> list[str]:
    return list(
        session.scalars(
            select(Role.key)
            .join(RoleAssignment, RoleAssignment.role_id == Role.id)
            .where(RoleAssignment.user_id == user_id)
            .order_by(Role.key)
        )
    )


def effective_permissions(
    session: Session, user_id: UUID, manifests: dict[str, Manifest]
) -> set[str]:
    """All permission ids the user holds, with the wildcard expanded to the catalogue."""
    granted = set(
        session.scalars(
            select(RolePermission.permission)
            .join(RoleAssignment, RoleAssignment.role_id == RolePermission.role_id)
            .where(RoleAssignment.user_id == user_id)
        )
    )
    known = set(catalogue(manifests))
    if WILDCARD in granted:
        return known
    return granted & known
