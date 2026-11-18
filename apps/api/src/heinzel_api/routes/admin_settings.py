"""Administration: tenant settings (permission core.settings.manage).

The configuration lives in core.tenant_settings (tenant.json is only the seed). Each tab of
the Einstellungen page saves one section. Saves name the version they started from; a
concurrent change answers 409 version_conflict. Sign-in and e-mail settings need a step-up:
they decide who can log in and where password-reset links are sent.
"""

import hashlib
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, HttpUrl

from heinzel_api import audit, crypto, localization, mail
from heinzel_api.db import tenant_session
from heinzel_api.deps import (
    DbDep,
    Principal,
    TenantContext,
    TenantDep,
    client_ip,
    require,
    require_step_up,
)
from heinzel_api.models import TenantAsset, TenantSettings

router = APIRouter(prefix="/api/v1/admin/settings", tags=["admin"])

SettingsAdmin = Annotated[Principal, Depends(require("core.settings.manage"))]
SettingsAdminStepUp = Annotated[Principal, Depends(require_step_up("core.settings.manage"))]

HEX = r"^#[0-9a-fA-F]{6}$"
EmailStr = Annotated[str, Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
CURRENCIES = ["CHF", "EUR"]
LOGO_SLOTS = {"light": "logo_light", "dark": "logo_dark", "mark": "logo_mark"}
LOGO_MAX_BYTES = 512 * 1024
SMTP_PURPOSE = "smtp"


# --- section models -----------------------------------------------------------------------


class Legal(BaseModel):
    imprint_url: HttpUrl | None = None
    privacy_url: HttpUrl | None = None


class General(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    short_name: str = Field(min_length=1, max_length=60)
    legal: Legal = Legal()


class Colors(BaseModel):
    primary: str = Field(pattern=HEX)
    accent: str = Field(pattern=HEX)


class BrandingIn(BaseModel):
    colors: Colors
    theme_default: Literal["light", "dark", "system"] = "system"
    powered_by: bool = True


class LocalizationDefaults(BaseModel):
    language: str
    timezone: str
    date_format: str
    time_format: str
    first_day_of_week: str
    number_format: str
    currency: str = "CHF"


class LocalizationIn(BaseModel):
    languages: list[str] = Field(min_length=1)
    defaults: LocalizationDefaults
    locked: list[str] = []


class Lockout(BaseModel):
    attempts: int = Field(ge=3, le=20)
    minutes: int = Field(ge=1, le=1440)


class LocalIdentityIn(BaseModel):
    enabled: bool = True
    mfa_required: Literal["all", "admins", "optional"]
    password_min_length: int = Field(ge=10, le=128)
    self_service_reset: bool
    lockout: Lockout
    session_idle_hours: int = Field(ge=1, le=720)


class IdentityIn(BaseModel):
    local: LocalIdentityIn


class SmtpIn(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    security: Literal["none", "starttls", "tls"]
    username: str | None = Field(default=None, max_length=200)
    # Write-only. None keeps the stored password, "" removes it.
    password: str | None = Field(default=None, max_length=500)


class EmailIn(BaseModel):
    from_name: str = Field(min_length=1, max_length=200)
    from_address: EmailStr
    reply_to: EmailStr | None = None
    smtp: SmtpIn


SECTIONS: dict[str, type[BaseModel]] = {
    "general": General,
    "branding": BrandingIn,
    "localization": LocalizationIn,
    "identity": IdentityIn,
    "email": EmailIn,
}
STEP_UP_SECTIONS = {"identity", "email"}


class SaveIn(BaseModel):
    version: int
    values: dict[str, Any]


# --- reading ------------------------------------------------------------------------------


def _public(config: dict[str, Any]) -> dict[str, Any]:
    """The settings as the admin sees them: secrets replaced by flags."""
    email = dict(config.get("email") or {})
    smtp = dict(email.get("smtp") or {})
    smtp["password_set"] = bool(smtp.pop("password_enc", None) or smtp.get("password_ref"))
    smtp.pop("password_ref", None)
    email["smtp"] = smtp
    branding = dict(config.get("branding") or {})
    return {
        "general": {
            "display_name": config.get("display_name"),
            "short_name": config.get("short_name"),
            "legal": config.get("legal") or {},
        },
        "branding": branding,
        "localization": config.get("localization") or {},
        "identity": config.get("identity") or {},
        "email": email,
    }


def _options(tenant: TenantContext) -> dict[str, Any]:
    return {
        "languages": localization.LANGUAGE_LABELS,
        "timezones": localization.options(tenant.config)["timezone"],
        "currencies": CURRENCIES,
        "localization_keys": [*localization.KEYS, "currency"],
        **{k: v for k, v in localization.FIXED_OPTIONS.items()},
    }


def _load(s, tenant: TenantContext) -> TenantSettings:
    row = s.get(TenantSettings, tenant.id)
    if row is None:
        raise HTTPException(status_code=404, detail="settings_missing")
    return row


@router.get("")
def get_settings(actor: SettingsAdmin, tenant: TenantDep, db: DbDep) -> dict[str, Any]:
    with tenant_session(db, tenant.id) as s:
        row = _load(s, tenant)
        return {
            "version": row.version,
            "updated_at": row.updated_at,
            "sections": _public(row.config),
            "assets_base": f"/api/v1/tenants/{tenant.config.slug}/assets/",
            "options": _options(tenant),
        }


# --- saving -------------------------------------------------------------------------------


def _validate_localization(v: LocalizationIn) -> dict[str, Any]:
    supported = set(localization.LANGUAGE_LABELS)
    if not set(v.languages) <= supported:
        raise HTTPException(status_code=422, detail="unknown_language")
    d = v.defaults
    if d.language not in v.languages:
        raise HTTPException(status_code=422, detail="default_language_not_offered")
    if d.timezone not in localization._timezones():
        raise HTTPException(status_code=422, detail="unknown_timezone")
    for key, allowed in localization.FIXED_OPTIONS.items():
        if getattr(d, key) not in allowed:
            raise HTTPException(status_code=422, detail=f"invalid_{key}")
    if d.currency not in CURRENCIES:
        raise HTTPException(status_code=422, detail="invalid_currency")
    if not set(v.locked) <= {*localization.KEYS, "currency"}:
        raise HTTPException(status_code=422, detail="invalid_lock")
    return v.model_dump(mode="json")


def _apply(
    section: str, values: dict[str, Any], config: dict[str, Any], secret_key: str
) -> dict[str, Any]:
    """Return the new config with `section` replaced. Raises HTTPException on bad input."""
    model = SECTIONS[section].model_validate(values)
    new = dict(config)
    if section == "general":
        g: General = model  # type: ignore[assignment]
        new["display_name"] = g.display_name
        new["short_name"] = g.short_name
        new["legal"] = g.legal.model_dump(mode="json")
    elif section == "branding":
        # Logos are managed through their own endpoints; keep them.
        new["branding"] = {**(config.get("branding") or {}), **model.model_dump(mode="json")}
    elif section == "localization":
        new["localization"] = _validate_localization(model)  # type: ignore[arg-type]
    elif section == "identity":
        ident: IdentityIn = model  # type: ignore[assignment]
        providers = (config.get("identity") or {}).get("providers", [])
        if not ident.local.enabled and not providers:
            raise HTTPException(status_code=409, detail="no_login_left")
        new["identity"] = {**(config.get("identity") or {}), "local": ident.local.model_dump()}
    elif section == "email":
        e: EmailIn = model  # type: ignore[assignment]
        old_smtp = (config.get("email") or {}).get("smtp") or {}
        smtp = e.smtp.model_dump(exclude={"password"})
        if e.smtp.password is None:
            for key in ("password_enc", "password_ref"):
                if old_smtp.get(key):
                    smtp[key] = old_smtp[key]
        elif e.smtp.password:
            smtp["password_enc"] = crypto.encrypt(secret_key, SMTP_PURPOSE, e.smtp.password)
        new["email"] = {**e.model_dump(mode="json", exclude={"smtp"}), "smtp": smtp}
    return new


def _diff(before: dict[str, Any], after: dict[str, Any], section: str) -> dict[str, Any]:
    pb, pa = _public(before)[section], _public(after)[section]
    return {"before": pb, "after": pa} if pb != pa else {}


def _save(
    request: Request,
    actor: Principal,
    tenant: TenantContext,
    db,
    section: str,
    body: SaveIn,
) -> dict[str, Any]:
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail="unknown_section")
    with tenant_session(db, tenant.id) as s:
        row = _load(s, tenant)
        if row.version != body.version:
            raise HTTPException(status_code=409, detail="version_conflict")
        try:
            new = _apply(section, body.values, row.config, request.app.state.settings.secret_key)
        except ValueError as e:  # pydantic ValidationError is a ValueError
            raise HTTPException(status_code=422, detail="invalid_values") from e
        change = _diff(row.config, new, section)
        if change:
            row.config = new
            row.version += 1
            row.updated_by = actor.user_id
            audit.record(
                s,
                tenant.id,
                "settings.changed",
                actor_user_id=actor.user_id,
                target_type="settings",
                target_id=section,
                data=change,
                ip=client_ip(request),
            )
        version = row.version
    request.app.state.registry.invalidate()
    return {"version": version, "changed": bool(change)}


@router.put("/{section}")
def save_section(
    section: str,
    body: SaveIn,
    request: Request,
    actor: SettingsAdmin,
    tenant: TenantDep,
    db: DbDep,
) -> dict[str, Any]:
    if section in STEP_UP_SECTIONS:
        raise HTTPException(status_code=404, detail="use_step_up_route")
    return _save(request, actor, tenant, db, section, body)


@router.put("/secure/{section}")
def save_secure_section(
    section: str,
    body: SaveIn,
    request: Request,
    actor: SettingsAdminStepUp,
    tenant: TenantDep,
    db: DbDep,
) -> dict[str, Any]:
    """Sign-in and e-mail settings, behind a step-up."""
    if section not in STEP_UP_SECTIONS:
        raise HTTPException(status_code=404, detail="unknown_section")
    return _save(request, actor, tenant, db, section, body)


# --- logos --------------------------------------------------------------------------------


def _sniff(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    head = data[:2048].decode("utf-8", "ignore").lstrip("﻿ \r\n\t")
    if (head.startswith("<?xml") or head.startswith("<svg")) and re.search(r"<svg[\s>]", head):
        return "image/svg+xml", "svg"
    return None


@router.put("/branding/logos/{slot}")
async def upload_logo(
    slot: str, request: Request, actor: SettingsAdmin, tenant: TenantDep, db: DbDep
) -> dict[str, Any]:
    """Body: the image itself (SVG, PNG or WebP, at most 512 KB)."""
    if slot not in LOGO_SLOTS:
        raise HTTPException(status_code=404, detail="unknown_slot")
    data = await request.body()
    if not data or len(data) > LOGO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="logo_too_large")
    kind = _sniff(data)
    if kind is None:
        raise HTTPException(status_code=415, detail="logo_type")
    ctype, ext = kind
    sha = hashlib.sha256(data).hexdigest()
    # A new name per content: browsers and proxies never show a stale logo.
    name = f"logo-{slot}-{sha[:12]}.{ext}"
    return _set_logo(request, actor, tenant, db, slot, (name, ctype, data, sha))


@router.delete("/branding/logos/{slot}")
def delete_logo(
    slot: str, request: Request, actor: SettingsAdmin, tenant: TenantDep, db: DbDep
) -> dict[str, Any]:
    if slot not in LOGO_SLOTS:
        raise HTTPException(status_code=404, detail="unknown_slot")
    if slot == "light":
        raise HTTPException(status_code=409, detail="main_logo_required")
    return _set_logo(request, actor, tenant, db, slot, None)


def _set_logo(request, actor, tenant, db, slot, new) -> dict[str, Any]:
    key = LOGO_SLOTS[slot]
    with tenant_session(db, tenant.id) as s:
        row = _load(s, tenant)
        branding = dict(row.config.get("branding") or {})
        old = (branding.get(key) or "").removeprefix("assets/") or None
        if new:
            name, ctype, data, sha = new
            if s.get(TenantAsset, {"tenant_id": tenant.id, "name": name}) is None:
                s.add(
                    TenantAsset(
                        tenant_id=tenant.id, name=name, content_type=ctype, data=data, sha256=sha
                    )
                )
            branding[key] = name
        else:
            branding[key] = None
        if old and old != branding[key]:
            stale = s.get(TenantAsset, {"tenant_id": tenant.id, "name": old})
            if stale is not None:
                s.delete(stale)
        row.config = {**row.config, "branding": branding}
        row.version += 1
        row.updated_by = actor.user_id
        audit.record(
            s,
            tenant.id,
            "settings.logo_changed" if new else "settings.logo_removed",
            actor_user_id=actor.user_id,
            target_type="settings",
            target_id=f"branding.{key}",
            data={"name": branding[key]},
            ip=client_ip(request),
        )
        version = row.version
    request.app.state.registry.invalidate()
    return {"version": version, "name": branding[key]}


# --- test mail ----------------------------------------------------------------------------


@router.post("/email/test")
def send_test_mail(
    request: Request, actor: SettingsAdmin, tenant: TenantDep, db: DbDep
) -> dict[str, Any]:
    """Send a test mail to the signed-in admin with the saved settings."""
    request.app.state.registry.invalidate()
    entry = request.app.state.registry.by_slug(tenant.config.slug)
    config = entry.config if entry else tenant.config
    sent = request.app.state.mailer.send(
        config,
        mail.Mail(
            to=actor.email,
            subject=f"Test-E-Mail · {config.display_name}",
            text=(
                f"Grüezi {actor.display_name}\n\n"
                "Diese E-Mail bestätigt, dass Heinzel mit den gespeicherten Einstellungen "
                "E-Mails versenden kann.\n"
            ),
        ),
    )
    with tenant_session(db, tenant.id) as s:
        audit.record(
            s,
            tenant.id,
            "settings.test_mail",
            actor_user_id=actor.user_id,
            data={"sent": sent},
            ip=client_ip(request),
        )
    return {"sent": sent, "to": actor.email}
