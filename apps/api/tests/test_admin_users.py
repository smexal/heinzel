"""Benutzer & Rollen: invitations, deactivation, MFA reset, role changes and their guard rails."""

import pytest
from _flows import enrol, link_token, login
from _support import PASSWORD

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture
def admin(api, make_user):
    email = make_user(roles=("admin",))
    enrol(api, email)
    me = api.get("/api/v1/me").json()
    return me


def _invite(api, email="neu-{}@schmelzi.test", roles=("staff",)):
    import uuid

    email = email.format(uuid.uuid4().hex[:6])
    r = api.post(
        "/api/v1/admin/users",
        json={"email": email, "display_name": "Nina Neu", "roles": list(roles)},
    )
    return r


def test_staff_cannot_use_admin_endpoints(api, make_user):
    enrol(api, make_user())
    assert api.get("/api/v1/admin/users").status_code == 403
    assert api.get("/api/v1/admin/roles").status_code == 403


def test_invite_flow_end_to_end(api, admin):
    r = _invite(api)
    assert r.status_code == 201 and r.json()["mail_sent"]
    user = r.json()["user"]
    assert user["status"] == "invited" and user["roles"] == ["staff"]
    assert user["invite_expires_at"] is not None
    assert (
        api.post(
            "/api/v1/admin/users", json={**{"email": user["email"]}, "display_name": "x"}
        ).status_code
        == 409
    )

    mail = api.app.state.mailer.sent[-1]
    assert mail.to == user["email"] and "eingeladen" in mail.text
    token = link_token(mail.text)

    api.cookies.clear()
    info = api.get(f"/api/v1/auth/token/{token}").json()
    assert info["purpose"] == "invite" and info["display_name"] == "Nina Neu"
    # an invited user cannot log in before accepting
    assert login(api, user["email"], PASSWORD).status_code == 401
    assert (
        api.post(
            "/api/v1/auth/password/set", json={"token": token, "password": PASSWORD}
        ).status_code
        == 204
    )
    enrol(api, user["email"])
    assert api.get("/api/v1/me").json()["roles"] == ["staff"]


def test_resend_invite_replaces_link(api, admin):
    user = _invite(api).json()["user"]
    first = link_token(api.app.state.mailer.sent[-1].text)
    r = api.post(f"/api/v1/admin/users/{user['id']}/invite")
    assert r.status_code == 200 and r.json()["mail_sent"]
    second = link_token(api.app.state.mailer.sent[-1].text)
    assert first != second
    assert api.get(f"/api/v1/auth/token/{first}").status_code == 404


def test_deactivate_ends_sessions_and_blocks_login(api, admin, make_user):
    from fastapi.testclient import TestClient

    email = make_user()
    other = TestClient(api.app, base_url="http://localhost")
    enrol(other, email)
    uid = other.get("/api/v1/me").json()["id"]

    r = api.post(f"/api/v1/admin/users/{uid}/deactivate")
    assert r.status_code == 200 and r.json()["status"] == "deactivated"
    assert other.get("/api/v1/me").status_code == 401
    other.cookies.clear()
    assert login(other, email).status_code == 401

    assert api.post(f"/api/v1/admin/users/{uid}/activate").json()["status"] == "active"


def test_admin_cannot_deactivate_self(api, admin):
    r = api.post(f"/api/v1/admin/users/{admin['id']}/deactivate")
    assert r.status_code == 409 and r.json()["detail"] == "cannot_deactivate_self"


def test_mfa_reset_forces_new_enrolment(api, admin, make_user):
    from fastapi.testclient import TestClient

    email = make_user()
    other = TestClient(api.app, base_url="http://localhost")
    enrol(other, email)
    uid = other.get("/api/v1/me").json()["id"]
    r = api.post(f"/api/v1/admin/users/{uid}/mfa-reset")
    assert r.status_code == 200 and r.json()["mfa_enabled"] is False
    assert other.get("/api/v1/me").status_code == 401
    other.cookies.clear()
    assert login(other, email).json() == {"next": "mfa_setup"}


def test_roles_change_and_last_admin_guard(api, admin, make_user):
    from fastapi.testclient import TestClient

    email = make_user()
    other = TestClient(api.app, base_url="http://localhost")
    enrol(other, email)
    uid = other.get("/api/v1/me").json()["id"]

    r = api.put(f"/api/v1/admin/users/{uid}/roles", json={"roles": ["staff", "admin"]})
    assert r.status_code == 200 and r.json()["roles"] == ["admin", "staff"]
    assert api.put(f"/api/v1/admin/users/{uid}/roles", json={"roles": ["nope"]}).status_code == 422
    # now two admins: removing one is fine
    r = api.put(f"/api/v1/admin/users/{uid}/roles", json={"roles": ["staff"]})
    assert r.json()["roles"] == ["staff"]


def test_last_admin_cannot_lose_admin_role(api, owner_engine, make_user):
    """In a tenant with exactly one admin, that admin keeps the role."""
    from sqlalchemy import text

    # isolate: deactivate every other admin of the shared test tenant first
    email = make_user(roles=("admin",))
    enrol(api, email)
    me = api.get("/api/v1/me").json()
    with owner_engine.begin() as c:
        tid = c.execute(text("select id from core.tenant where slug = 'schmelzi'")).scalar_one()
        c.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        c.execute(
            text(
                "update core.app_user set status = 'deactivated' where id <> :me and id in "
                "(select user_id from core.role_assignment ra "
                "join core.role r on r.id = ra.role_id where r.key = 'admin')"
            ),
            {"me": me["id"]},
        )
    r = api.put(f"/api/v1/admin/users/{me['id']}/roles", json={"roles": ["staff"]})
    assert r.status_code == 409 and r.json()["detail"] == "last_admin"


def test_users_admin_without_wildcard_cannot_grant_admin(api, owner_engine, make_user):
    """A user manager may not hand out roles with more rights than their own."""
    from sqlalchemy import text

    email = make_user()
    with owner_engine.begin() as c:
        tid = c.execute(text("select id from core.tenant where slug = 'schmelzi'")).scalar_one()
        c.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        rid = c.execute(
            text(
                "insert into core.role (tenant_id, key, name) values (:t, 'useradmin-' || "
                "substr(md5(random()::text), 1, 6), 'Benutzer-Admin') returning id"
            ),
            {"t": str(tid)},
        ).scalar_one()
        c.execute(
            text(
                "insert into core.role_permission (tenant_id, role_id, permission) "
                "values (:t, :r, 'core.users.manage')"
            ),
            {"t": str(tid), "r": rid},
        )
        c.execute(
            text(
                "insert into core.role_assignment (tenant_id, user_id, role_id) "
                "select :t, id, :r from core.app_user where email = :e"
            ),
            {"t": str(tid), "r": rid, "e": email},
        )
    enrol(api, email)
    r = _invite(api, roles=("admin",))
    assert r.status_code == 403 and r.json()["detail"] == "role_exceeds_own_permissions"


def test_roles_overview(api, admin):
    data = api.get("/api/v1/admin/roles").json()
    keys = [r["key"] for r in data["roles"]]
    assert keys[:2] == ["admin", "staff"] or set(keys[:2]) == {"admin", "staff"}
    admin_role = next(r for r in data["roles"] if r["key"] == "admin")
    assert "core.users.manage" in admin_role["permissions"]
    groups = {p["group"] for p in data["permissions"]}
    assert {"core", "aufgaben"} <= groups
