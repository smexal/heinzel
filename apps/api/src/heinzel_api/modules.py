"""In-process module host.

A module is a folder `modules/<id>/` with its manifest (heinzel.module.yaml) and, for modules
with backend code, a Python package `backend/` whose `__init__.py` defines

    def setup(host: ModuleHost) -> None

`setup` adds the module's API router, home widgets and scheduled jobs through the host, and
registers search providers, file access checks, inbox actions and event handlers with the
core services directly. The package is imported as `heinzel_modules.<id>` (relative imports
work inside it). Its database migrations live in `backend/migrations/` with their own version
table in the module's schema `mod_<id>` (see heinzel_api.migrate).

Routes are mounted under `/api/v1/<id>/` and answer 404 `module_disabled` while the module is
switched off for the requesting tenant. Permissions are checked by the module's own routes.
"""

import importlib.util
import sys
import types
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from heinzel_api.manifests import Manifest
from heinzel_api.tenants import ModuleInstall, TenantConfig

PACKAGE = "heinzel_modules"


# --- per-tenant state of a module -------------------------------------------------------------


def install(tenant: TenantConfig, module_id: str) -> ModuleInstall | None:
    return next((m for m in tenant.modules if m.key == module_id), None)


def is_enabled(tenant: TenantConfig, module_id: str) -> bool:
    inst = install(tenant, module_id)
    return inst is not None and inst.enabled


def settings_for(tenant: TenantConfig, manifest: Manifest) -> dict[str, Any]:
    """The module's settings for this tenant, schema defaults filled in."""
    inst = install(tenant, manifest.id)
    return {**manifest.settings_defaults(), **(inst.settings if inst else {})}


# --- home widgets -----------------------------------------------------------------------------


class WidgetItem(BaseModel):
    title: str
    meta: str | None = None
    tone: str | None = None  # danger | warn | None: colour of the meta line
    href: str | None = None


class Widget(BaseModel):
    key: str
    module: str
    eyebrow: str
    title: str
    link_label: str | None = None
    link: str | None = None
    items: list[WidgetItem]
    empty: str = "Nichts zu tun."


@dataclass
class WidgetContext:
    session: Session
    tenant_id: uuid.UUID
    tenant: TenantConfig
    user_id: uuid.UUID
    permissions: frozenset[str]
    localization: dict[str, str]
    settings: dict[str, Any]


WidgetFn = Callable[[WidgetContext], Widget | None]


# --- scheduled jobs ---------------------------------------------------------------------------


@dataclass
class Job:
    name: str
    every_seconds: int
    run: Callable[["JobContext"], Any]


@dataclass
class JobContext:
    """What a job gets: database (runtime role, RLS per tenant), tenants, mailer, storage."""

    db: Any
    tenants: list[Any]  # TenantEntry
    manifests: dict[str, Manifest]
    mailer: Any
    storage: Any
    settings: Any


# --- host ------------------------------------------------------------------------------------


@dataclass
class ModuleHost:
    manifest: Manifest
    path: Path
    routers: list[APIRouter] = field(default_factory=list)
    widgets: dict[str, WidgetFn] = field(default_factory=dict)
    jobs: list[Job] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.manifest.id

    def add_router(self, router: APIRouter) -> None:
        self.routers.append(router)

    def add_widget(self, key: str, fn: WidgetFn) -> None:
        declared = self.manifest.contributes.get("dashboard_widgets", [])
        if key not in declared:
            raise ValueError(f"widget '{key}' is not declared in the manifest of '{self.id}'")
        self.widgets[key] = fn

    def add_job(self, name: str, every_seconds: int, run: Callable[[JobContext], Any]) -> None:
        self.jobs.append(Job(f"{self.id}.{name}", every_seconds, run))

    @property
    def migrations_dir(self) -> Path | None:
        d = self.path / "backend" / "migrations"
        return d if (d / "env.py").is_file() else None


def _import_backend(module_id: str, backend: Path) -> types.ModuleType:
    name = f"{PACKAGE}.{module_id.replace('-', '_')}"
    if name in sys.modules:
        return sys.modules[name]
    if PACKAGE not in sys.modules:
        pkg = types.ModuleType(PACKAGE)
        pkg.__path__ = []
        sys.modules[PACKAGE] = pkg
    spec = importlib.util.spec_from_file_location(
        name, backend / "__init__.py", submodule_search_locations=[str(backend)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[name]
        raise
    return module


def load_modules(manifests: dict[str, Manifest], modules_dir: Path) -> dict[str, ModuleHost]:
    """Import every module with a backend package and run its setup()."""
    hosts: dict[str, ModuleHost] = {}
    for module_id, manifest in manifests.items():
        path = modules_dir / module_id
        host = ModuleHost(manifest, path)
        backend = path / "backend"
        if (backend / "__init__.py").is_file():
            package = _import_backend(module_id, backend)
            setup = getattr(package, "setup", None)
            if setup is None:
                raise ValueError(f"module '{module_id}': backend has no setup(host)")
            setup(host)
        hosts[module_id] = host
    return hosts


def enabled_dependency(module_id: str):
    """Route dependency: 404 while the module is off for the requesting tenant."""
    from heinzel_api.deps import current_tenant

    def _check(tenant=Depends(current_tenant)) -> None:  # noqa: B008
        if not is_enabled(tenant.config, module_id):
            raise HTTPException(status_code=404, detail="module_disabled")

    return _check


def mount(app, hosts: dict[str, ModuleHost]) -> None:
    for host in hosts.values():
        for router in host.routers:
            app.include_router(
                router,
                prefix=f"/api/v1/{host.id}",
                dependencies=[Depends(enabled_dependency(host.id))],
            )
