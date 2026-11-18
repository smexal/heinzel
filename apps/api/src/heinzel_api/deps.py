"""Request context: tenant, database and the signed-in user."""

import ipaddress
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from heinzel_api import identity, rbac
from heinzel_api.db import global_session, tenant_session
from heinzel_api.manifests import Manifest
from heinzel_api.models import Tenant
from heinzel_api.ratelimit import Limit
from heinzel_api.tenants import TenantConfig, resolve_tenant

SESSION_COOKIE = "heinzel_session"


@dataclass(frozen=True)
class TenantContext:
    id: UUID
    config: TenantConfig

    @property
    def policy(self):
        return self.config.identity.local


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    session_id: UUID
    email: str
    display_name: str
    mfa_passed: bool
    mfa_enabled: bool
    roles: list[str] = field(default_factory=list)
    permissions: frozenset[str] = frozenset()
    preferences: dict = field(default_factory=dict)

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def request_host(request: Request) -> str | None:
    return request.headers.get("x-forwarded-host") or request.headers.get("host")


def client_ip(request: Request) -> str | None:
    """Client address; behind the reverse proxy the first X-Forwarded-For entry.
    Returns None for anything that is not an IP address."""
    forwarded = request.headers.get("x-forwarded-for")
    raw = forwarded.split(",")[0].strip() if forwarded else None
    if not raw and request.client:
        raw = request.client.host
    try:
        return str(ipaddress.ip_address(raw)) if raw else None
    except ValueError:
        return None


def public_url(request: Request, path: str) -> str:
    """Absolute link for e-mails. The host is one of the tenant's domains (the tenant was
    resolved from it), so a forged Host header cannot point links elsewhere."""
    host = request_host(request) or "localhost"
    scheme = "https" if request.app.state.settings.secure_cookies else "http"
    return f"{scheme}://{host}{path}"


def rate_limit(request: Request, limit: Limit, tenant_slug: str) -> None:
    retry = request.app.state.ratelimiter.hit(limit, f"{tenant_slug}:{client_ip(request)}")
    if retry is not None:
        raise HTTPException(
            status_code=429, detail="rate_limited", headers={"Retry-After": str(retry)}
        )


def db_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.db


def manifests(request: Request) -> dict[str, Manifest]:
    return request.app.state.manifests


def tenant_config(request: Request) -> TenantConfig:
    config = resolve_tenant(request.app.state.tenants, request_host(request))
    if config is None:
        raise HTTPException(status_code=404, detail="unknown_tenant")
    return config


def current_tenant(
    request: Request, config: Annotated[TenantConfig, Depends(tenant_config)]
) -> TenantContext:
    cache: dict[str, UUID] = request.app.state.tenant_ids
    tenant_id = cache.get(config.slug)
    if tenant_id is None:
        with global_session(db_factory(request)) as s:
            tenant_id = s.scalar(select(Tenant.id).where(Tenant.slug == config.slug))
        if tenant_id is None:
            # tenant.json exists, but `heinzel seed-tenants` has not been run
            raise HTTPException(status_code=503, detail="tenant_not_provisioned")
        cache[config.slug] = tenant_id
    return TenantContext(tenant_id, config)


def optional_principal(
    request: Request, tenant: Annotated[TenantContext, Depends(current_tenant)]
) -> Principal | None:
    """The session owner, including sessions still waiting for the second factor."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with tenant_session(db_factory(request), tenant.id) as s:
        active = identity.load_session(s, token, tenant.policy)
        if active is None:
            return None
        user = active.user
        perms = (
            rbac.effective_permissions(s, user.id, manifests(request))
            if active.session.mfa_passed
            else set()
        )
        return Principal(
            user_id=user.id,
            tenant_id=tenant.id,
            session_id=active.session.id,
            email=user.email,
            display_name=user.display_name,
            mfa_passed=active.session.mfa_passed,
            mfa_enabled=user.mfa_enabled,
            roles=rbac.user_role_keys(s, user.id),
            permissions=frozenset(perms),
            preferences=dict(user.preferences),
        )


def principal(
    p: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    """A fully signed-in user (password and, where required, second factor)."""
    if p is None or not p.mfa_passed:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return p


def require(permission: str):
    def _check(p: Annotated[Principal, Depends(principal)]) -> Principal:
        if not p.can(permission):
            raise HTTPException(status_code=403, detail="forbidden")
        return p

    return _check


TenantDep = Annotated[TenantContext, Depends(current_tenant)]
PrincipalDep = Annotated[Principal, Depends(principal)]
OptionalPrincipalDep = Annotated[Principal | None, Depends(optional_principal)]
DbDep = Annotated[sessionmaker[Session], Depends(db_factory)]
ManifestsDep = Annotated[dict[str, Manifest], Depends(manifests)]
