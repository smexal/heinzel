"""Self-service account flows: forgotten password, invitation and reset links, change password.

The link in an e-mail opens /konto/<token> in the web app, which calls these endpoints.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from heinzel_api import audit, identity, inbox, mail, ratelimit
from heinzel_api.db import tenant_session
from heinzel_api.deps import DbDep, PrincipalDep, TenantDep, client_ip, public_url, rate_limit
from heinzel_api.models import User

router = APIRouter(prefix="/api/v1", tags=["account"])


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class TokenInfo(BaseModel):
    purpose: str  # invite | password_reset
    email: str
    display_name: str
    password_min_length: int


class SetPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


@router.post("/auth/password/forgot", status_code=202)
def forgot_password(body: ForgotIn, request: Request, tenant: TenantDep, db: DbDep) -> dict:
    """Always answers 202, whether or not the address exists."""
    rate_limit(request, ratelimit.PASSWORD_FORGOT, tenant.config.slug)
    if not tenant.policy.self_service_reset or not tenant.policy.enabled:
        return {}
    outgoing: mail.Mail | None = None
    with tenant_session(db, tenant.id) as s:
        user = identity.find_user(s, body.email)
        if user is not None and user.status == "active":
            token = identity.issue_action_token(s, user, "password_reset")
            outgoing = mail.reset_mail(
                tenant.config,
                user.email,
                user.display_name,
                public_url(request, f"/konto/{token}"),
                int(identity.RESET_TTL.total_seconds() // 60),
            )
            audit.record(
                s,
                tenant.id,
                "auth.password_reset_requested",
                target_type="user",
                target_id=str(user.id),
                ip=client_ip(request),
            )
    if outgoing is not None:
        request.app.state.mailer.send(tenant.config, outgoing)
    return {}


@router.get("/auth/token/{token}", response_model=TokenInfo)
def token_info(token: str, request: Request, tenant: TenantDep, db: DbDep) -> TokenInfo:
    rate_limit(request, ratelimit.TOKEN, tenant.config.slug)
    with tenant_session(db, tenant.id) as s:
        found = identity.find_action_token(s, token)
        if found is None:
            raise HTTPException(status_code=404, detail="invalid_token")
        row, user = found
        return TokenInfo(
            purpose=row.purpose,
            email=user.email,
            display_name=user.display_name,
            password_min_length=tenant.policy.password_min_length,
        )


@router.post("/auth/password/set", status_code=204)
def set_password(body: SetPasswordIn, request: Request, tenant: TenantDep, db: DbDep) -> None:
    """Redeem an invitation or reset link. The user then signs in normally (MFA follows)."""
    rate_limit(request, ratelimit.TOKEN, tenant.config.slug)
    try:
        with tenant_session(db, tenant.id) as s:
            result = identity.set_password_with_token(s, body.token, body.password, tenant.policy)
            if result is None:
                raise HTTPException(status_code=404, detail="invalid_token")
            row, user = result
            if row.purpose == "invite" and row.created_by:
                inbox.deliver(
                    s,
                    tenant.id,
                    [row.created_by],
                    source=inbox.CORE,
                    kind="notice",
                    title=f"{user.display_name} hat die Einladung angenommen",
                    context=user.email,
                    link="/admin/benutzer",
                    ref_type="user",
                    ref_id=str(user.id),
                    actor_user_id=user.id,
                )
            audit.record(
                s,
                tenant.id,
                "user.activated" if row.purpose == "invite" else "auth.password_reset",
                actor_user_id=user.id,
                target_type="user",
                target_id=str(user.id),
                ip=client_ip(request),
            )
    except identity.PasswordPolicyError as e:
        raise HTTPException(status_code=422, detail="password_policy") from e


@router.post("/me/password", status_code=204)
def change_password(
    body: ChangePasswordIn, request: Request, p: PrincipalDep, tenant: TenantDep, db: DbDep
) -> None:
    """Change the own password. Other sessions of the user end; this one stays."""
    ok = False
    try:
        with tenant_session(db, tenant.id) as s:
            user = s.get(User, p.user_id)
            assert user is not None
            ok = identity.change_password(
                s, user, body.current_password, body.new_password, tenant.policy, p.session_id
            )
            audit.record(
                s,
                tenant.id,
                "auth.password_changed" if ok else "auth.password_change_failed",
                actor_user_id=p.user_id,
                target_type="user",
                target_id=str(p.user_id),
                ip=client_ip(request),
            )
    except identity.PasswordPolicyError as e:
        raise HTTPException(status_code=422, detail="password_policy") from e
    if not ok:
        raise HTTPException(status_code=403, detail="wrong_password")
