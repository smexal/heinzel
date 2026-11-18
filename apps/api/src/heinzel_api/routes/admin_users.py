"""Administration: users and roles (permission core.users.manage).

Guard rails:
- Nobody can hand out a role that carries permissions they do not hold themselves.
- The last active administrator cannot be deactivated or lose the admin role.
- Administrators cannot deactivate themselves.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from heinzel_api import audit, identity, mail, rbac
from heinzel_api.db import tenant_session
from heinzel_api.deps import (
    DbDep,
    ManifestsDep,
    Principal,
    TenantContext,
    TenantDep,
    client_ip,
    public_url,
    require,
)
from heinzel_api.models import ActionToken, Role, RoleAssignment, RolePermission, User

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

UsersAdmin = Annotated[Principal, Depends(require("core.users.manage"))]


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    status: str
    roles: list[str]
    mfa_enabled: bool
    has_password: bool
    last_login_at: datetime | None
    created_at: datetime
    invite_expires_at: datetime | None


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=200)
    roles: list[str] = ["staff"]


class InviteOut(BaseModel):
    user: UserOut
    mail_sent: bool


class RolesIn(BaseModel):
    roles: list[str]


class MailOut(BaseModel):
    mail_sent: bool


class PermissionOut(BaseModel):
    id: str
    label: str
    group: str  # "core" or the module id
    group_label: str


class RoleOut(BaseModel):
    key: str
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]  # expanded: the wildcard becomes the whole catalogue
    members: int


class RolesOut(BaseModel):
    roles: list[RoleOut]
    permissions: list[PermissionOut]


# --- helpers ------------------------------------------------------------------------------


def _user_out(s: Session, user: User) -> UserOut:
    invite = None
    if user.status == "invited":
        invite = s.scalar(
            select(ActionToken.expires_at).where(
                ActionToken.user_id == user.id,
                ActionToken.purpose == "invite",
                ActionToken.used_at.is_(None),
            )
        )
    return UserOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        roles=rbac.user_role_keys(s, user.id),
        mfa_enabled=user.mfa_enabled,
        has_password=user.password_hash is not None,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        invite_expires_at=invite,
    )


def _get_user(s: Session, user_id: UUID) -> User:
    user = s.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return user


def _role_permissions(s: Session, role: Role, manifests) -> set[str]:
    perms = set(
        s.scalars(select(RolePermission.permission).where(RolePermission.role_id == role.id))
    )
    known = set(rbac.catalogue(manifests))
    return known if rbac.WILDCARD in perms else perms & known


def _resolve_roles(s: Session, keys: list[str], actor: Principal, manifests) -> list[Role]:
    roles = list(s.scalars(select(Role).where(Role.key.in_(keys))))
    if {r.key for r in roles} != set(keys):
        raise HTTPException(status_code=422, detail="unknown_role")
    for role in roles:
        if not _role_permissions(s, role, manifests) <= actor.permissions:
            raise HTTPException(status_code=403, detail="role_exceeds_own_permissions")
    return roles


def _active_admins(s: Session) -> set[UUID]:
    return set(
        s.scalars(
            select(User.id)
            .join(RoleAssignment, RoleAssignment.user_id == User.id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(Role.key == "admin", User.status == "active")
        )
    )


def _send_invite(
    request: Request, tenant: TenantContext, s: Session, user: User, actor: Principal
) -> mail.Mail:
    token = identity.issue_action_token(s, user, "invite", created_by=actor.user_id)
    return mail.invite_mail(
        tenant.config,
        user.email,
        user.display_name,
        actor.display_name,
        public_url(request, f"/konto/{token}"),
        identity.INVITE_TTL.days,
    )


# --- users --------------------------------------------------------------------------------


@router.get("/users", response_model=list[UserOut])
def list_users(actor: UsersAdmin, tenant: TenantDep, db: DbDep) -> list[UserOut]:
    with tenant_session(db, tenant.id) as s:
        users = s.scalars(select(User).order_by(func.lower(User.display_name)))
        return [_user_out(s, u) for u in users]


@router.post("/users", response_model=InviteOut, status_code=201)
def invite_user(
    body: InviteIn,
    request: Request,
    actor: UsersAdmin,
    tenant: TenantDep,
    db: DbDep,
    manifests: ManifestsDep,
) -> InviteOut:
    try:
        with tenant_session(db, tenant.id) as s:
            if identity.find_user(s, body.email):
                raise HTTPException(status_code=409, detail="email_exists")
            roles = _resolve_roles(s, sorted(set(body.roles)), actor, manifests)
            user = identity.create_user(
                s, tenant.id, body.email, body.display_name, tenant.policy, status="invited"
            )
            for role in roles:
                rbac.assign_role(s, tenant.id, user.id, role.id)
            outgoing = _send_invite(request, tenant, s, user, actor)
            audit.record(
                s,
                tenant.id,
                "user.invited",
                actor_user_id=actor.user_id,
                target_type="user",
                target_id=str(user.id),
                data={"email": user.email, "roles": [r.key for r in roles]},
                ip=client_ip(request),
            )
            out = _user_out(s, user)
    except IntegrityError as e:  # concurrent invite of the same address
        raise HTTPException(status_code=409, detail="email_exists") from e
    sent = request.app.state.mailer.send(tenant.config, outgoing)
    return InviteOut(user=out, mail_sent=sent)


@router.post("/users/{user_id}/invite", response_model=MailOut)
def resend_invite(
    user_id: UUID, request: Request, actor: UsersAdmin, tenant: TenantDep, db: DbDep
) -> MailOut:
    with tenant_session(db, tenant.id) as s:
        user = _get_user(s, user_id)
        if user.status != "invited":
            raise HTTPException(status_code=409, detail="not_invited")
        outgoing = _send_invite(request, tenant, s, user, actor)
        audit.record(
            s,
            tenant.id,
            "user.invite_resent",
            actor_user_id=actor.user_id,
            target_type="user",
            target_id=str(user.id),
            ip=client_ip(request),
        )
    return MailOut(mail_sent=request.app.state.mailer.send(tenant.config, outgoing))


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: UUID, request: Request, actor: UsersAdmin, tenant: TenantDep, db: DbDep
) -> UserOut:
    if user_id == actor.user_id:
        raise HTTPException(status_code=409, detail="cannot_deactivate_self")
    with tenant_session(db, tenant.id) as s:
        user = _get_user(s, user_id)
        if _active_admins(s) == {user.id}:
            raise HTTPException(status_code=409, detail="last_admin")
        user.status = "deactivated"
        identity.end_all_sessions(s, user.id)
        audit.record(
            s,
            tenant.id,
            "user.deactivated",
            actor_user_id=actor.user_id,
            target_type="user",
            target_id=str(user.id),
            ip=client_ip(request),
        )
        s.flush()
        return _user_out(s, user)


@router.post("/users/{user_id}/activate", response_model=UserOut)
def activate_user(
    user_id: UUID, request: Request, actor: UsersAdmin, tenant: TenantDep, db: DbDep
) -> UserOut:
    with tenant_session(db, tenant.id) as s:
        user = _get_user(s, user_id)
        if user.status != "deactivated":
            raise HTTPException(status_code=409, detail="not_deactivated")
        # Someone who never set a password goes back to "invited" and needs a new link.
        user.status = "active" if user.password_hash else "invited"
        audit.record(
            s,
            tenant.id,
            "user.activated_by_admin",
            actor_user_id=actor.user_id,
            target_type="user",
            target_id=str(user.id),
            ip=client_ip(request),
        )
        s.flush()
        return _user_out(s, user)


@router.post("/users/{user_id}/mfa-reset", response_model=UserOut)
def reset_user_mfa(
    user_id: UUID, request: Request, actor: UsersAdmin, tenant: TenantDep, db: DbDep
) -> UserOut:
    with tenant_session(db, tenant.id) as s:
        user = _get_user(s, user_id)
        identity.reset_mfa(s, user)
        audit.record(
            s,
            tenant.id,
            "user.mfa_reset",
            actor_user_id=actor.user_id,
            target_type="user",
            target_id=str(user.id),
            ip=client_ip(request),
        )
        return _user_out(s, user)


@router.put("/users/{user_id}/roles", response_model=UserOut)
def set_user_roles(
    user_id: UUID,
    body: RolesIn,
    request: Request,
    actor: UsersAdmin,
    tenant: TenantDep,
    db: DbDep,
    manifests: ManifestsDep,
) -> UserOut:
    with tenant_session(db, tenant.id) as s:
        user = _get_user(s, user_id)
        before = set(rbac.user_role_keys(s, user.id))
        wanted = set(body.roles)
        # Only roles that change are checked against the actor's own permissions.
        changed = _resolve_roles(s, sorted(wanted ^ before), actor, manifests)
        all_roles = {r.key: r for r in s.scalars(select(Role))}
        if "admin" in before and "admin" not in wanted and _active_admins(s) == {user.id}:
            raise HTTPException(status_code=409, detail="last_admin")
        for role in changed:
            if role.key in wanted:
                rbac.assign_role(s, tenant.id, user.id, role.id)
            else:
                rbac.unassign_role(s, user.id, all_roles[role.key].id)
        audit.record(
            s,
            tenant.id,
            "user.roles_changed",
            actor_user_id=actor.user_id,
            target_type="user",
            target_id=str(user.id),
            data={"added": sorted(wanted - before), "removed": sorted(before - wanted)},
            ip=client_ip(request),
        )
        s.flush()
        return _user_out(s, user)


# --- roles (read-only for now) ------------------------------------------------------------


@router.get("/roles", response_model=RolesOut)
def list_roles(
    actor: UsersAdmin, tenant: TenantDep, db: DbDep, manifests: ManifestsDep
) -> RolesOut:
    catalogue = rbac.catalogue(manifests)

    def _de(text: dict[str, str], fallback: str) -> str:
        return text.get("de") or next(iter(text.values()), fallback)

    def _group_label(group: str) -> str:
        if group == "core":
            return "Plattform"
        manifest = manifests.get(group)
        return f"Modul {_de(manifest.name, group)}" if manifest else group

    perms = [
        PermissionOut(
            id=pid,
            label=_de(label, pid),
            group=pid.split(".")[0],
            group_label=_group_label(pid.split(".")[0]),
        )
        for pid, label in catalogue.items()
    ]
    with tenant_session(db, tenant.id) as s:
        counts = dict(
            s.execute(
                select(RoleAssignment.role_id, func.count())
                .join(User, User.id == RoleAssignment.user_id)
                .where(User.status != "deactivated")
                .group_by(RoleAssignment.role_id)
            ).all()
        )
        roles = [
            RoleOut(
                key=r.key,
                name=r.name,
                description=r.description,
                is_system=r.is_system,
                permissions=sorted(_role_permissions(s, r, manifests)),
                members=counts.get(r.id, 0),
            )
            for r in s.scalars(select(Role).order_by(Role.is_system.desc(), Role.name))
        ]
    return RolesOut(roles=roles, permissions=perms)
