"""Local login with password and TOTP.

Flow: POST /auth/login → `next` says what follows:
  "done"       signed in
  "totp"       enter the code from the authenticator app (POST /auth/totp)
  "mfa_setup"  MFA is required but not set up yet (POST /auth/mfa/setup, then /auth/mfa/confirm)
Until the second factor is passed the session cookie only grants access to these endpoints.
The cookie token is replaced whenever the session gains privileges.

Failed logins never say whether the e-mail exists or the account is locked; the audit log
records the real reason.
"""

from datetime import UTC, datetime
from typing import Literal

import segno
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from heinzel_api import audit, identity, ratelimit, rbac
from heinzel_api.db import tenant_session
from heinzel_api.deps import (
    SESSION_COOKIE,
    DbDep,
    OptionalPrincipalDep,
    Principal,
    TenantContext,
    TenantDep,
    client_ip,
    rate_limit,
)
from heinzel_api.identity import LoginResult
from heinzel_api.models import User, UserSession

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

Next = Literal["done", "totp", "mfa_setup"]


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class StepOut(BaseModel):
    next: Next


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str  # data: URI, ready for <img src>


def _set_cookie(request: Request, response: Response, token: str, tenant: TenantContext) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=tenant.policy.session_idle_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.secure_cookies,
        path="/",
    )


def _pending(p: Principal | None) -> Principal:
    if p is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return p


def _elevate(
    request: Request, response: Response, tenant: TenantContext, s, user: User, old: UserSession
) -> None:
    """Replace a half-authenticated session with a fully authenticated one (new token)."""
    s.delete(old)
    token = identity.create_session(
        s,
        user,
        tenant.policy,
        mfa_passed=True,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    user.last_login_at = datetime.now(UTC)
    _set_cookie(request, response, token, tenant)


@router.post("/login", response_model=StepOut)
def login(
    body: LoginIn, request: Request, response: Response, tenant: TenantDep, db: DbDep
) -> StepOut:
    if not tenant.policy.enabled:
        raise HTTPException(status_code=403, detail="local_login_disabled")
    rate_limit(request, ratelimit.LOGIN, tenant.config.slug)
    ip = client_ip(request)
    # Commit the outcome (failed-login counter, audit) before answering, also on failure.
    with tenant_session(db, tenant.id) as s:
        result, user = identity.check_password(s, body.email, body.password, tenant.policy)
        if result is not LoginResult.OK:
            audit.record(
                s,
                tenant.id,
                "auth.login_failed",
                actor_user_id=user.id if user else None,
                target_type="user" if user else None,
                target_id=str(user.id) if user else None,
                data={"reason": result.value, "email": identity.normalise_email(body.email)},
                ip=ip,
            )
            token = None
        else:
            assert user is not None
            is_admin = "admin" in rbac.user_role_keys(s, user.id)
            needs_mfa = identity.mfa_required(user, tenant.policy, is_admin)
            token = identity.create_session(
                s,
                user,
                tenant.policy,
                mfa_passed=not needs_mfa,
                ip=ip,
                user_agent=request.headers.get("user-agent"),
            )
            if not needs_mfa:
                user.last_login_at = datetime.now(UTC)
            audit.record(
                s,
                tenant.id,
                "auth.login" if not needs_mfa else "auth.password_ok",
                actor_user_id=user.id,
                target_type="user",
                target_id=str(user.id),
                ip=ip,
            )
            step: Next = "done" if not needs_mfa else ("totp" if user.mfa_enabled else "mfa_setup")
    if token is None:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    _set_cookie(request, response, token, tenant)
    return StepOut(next=step)


@router.post("/totp", response_model=StepOut)
def totp(
    body: CodeIn,
    request: Request,
    response: Response,
    tenant: TenantDep,
    db: DbDep,
    p: OptionalPrincipalDep,
) -> StepOut:
    p = _pending(p)
    if p.mfa_passed:
        return StepOut(next="done")
    rate_limit(request, ratelimit.LOGIN, tenant.config.slug)
    ok = False
    with tenant_session(db, tenant.id) as s:
        user = s.get(User, p.user_id)
        old = s.get(UserSession, p.session_id)
        assert user is not None and old is not None
        if user.mfa_enabled and identity.verify_totp(
            user, body.code, request.app.state.settings.secret_key
        ):
            ok = True
            _elevate(request, response, tenant, s, user, old)
            audit.record(s, tenant.id, "auth.login", actor_user_id=user.id, ip=client_ip(request))
        else:
            locked = identity.second_factor_failed(s, user, tenant.policy)
            audit.record(
                s,
                tenant.id,
                "auth.totp_failed",
                actor_user_id=user.id,
                data={"locked": locked},
                ip=client_ip(request),
            )
    if not ok:
        raise HTTPException(status_code=401, detail="invalid_code")
    return StepOut(next="done")


@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(
    request: Request, tenant: TenantDep, db: DbDep, p: OptionalPrincipalDep
) -> MfaSetupOut:
    """Start (or restart) TOTP enrolment. Only while MFA is not yet active for the user."""
    p = _pending(p)
    if p.mfa_enabled:
        raise HTTPException(status_code=409, detail="mfa_already_enabled")
    with tenant_session(db, tenant.id) as s:
        user = s.get(User, p.user_id)
        assert user is not None
        secret, uri = identity.start_totp_setup(
            user, request.app.state.settings.secret_key, tenant.config.short_name
        )
    qr = segno.make(uri, error="m").svg_data_uri(scale=5, border=2)
    return MfaSetupOut(secret=secret, otpauth_uri=uri, qr_svg=qr)


@router.post("/mfa/confirm", response_model=StepOut)
def mfa_confirm(
    body: CodeIn,
    request: Request,
    response: Response,
    tenant: TenantDep,
    db: DbDep,
    p: OptionalPrincipalDep,
) -> StepOut:
    p = _pending(p)
    if p.mfa_enabled:
        raise HTTPException(status_code=409, detail="mfa_already_enabled")
    ok = False
    with tenant_session(db, tenant.id) as s:
        user = s.get(User, p.user_id)
        old = s.get(UserSession, p.session_id)
        assert user is not None and old is not None
        if not identity.verify_totp(user, body.code, request.app.state.settings.secret_key):
            identity.second_factor_failed(s, user, tenant.policy)
        else:
            ok = True
            user.mfa_enabled = True
            audit.record(
                s,
                tenant.id,
                "auth.mfa_enabled",
                actor_user_id=user.id,
                target_type="user",
                target_id=str(user.id),
                ip=client_ip(request),
            )
            if not p.mfa_passed:
                _elevate(request, response, tenant, s, user, old)
                audit.record(
                    s, tenant.id, "auth.login", actor_user_id=user.id, ip=client_ip(request)
                )
    if not ok:
        raise HTTPException(status_code=401, detail="invalid_code")
    return StepOut(next="done")


@router.post("/logout", status_code=204)
def logout(request: Request, tenant: TenantDep, db: DbDep, p: OptionalPrincipalDep) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with tenant_session(db, tenant.id) as s:
            identity.end_session(s, token)
            if p is not None:
                audit.record(
                    s, tenant.id, "auth.logout", actor_user_id=p.user_id, ip=client_ip(request)
                )
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
