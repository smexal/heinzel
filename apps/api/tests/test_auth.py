"""Login flow end to end against the test database (tenant schmelzi, MFA required for all)."""

import time

import pyotp
import pytest
from _support import PASSWORD

pytestmark = pytest.mark.usefixtures("seeded")


def _login(api, email, password=PASSWORD):
    return api.post("/api/v1/auth/login", json={"email": email, "password": password})


def _enrol(api, email) -> pyotp.TOTP:
    r = _login(api, email)
    assert r.status_code == 200 and r.json() == {"next": "mfa_setup"}
    setup = api.post("/api/v1/auth/mfa/setup").json()
    assert setup["qr_svg"].startswith("data:image/svg+xml")
    totp = pyotp.TOTP(setup["secret"])
    r = api.post("/api/v1/auth/mfa/confirm", json={"code": totp.now()})
    assert r.status_code == 200 and r.json() == {"next": "done"}
    return totp


def test_first_login_requires_mfa_setup(api, make_user):
    email = make_user()
    r = _login(api, email)
    assert r.json() == {"next": "mfa_setup"}
    # half-authenticated: no access yet
    assert api.get("/api/v1/me").status_code == 401
    assert api.get("/api/v1/shell").json()["navigation"] == []


def test_full_flow_and_session_rotation(api, make_user):
    email = make_user()
    _login(api, email)
    pending = api.cookies.get("heinzel_session")
    setup = api.post("/api/v1/auth/mfa/setup").json()
    code = pyotp.TOTP(setup["secret"]).now()
    assert api.post("/api/v1/auth/mfa/confirm", json={"code": code}).status_code == 200
    assert api.cookies.get("heinzel_session") != pending

    me = api.get("/api/v1/me").json()
    assert me["email"] == email and me["roles"] == ["staff"]
    assert "aufgaben.use" in me["permissions"] and "core.users.manage" not in me["permissions"]
    assert me["localization"]["timezone"] == "Europe/Zurich"

    shell = api.get("/api/v1/shell").json()
    assert shell["user"]["display_name"] == "Sam Staff"
    assert [s["key"] for s in shell["navigation"]] == ["top"]

    assert api.post("/api/v1/auth/logout").status_code == 204
    api.cookies.clear()
    assert api.get("/api/v1/me").status_code == 401


def test_second_login_uses_totp_and_rejects_replay(api, make_user):
    email = make_user()
    totp = _enrol(api, email)
    api.post("/api/v1/auth/logout")
    api.cookies.clear()

    assert _login(api, email).json() == {"next": "totp"}
    # the code used for enrolment cannot be used again
    assert api.post("/api/v1/auth/totp", json={"code": totp.now()}).status_code == 401
    nxt = totp.at(time.time() + 30)
    assert api.post("/api/v1/auth/totp", json={"code": nxt}).status_code == 200
    assert api.get("/api/v1/me").status_code == 200


def test_admin_sees_administration(api, make_user):
    email = make_user(roles=("admin",))
    _enrol(api, email)
    me = api.get("/api/v1/me").json()
    assert "core.users.manage" in me["permissions"] and "aufgaben.use" in me["permissions"]
    shell = api.get("/api/v1/shell").json()
    assert shell["navigation"][-1]["key"] == "admin"
    assert len(shell["navigation"][-1]["items"]) == 4


def test_wrong_password_and_unknown_user_look_the_same(api, make_user):
    email = make_user()
    a = _login(api, email, "wrong password!!")
    b = _login(api, "nobody@schmelzi.test", "wrong password!!")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "invalid_credentials"}


def test_lockout_after_five_failures(api, make_user):
    email = make_user()
    for _ in range(5):
        assert _login(api, email, "wrong password!!").status_code == 401
    # even the right password is refused while locked, with the same answer
    r = _login(api, email)
    assert r.status_code == 401 and r.json() == {"detail": "invalid_credentials"}


def test_cross_origin_write_is_refused(api):
    r = api.post(
        "/api/v1/auth/login",
        json={"email": "a@b.c", "password": "x"},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_login_is_audited_and_chain_holds(api, make_user, owner_engine):
    from _support import OWNER_URL
    from sqlalchemy import text

    from heinzel_api import audit
    from heinzel_api.db import make_sessionmaker, tenant_session

    email = make_user()
    _login(api, email, "wrong password!!")
    _enrol(api, email)
    with owner_engine.connect() as c:
        tid = c.execute(text("select id from core.tenant where slug = 'schmelzi'")).scalar_one()
    with tenant_session(make_sessionmaker(OWNER_URL), tid) as s:
        actions = list(
            s.execute(
                text(
                    "select action from core.audit_event "
                    "where data->>'email' = :e or actor_user_id = "
                    "(select id from core.app_user where email = :e) order by id"
                ),
                {"e": email},
            ).scalars()
        )
        assert audit.verify_chain(s, tid).ok
    assert actions == ["auth.login_failed", "auth.password_ok", "auth.mfa_enabled", "auth.login"]
