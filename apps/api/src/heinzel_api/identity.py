"""Local identity: passwords (Argon2id), TOTP and server-side sessions.

All functions expect a tenant-bound session (see heinzel_api.db.tenant_session), so row
level security already limits them to one tenant.
"""

import contextlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from heinzel_api import crypto
from heinzel_api.models import User, UserSession
from heinzel_api.tenants import LocalIdentity

_hasher = PasswordHasher()  # Argon2id with the library's current recommended parameters
# Verified against when the e-mail is unknown, so both paths cost the same time.
_DUMMY_HASH = _hasher.hash("heinzel-dummy-password")

SESSION_ABSOLUTE = timedelta(days=7)
SESSION_TOUCH_EVERY = timedelta(minutes=1)
TOTP_ISSUER = "Heinzel"
MFA_PURPOSE = "totp"


class PasswordPolicyError(ValueError):
    pass


def hash_password(password: str, policy: LocalIdentity) -> str:
    if len(password) < policy.password_min_length:
        raise PasswordPolicyError(
            f"Das Passwort muss mindestens {policy.password_min_length} Zeichen lang sein."
        )
    if len(password) > 1024:
        raise PasswordPolicyError("Das Passwort ist zu lang.")
    return _hasher.hash(password)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def find_user(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.email) == normalise_email(email)))


def create_user(
    session: Session,
    tenant_id: UUID,
    email: str,
    display_name: str,
    policy: LocalIdentity,
    password: str | None = None,
    status: str = "active",
) -> User:
    user = User(
        tenant_id=tenant_id,
        email=normalise_email(email),
        display_name=display_name.strip(),
        password_hash=hash_password(password, policy) if password else None,
        status=status,
    )
    session.add(user)
    session.flush()
    return user


class LoginResult(StrEnum):
    OK = "ok"
    INVALID = "invalid"
    LOCKED = "locked"
    INACTIVE = "inactive"


def check_password(
    session: Session, email: str, password: str, policy: LocalIdentity
) -> tuple[LoginResult, User | None]:
    """Verify credentials and apply the tenant's lockout policy."""
    user = find_user(session, email)
    if user is None or user.password_hash is None:
        with contextlib.suppress(VerificationError):
            _hasher.verify(_DUMMY_HASH, password)
        return LoginResult.INVALID, user

    now = datetime.now(UTC)
    if user.locked_until and user.locked_until > now:
        return LoginResult.LOCKED, user

    try:
        _hasher.verify(user.password_hash, password)
    except (VerificationError, InvalidHashError):
        user.failed_logins += 1
        if user.failed_logins >= policy.lockout.attempts:
            user.locked_until = now + timedelta(minutes=policy.lockout.minutes)
            user.failed_logins = 0
            session.flush()
            return LoginResult.LOCKED, user
        session.flush()
        return LoginResult.INVALID, user

    if user.status != "active":
        return LoginResult.INACTIVE, user

    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    user.failed_logins = 0
    user.locked_until = None
    session.flush()
    return LoginResult.OK, user


def mfa_required(user: User, policy: LocalIdentity, is_admin: bool) -> bool:
    if user.mfa_enabled:
        return True
    return policy.mfa_required == "all" or (policy.mfa_required == "admins" and is_admin)


# --- TOTP -------------------------------------------------------------------------------


def start_totp_setup(user: User, secret_key: str, issuer: str) -> tuple[str, str]:
    """Generate a new seed (stored encrypted, not yet active). Returns (seed, otpauth URI)."""
    seed = pyotp.random_base32()
    user.mfa_secret = crypto.encrypt(secret_key, MFA_PURPOSE, seed)
    user.mfa_enabled = False
    user.mfa_last_step = None
    uri = pyotp.TOTP(seed).provisioning_uri(
        name=user.email, issuer_name=f"{issuer} ({TOTP_ISSUER})"
    )
    return seed, uri


def verify_totp(user: User, code: str, secret_key: str, at: float | None = None) -> bool:
    """Accept the current, previous or next 30 s step; never the same step twice."""
    if not user.mfa_secret:
        return False
    code = code.replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return False
    totp = pyotp.TOTP(crypto.decrypt(secret_key, MFA_PURPOSE, user.mfa_secret))
    now = at if at is not None else time.time()
    step_now = int(now // totp.interval)
    for step in (step_now - 1, step_now, step_now + 1):
        if user.mfa_last_step is not None and step <= user.mfa_last_step:
            continue
        if totp.verify(code, for_time=step * totp.interval, valid_window=0):
            user.mfa_last_step = step
            return True
    return False


# --- Sessions ---------------------------------------------------------------------------


@dataclass
class ActiveSession:
    session: UserSession
    user: User


def create_session(
    session: Session,
    user: User,
    policy: LocalIdentity,
    *,
    mfa_passed: bool,
    ip: str | None,
    user_agent: str | None,
) -> str:
    """Create a session and return the cookie token (only its hash is stored)."""
    token = crypto.new_token()
    now = datetime.now(UTC)
    session.add(
        UserSession(
            tenant_id=user.tenant_id,
            user_id=user.id,
            token_hash=crypto.token_hash(token),
            mfa_passed=mfa_passed,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=policy.session_idle_hours),
            ip=ip,
            user_agent=(user_agent or "")[:400] or None,
        )
    )
    session.flush()
    return token


def load_session(session: Session, token: str, policy: LocalIdentity) -> ActiveSession | None:
    """Return the live session for a cookie token and extend its idle timeout."""
    row = session.scalar(
        select(UserSession).where(UserSession.token_hash == crypto.token_hash(token))
    )
    if row is None:
        return None
    now = datetime.now(UTC)
    if row.expires_at <= now or row.created_at + SESSION_ABSOLUTE <= now:
        session.delete(row)
        session.flush()
        return None
    user = session.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    if now - row.last_seen_at >= SESSION_TOUCH_EVERY:
        row.last_seen_at = now
        row.expires_at = min(
            now + timedelta(hours=policy.session_idle_hours), row.created_at + SESSION_ABSOLUTE
        )
    return ActiveSession(row, user)


def end_session(session: Session, token: str) -> None:
    session.execute(delete(UserSession).where(UserSession.token_hash == crypto.token_hash(token)))


def end_all_sessions(session: Session, user_id: UUID, keep: UUID | None = None) -> None:
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if keep is not None:
        stmt = stmt.where(UserSession.id != keep)
    session.execute(stmt)
