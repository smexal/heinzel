"""The signed-in user: profile and personal settings."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from heinzel_api import audit, localization
from heinzel_api.db import tenant_session
from heinzel_api.deps import DbDep, PrincipalDep, TenantDep, client_ip
from heinzel_api.models import User

router = APIRouter(prefix="/api/v1", tags=["me"])


class Me(BaseModel):
    id: str
    email: str
    display_name: str
    roles: list[str]
    permissions: list[str]
    mfa_enabled: bool
    # Effective localisation: tenant defaults, overridden by the user unless locked
    localization: dict[str, str]
    locked: list[str]


class Preferences(BaseModel):
    """GET: everything the profile page needs. `values` holds only the user's own choices;
    a missing key means "Standard" (follow the tenant default)."""

    values: dict[str, str]
    defaults: dict[str, str]
    effective: dict[str, str]
    locked: list[str]
    options: dict[str, list[str]]
    language_labels: dict[str, str]


class PreferencesIn(BaseModel):
    # Keys from localization.KEYS; null resets to the tenant default.
    localization: dict[str, str | None]


@router.get("/me", response_model=Me)
def me(p: PrincipalDep, tenant: TenantDep, db: DbDep) -> Me:
    with tenant_session(db, tenant.id) as s:
        user = s.get(User, p.user_id)
        assert user is not None
        prefs = dict(user.preferences)
    return Me(
        id=str(p.user_id),
        email=p.email,
        display_name=p.display_name,
        roles=p.roles,
        permissions=sorted(p.permissions),
        mfa_enabled=p.mfa_enabled,
        localization=localization.effective(tenant.config, prefs),
        locked=localization.locked(tenant.config),
    )


def _preferences(tenant, prefs: dict) -> Preferences:
    cfg = tenant.config
    return Preferences(
        values=localization.user_values(prefs),
        defaults=localization.defaults(cfg),
        effective=localization.effective(cfg, prefs),
        locked=localization.locked(cfg),
        options=localization.options(cfg),
        language_labels=localization.LANGUAGE_LABELS,
    )


@router.get("/me/preferences", response_model=Preferences)
def get_preferences(p: PrincipalDep, tenant: TenantDep, db: DbDep) -> Preferences:
    with tenant_session(db, tenant.id) as s:
        user = s.get(User, p.user_id)
        assert user is not None
        return _preferences(tenant, dict(user.preferences))


@router.put("/me/preferences", response_model=Preferences)
def put_preferences(
    body: PreferencesIn, request: Request, p: PrincipalDep, tenant: TenantDep, db: DbDep
) -> Preferences:
    """Replace the user's localisation choices (keys left out or null follow the default)."""
    try:
        values = localization.validate(tenant.config, body.localization)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    with tenant_session(db, tenant.id) as s:
        user = s.get(User, p.user_id)
        assert user is not None
        before = localization.user_values(user.preferences)
        user.preferences = {**user.preferences, "localization": values}
        if before != values:
            audit.record(
                s,
                tenant.id,
                "user.preferences_changed",
                actor_user_id=p.user_id,
                target_type="user",
                target_id=str(p.user_id),
                data={"before": before, "after": values},
                ip=client_ip(request),
            )
        return _preferences(tenant, dict(user.preferences))
