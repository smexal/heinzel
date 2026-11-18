"""Tenant configuration (tenants/<slug>/tenant.json) and resolution by host name."""

import json
import threading
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from heinzel_api.db import global_session, tenant_session
from heinzel_api.models import Tenant, TenantSettings

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
    # Values for the module's settings.schema.json (missing keys use the schema defaults)
    settings: dict = {}
    # MCP tools and prompts this tenant switched off for AI clients
    mcp_disabled: list[str] = []


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


# --- Runtime registry (database) ----------------------------------------------------------


class TenantEntry:
    __slots__ = ("id", "config", "version")

    def __init__(self, id, config: TenantConfig, version: int):  # noqa: A002
        self.id = id
        self.config = config
        self.version = version


class TenantRegistry:
    """Active tenants with their settings, loaded from the database and cached briefly.

    Host resolution needs every tenant's domains before a tenant is known, so the registry
    reads the global tenant table, then each tenant's settings inside its own RLS scope.
    A settings change calls invalidate(); other API processes pick it up within `ttl`.
    """

    def __init__(self, factory, ttl: float = 30.0):
        self._factory = factory
        self._ttl = ttl
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self._by_slug: dict[str, TenantEntry] = {}
        self._by_domain: dict[str, TenantEntry] = {}

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0

    def _ensure(self) -> None:
        if time.monotonic() - self._loaded_at < self._ttl:
            return
        with self._lock:
            if time.monotonic() - self._loaded_at < self._ttl:
                return
            self._load()
            self._loaded_at = time.monotonic()

    def _load(self) -> None:
        with global_session(self._factory) as s:
            rows = list(
                s.execute(
                    select(Tenant.id, Tenant.slug, Tenant.domains).where(Tenant.status == "active")
                )
            )
        by_slug: dict[str, TenantEntry] = {}
        by_domain: dict[str, TenantEntry] = {}
        for tid, slug, domains in rows:
            with tenant_session(self._factory, tid) as s:
                settings = s.get(TenantSettings, tid)
            if settings is None:
                continue  # registered but not seeded yet
            config = TenantConfig.model_validate(
                {**settings.config, "slug": slug, "domains": list(domains)}
            )
            entry = TenantEntry(tid, config, settings.version)
            by_slug[slug] = entry
            for d in domains:
                by_domain[d.lower()] = entry
        self._by_slug, self._by_domain = by_slug, by_domain

    def resolve(self, host: str | None) -> TenantEntry | None:
        if not host:
            return None
        self._ensure()
        return self._by_domain.get(host.split(":")[0].lower())

    def by_slug(self, slug: str) -> TenantEntry | None:
        self._ensure()
        return self._by_slug.get(slug)
