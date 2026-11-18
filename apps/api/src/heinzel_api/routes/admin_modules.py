"""Administration: modules per tenant (permission core.modules.manage).

A module is installed for a tenant by an entry in its configuration (`modules`): active or
not, its area in the sidebar, hidden sub-navigation entries, its settings (validated against
the module's settings.schema.json) and MCP tools switched off for AI clients. Deactivating a
module hides it everywhere; its data stays.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from heinzel_api import audit
from heinzel_api.db import tenant_session
from heinzel_api.deps import (
    DbDep,
    ManifestsDep,
    Principal,
    TenantContext,
    TenantDep,
    client_ip,
    require,
)
from heinzel_api.manifests import Manifest
from heinzel_api.models import Role, RolePermission, TenantSettings

router = APIRouter(prefix="/api/v1/admin/modules", tags=["admin"])

ModulesAdmin = Annotated[Principal, Depends(require("core.modules.manage"))]


class ModuleIn(BaseModel):
    version: int
    enabled: bool
    area: str | None = None
    hidden_children: list[str] = []
    settings: dict[str, Any] = {}
    mcp_disabled: list[str] = []


def _de(text: dict[str, str] | None, fallback: str = "") -> str:
    text = text or {}
    return text.get("de") or next(iter(text.values()), fallback)


def _mcp_items(m: Manifest, disabled: set[str]) -> list[dict[str, Any]]:
    items = []
    for tool in m.mcp.get("tools", []):
        ro = bool((tool.get("annotations") or {}).get("readOnlyHint"))
        items.append(
            {
                "name": tool["name"],
                "kind": "read" if ro else "write",
                "title": _de(tool.get("title"), tool["name"]),
                "enabled": tool["name"] not in disabled,
            }
        )
    for prompt in m.mcp.get("prompts", []):
        name = prompt["name"] if isinstance(prompt, dict) else prompt
        title = _de(prompt.get("title"), name) if isinstance(prompt, dict) else name
        items.append(
            {"name": name, "kind": "prompt", "title": title, "enabled": name not in disabled}
        )
    return items


def _installs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["key"]: m for m in config.get("modules", [])}


def _module_out(
    m: Manifest, install: dict[str, Any] | None, holders: dict[str, list[str]]
) -> dict[str, Any]:
    nav = m.navigation
    hidden = set((install or {}).get("hidden_children", []))
    disabled = set((install or {}).get("mcp_disabled", []))
    status = "available" if install is None else ("active" if install["enabled"] else "inactive")
    return {
        "key": m.id,
        "name": _de(m.name, m.id),
        "description": _de(m.description),
        "version": m.version,
        "icon": nav.entry.icon if nav else None,
        "status": status,
        "area": (install or {}).get("area", nav.default_area if nav else None),
        "default_area": nav.default_area if nav else None,
        "children": [
            {"path": c.path, "label": _de(c.label, c.path), "visible": c.path not in hidden}
            for c in (nav.children if nav else [])
        ],
        "permissions": [
            {"id": p.id, "label": _de(p.label, p.id), "roles": holders.get(p.id, [])}
            for p in m.permissions
        ],
        "settings_schema": m.settings_json_schema,
        "settings": {**m.settings_defaults(), **((install or {}).get("settings") or {})},
        "mcp": _mcp_items(m, disabled),
    }


def _holders(s) -> tuple[list[str], dict[str, list[str]]]:
    """Roles holding the wildcard, and permission id -> names of roles that hold it."""
    rows = s.execute(
        select(RolePermission.permission, Role.name, Role.key)
        .join(Role, Role.id == RolePermission.role_id)
        .order_by(Role.is_system.desc(), Role.name)
    )
    out: dict[str, list[str]] = {}
    wildcard: list[str] = []
    for perm, name, _key in rows:
        if perm == "*":
            wildcard.append(name)
        else:
            out.setdefault(perm, []).append(name)
    return wildcard, out


def _load(s, tenant: TenantContext) -> TenantSettings:
    row = s.get(TenantSettings, tenant.id)
    if row is None:
        raise HTTPException(status_code=404, detail="settings_missing")
    return row


@router.get("")
def list_modules(
    actor: ModulesAdmin, tenant: TenantDep, db: DbDep, manifests: ManifestsDep
) -> dict[str, Any]:
    with tenant_session(db, tenant.id) as s:
        row = _load(s, tenant)
        wildcard, per_permission = _holders(s)
        installs = _installs(row.config)
        modules = [
            _module_out(
                m,
                installs.get(m.id),
                {p.id: [*wildcard, *per_permission.get(p.id, [])] for p in m.permissions},
            )
            for m in manifests.values()
        ]
        areas = [
            {"key": a["key"], "label": _de(a.get("label"), a["key"])}
            for a in sorted(
                (row.config.get("navigation") or {}).get("areas", []),
                key=lambda a: a.get("order", 0),
            )
        ]
        return {"version": row.version, "areas": areas, "modules": modules}


@router.put("/{key}")
def save_module(
    key: str,
    body: ModuleIn,
    request: Request,
    actor: ModulesAdmin,
    tenant: TenantDep,
    db: DbDep,
    manifests: ManifestsDep,
) -> dict[str, Any]:
    m = manifests.get(key)
    if m is None:
        raise HTTPException(status_code=404, detail="unknown_module")
    with tenant_session(db, tenant.id) as s:
        row = _load(s, tenant)
        if row.version != body.version:
            raise HTTPException(status_code=409, detail="version_conflict")
        areas = {a["key"] for a in (row.config.get("navigation") or {}).get("areas", [])}
        if body.area is not None and body.area not in areas:
            raise HTTPException(status_code=422, detail="unknown_area")
        children = {c.path for c in (m.navigation.children if m.navigation else [])}
        if not set(body.hidden_children) <= children:
            raise HTTPException(status_code=422, detail="unknown_child")
        mcp_names = {i["name"] for i in _mcp_items(m, set())}
        if not set(body.mcp_disabled) <= mcp_names:
            raise HTTPException(status_code=422, detail="unknown_mcp_item")
        settings = {**m.settings_defaults(), **body.settings}
        errors = m.validate_settings(settings) if m.settings_json_schema else []
        if errors:
            raise HTTPException(
                status_code=422, detail={"code": "invalid_settings", "errors": errors}
            )

        installs = row.config.get("modules", [])
        before = next((dict(i) for i in installs if i["key"] == key), None)
        after = {
            "key": key,
            "enabled": body.enabled,
            "area": body.area,
            "hidden_children": sorted(set(body.hidden_children)),
            "settings": settings if m.settings_json_schema else {},
            "mcp_disabled": sorted(set(body.mcp_disabled)),
        }
        if before is not None and all(before.get(k) == v for k, v in after.items()):
            return {"version": row.version, "changed": False}
        new_installs = [i for i in installs if i["key"] != key] + [after]
        new_installs.sort(key=lambda i: i["key"])
        row.config = {**row.config, "modules": new_installs}
        row.version += 1
        row.updated_by = actor.user_id
        if before is None or before.get("enabled") != body.enabled:
            action = "module.enabled" if body.enabled else "module.disabled"
        else:
            action = "module.changed"
        audit.record(
            s,
            tenant.id,
            action,
            actor_user_id=actor.user_id,
            target_type="module",
            target_id=key,
            data={"name": _de(m.name, key), "before": before, "after": after},
            ip=client_ip(request),
        )
        version = row.version
    request.app.state.registry.invalidate()
    return {"version": version, "changed": True}
