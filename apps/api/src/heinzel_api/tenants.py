"""Tenant configuration (tenants/<slug>/tenant.json) and resolution by host name."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

LocalizedText = dict[str, str]


class Branding(BaseModel):
    model_config = ConfigDict(extra="allow")

    logo_light: str
    logo_dark: str | None = None
    logo_mark: str | None = None
    colors: dict[str, str]
    theme_default: str = "system"
    powered_by: bool = True


class Area(BaseModel):
    key: str
    label: LocalizedText
    order: int = 0


class NavigationConfig(BaseModel):
    hide_empty_areas: bool = True
    areas: list[Area] = []


class ModuleInstall(BaseModel):
    key: str
    enabled: bool = True
    area: str | None = None
    hidden_children: list[str] = []


class Lockout(BaseModel):
    attempts: int = 5
    minutes: int = 15


class LocalIdentity(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    # all | admins | optional
    mfa_required: str = "all"
    password_min_length: int = Field(default=12, ge=8)
    self_service_reset: bool = True
    lockout: Lockout = Lockout()
    session_idle_hours: int = Field(default=8, ge=1, le=24 * 30)


class IdentityConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    local: LocalIdentity = LocalIdentity()
    providers: list[dict] = []


class TenantConfig(BaseModel):
    """Only the parts the core reads so far are typed; everything else is kept as-is."""

    model_config = ConfigDict(extra="allow")

    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,40}$")
    domains: list[str]
    display_name: str
    short_name: str
    branding: Branding
    navigation: NavigationConfig = NavigationConfig()
    identity: IdentityConfig = IdentityConfig()
    modules: list[ModuleInstall] = []


def load_tenants(tenants_dir: Path) -> dict[str, TenantConfig]:
    """Return tenants keyed by slug."""
    tenants: dict[str, TenantConfig] = {}
    for path in sorted(tenants_dir.glob("*/tenant.json")):
        tenant = TenantConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if tenant.slug != path.parent.name:
            raise ValueError(f"{path}: slug '{tenant.slug}' does not match folder")
        tenants[tenant.slug] = tenant
    return tenants


def resolve_tenant(tenants: dict[str, TenantConfig], host: str | None) -> TenantConfig | None:
    """Resolve a tenant from the request host (port is ignored)."""
    if not host:
        return None
    hostname = host.split(":")[0].lower()
    for tenant in tenants.values():
        if hostname in tenant.domains:
            return tenant
    return None
