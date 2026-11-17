"""Shell endpoint: everything the web app needs to draw the frame for the current tenant.

TODO(identity): filter navigation and quick actions by the user's permissions once
identity and RBAC exist. Until then every enabled module is shown.
"""

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from heinzel_api.manifests import Manifest
from heinzel_api.tenants import TenantConfig, resolve_tenant

router = APIRouter(prefix="/api/v1")

ASSET_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
LANG = "de"


class NavItem(BaseModel):
    key: str
    label: str
    path: str
    icon: str | None = None
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


class Shell(BaseModel):
    tenant: str
    branding: ShellBranding
    navigation: list[NavSection]
    quick_actions: list[QuickAction]


def _text(value: dict[str, str]) -> str:
    return value.get(LANG) or next(iter(value.values()), "")


def _asset_url(tenant: TenantConfig, path: str | None) -> str | None:
    if not path:
        return None
    return f"/api/v1/tenants/{tenant.slug}/assets/{path.removeprefix('assets/')}"


def _module_item(manifest: Manifest, hidden: list[str]) -> NavItem:
    nav = manifest.navigation
    assert nav is not None
    children = [
        NavItem(key=c.path, label=_text(c.label), path=c.path, icon=c.icon)
        for c in nav.children
        if c.path not in hidden
    ]
    return NavItem(
        key=manifest.id,
        label=_text(nav.entry.label),
        path=nav.entry.path,
        icon=nav.entry.icon,
        children=children,
    )


def build_shell(tenant: TenantConfig, manifests: dict[str, Manifest]) -> Shell:
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
        item = _module_item(manifest, install.hidden_children)
        if install.area is None:
            top.append(item)
        elif install.area in by_area:
            by_area[install.area].append(item)
        for qa in manifest.contributes.get("quick_actions", []):
            quick_actions.append(
                QuickAction(
                    key=qa["key"], label=_text(qa["label"]), path=qa["path"], module=manifest.id
                )
            )

    sections = [NavSection(key="top", label=None, items=top)]
    for area in sorted(tenant.navigation.areas, key=lambda a: a.order):
        items = by_area[area.key]
        if items or not tenant.navigation.hide_empty_areas:
            sections.append(NavSection(key=area.key, label=_text(area.label), items=items))
    sections.append(
        NavSection(
            key="admin",
            label="Administration",
            items=[
                NavItem(
                    key="users", label="Benutzer & Rollen", path="/admin/benutzer", icon="users"
                ),
                NavItem(key="modules", label="Module", path="/admin/module", icon="grid"),
                NavItem(
                    key="settings",
                    label="Einstellungen",
                    path="/admin/einstellungen",
                    icon="sliders",
                ),
                NavItem(key="audit", label="Audit-Log", path="/admin/audit", icon="shield"),
            ],
        )
    )

    b = tenant.branding
    return Shell(
        tenant=tenant.slug,
        branding=ShellBranding(
            display_name=tenant.display_name,
            short_name=tenant.short_name,
            logo_light=_asset_url(tenant, b.logo_light) or "",
            logo_dark=_asset_url(tenant, b.logo_dark),
            logo_mark=_asset_url(tenant, b.logo_mark),
            primary=b.colors["primary"],
            accent=b.colors.get("accent", b.colors["primary"]),
            theme_default=b.theme_default,
            powered_by=b.powered_by,
        ),
        navigation=sections,
        quick_actions=quick_actions,
    )


@router.get("/shell", response_model=Shell)
def get_shell(request: Request) -> Shell:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    tenant = resolve_tenant(request.app.state.tenants, host)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Unknown tenant")
    return build_shell(tenant, request.app.state.manifests)


@router.get("/tenants/{slug}/assets/{name}")
def get_tenant_asset(slug: str, name: str, request: Request) -> FileResponse:
    tenant = request.app.state.tenants.get(slug)
    if tenant is None or not ASSET_NAME.match(name):
        raise HTTPException(status_code=404)
    base = (request.app.state.settings.tenants_dir / slug / "assets").resolve()
    path = (base / name).resolve()
    if path.parent != base or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path)
