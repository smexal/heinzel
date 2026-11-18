"""Shell endpoint: everything the web app needs to draw the frame for the current tenant.

Branding is public (the login page needs it). Navigation and quick actions are only
returned for a signed-in user and only contain what that user may open.
"""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from heinzel_api import localization
from heinzel_api.db import tenant_session
from heinzel_api.deps import OptionalPrincipalDep, tenant_config
from heinzel_api.manifests import Manifest
from heinzel_api.models import TenantAsset
from heinzel_api.routes.inbox import counts as inbox_counts
from heinzel_api.tenants import TenantConfig

router = APIRouter(prefix="/api/v1")

ASSET_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
LANG = "de"


class NavItem(BaseModel):
    key: str
    label: str
    path: str
    icon: str | None = None
    badge: int | None = None  # e.g. unread items in Mein Eingang
    children: list["NavItem"] = []


class NavSection(BaseModel):
    key: str
    label: str | None  # None = top section without heading
    items: list[NavItem]


class QuickAction(BaseModel):
    key: str
    label: str
    path: str
    module: str
    description: str | None = None
    icon: str | None = None


class ShellBranding(BaseModel):
    display_name: str
    short_name: str
    logo_light: str
    logo_dark: str | None
    logo_mark: str | None
    primary: str
    accent: str
    theme_default: str
    powered_by: bool
    imprint_url: str | None = None
    privacy_url: str | None = None


class ShellUser(BaseModel):
    id: str
    display_name: str
    email: str
    initials: str
    mfa_enabled: bool
    # Effective language and regional settings, for formatting in the client
    localization: dict[str, str]


class Shell(BaseModel):
    tenant: str
    branding: ShellBranding
    user: ShellUser | None
    navigation: list[NavSection]
    quick_actions: list[QuickAction]


def _text(value: dict[str, str]) -> str:
    return value.get(LANG) or next(iter(value.values()), "")


def _asset_url(tenant: TenantConfig, path: str | None) -> str | None:
    if not path:
        return None
    return f"/api/v1/tenants/{tenant.slug}/assets/{path.removeprefix('assets/')}"


ADMIN_ITEMS = [
    ("users", "Benutzer & Rollen", "/admin/benutzer", "users", "core.users.manage"),
    ("modules", "Module", "/admin/module", "grid", "core.modules.manage"),
    ("settings", "Einstellungen", "/admin/einstellungen", "sliders", "core.settings.manage"),
    ("audit", "Audit-Log", "/admin/audit", "shield", "core.audit.read"),
]


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def _module_item(manifest: Manifest, hidden: list[str], perms: set[str]) -> NavItem:
    nav = manifest.navigation
    assert nav is not None
    children = [
        NavItem(key=c.path, label=_text(c.label), path=c.path, icon=c.icon)
        for c in nav.children
        if c.path not in hidden and c.permission in perms
    ]
    return NavItem(
        key=manifest.id,
        label=_text(nav.entry.label),
        path=nav.entry.path,
        icon=nav.entry.icon,
        children=children,
    )


def build_shell(
    tenant: TenantConfig,
    manifests: dict[str, Manifest],
    permissions: set[str] | frozenset[str] | None,
    user: ShellUser | None = None,
) -> Shell:
    """permissions=None means anonymous: branding only."""
    if permissions is None:
        return Shell(
            tenant=tenant.slug,
            branding=_branding(tenant),
            user=None,
            navigation=[],
            quick_actions=[],
        )
    perms = set(permissions)
    top = [
        NavItem(key="home", label="Übersicht", path="/", icon="home"),
        NavItem(key="inbox", label="Mein Eingang", path="/eingang", icon="inbox"),
    ]
    by_area: dict[str, list[NavItem]] = {a.key: [] for a in tenant.navigation.areas}
    quick_actions: list[QuickAction] = []

    for install in tenant.modules:
        manifest = manifests.get(install.key)
        if not install.enabled or manifest is None or manifest.navigation is None:
            continue
        if manifest.navigation.entry.permission not in perms:
            continue
        item = _module_item(manifest, install.hidden_children, perms)
        if install.area is None:
            top.append(item)
        elif install.area in by_area:
            by_area[install.area].append(item)
        # Convention for module settings: quick_action_enabled switches its quick actions off.
        module_settings = {**manifest.settings_defaults(), **install.settings}
        if module_settings.get("quick_action_enabled", True) is False:
            continue
        for qa in manifest.contributes.get("quick_actions", []):
            if qa.get("permission", manifest.navigation.entry.permission) not in perms:
                continue
            quick_actions.append(
                QuickAction(
                    key=qa["key"],
                    label=_text(qa["label"]),
                    path=qa["path"],
                    module=manifest.id,
                    description=_text(qa["description"]) if qa.get("description") else None,
                    icon=qa.get("icon") or manifest.navigation.entry.icon,
                )
            )

    sections = [NavSection(key="top", label=None, items=top)]
    for area in sorted(tenant.navigation.areas, key=lambda a: a.order):
        items = by_area[area.key]
        if items or not tenant.navigation.hide_empty_areas:
            sections.append(NavSection(key=area.key, label=_text(area.label), items=items))
    admin = [
        NavItem(key=key, label=label, path=path, icon=icon)
        for key, label, path, icon, perm in ADMIN_ITEMS
        if perm in perms
    ]
    if admin:
        sections.append(NavSection(key="admin", label="Administration", items=admin))

    return Shell(
        tenant=tenant.slug,
        branding=_branding(tenant),
        user=user,
        navigation=sections,
        quick_actions=quick_actions,
    )


def _branding(tenant: TenantConfig) -> ShellBranding:
    b = tenant.branding
    legal = (tenant.model_extra or {}).get("legal") or {}
    return ShellBranding(
        display_name=tenant.display_name,
        short_name=tenant.short_name,
        logo_light=_asset_url(tenant, b.logo_light) or "",
        logo_dark=_asset_url(tenant, b.logo_dark),
        logo_mark=_asset_url(tenant, b.logo_mark),
        primary=b.colors["primary"],
        accent=b.colors.get("accent", b.colors["primary"]),
        theme_default=b.theme_default,
        powered_by=b.powered_by,
        imprint_url=legal.get("imprint_url"),
        privacy_url=legal.get("privacy_url"),
    )


@router.get("/shell", response_model=Shell)
def get_shell(
    request: Request,
    tenant: Annotated[TenantConfig, Depends(tenant_config)],
    p: OptionalPrincipalDep,
) -> Shell:
    if p is None or not p.mfa_passed:
        return build_shell(tenant, request.app.state.manifests, None)
    user = ShellUser(
        id=str(p.user_id),
        display_name=p.display_name,
        email=p.email,
        initials=_initials(p.display_name),
        mfa_enabled=p.mfa_enabled,
        localization=localization.effective(tenant, p.preferences),
    )
    shell = build_shell(tenant, request.app.state.manifests, p.permissions, user)
    with tenant_session(request.app.state.db, p.tenant_id) as s:
        unread = inbox_counts(s, p.user_id)["unread"]
    for section in shell.navigation:
        for item in section.items:
            if item.key == "inbox":
                item.badge = unread or None
    return shell


@router.get("/tenants/{slug}/assets/{name}")
def get_tenant_asset(slug: str, name: str, request: Request) -> Response:
    """Public: the login page shows the logo. Served with a sandbox CSP, so an uploaded SVG
    can never run script on the portal's origin."""
    entry = request.app.state.registry.by_slug(slug)
    if entry is None or not ASSET_NAME.match(name):
        raise HTTPException(status_code=404)
    with tenant_session(request.app.state.db, entry.id) as s:
        asset = s.get(TenantAsset, {"tenant_id": entry.id, "name": name})
        if asset is None:
            raise HTTPException(status_code=404)
        data, ctype, etag = asset.data, asset.content_type, asset.sha256[:16]
    if request.headers.get("if-none-match") == f'"{etag}"':
        return Response(status_code=304)
    return Response(
        content=data,
        media_type=ctype,
        headers={
            "ETag": f'"{etag}"',
            "Cache-Control": "public, max-age=300",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )
