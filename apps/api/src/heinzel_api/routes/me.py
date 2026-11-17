"""The signed-in user."""

from fastapi import APIRouter
from pydantic import BaseModel

from heinzel_api.db import tenant_session
from heinzel_api.deps import DbDep, PrincipalDep, TenantDep
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


@router.get("/me", response_model=Me)
def me(p: PrincipalDep, tenant: TenantDep, db: DbDep) -> Me:
    with tenant_session(db, tenant.id) as s:
        user = s.get(User, p.user_id)
        assert user is not None
        prefs = dict(user.preferences.get("localization", {}))
    loc = tenant.config.model_extra.get("localization", {}) if tenant.config.model_extra else {}
    defaults: dict[str, str] = dict(loc.get("defaults", {}))
    locked: list[str] = list(loc.get("locked", []))
    effective = {**defaults, **{k: v for k, v in prefs.items() if k not in locked}}
    return Me(
        id=str(p.user_id),
        email=p.email,
        display_name=p.display_name,
        roles=p.roles,
        permissions=sorted(p.permissions),
        mfa_enabled=p.mfa_enabled,
        localization=effective,
        locked=locked,
    )
