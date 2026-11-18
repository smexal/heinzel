"""Custom roles and the step-up confirmation for permission changes."""

import pytest
from _flows import enrol, step_up

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture
def admin(api, make_user):
    totp = enrol(api, make_user(roles=("admin",)))
    return totp


def test_role_changes_need_step_up(api, admin):
    body = {"name": "Unterhalt", "permissions": ["aufgaben.use"]}
    r = api.post("/api/v1/admin/roles", json=body)
    assert r.status_code == 403 and r.json()["detail"] == "step_up_required"
    bad = api.post("/api/v1/auth/step-up", json={"code": "000000"})
    assert bad.status_code == 401
    step_up(api, admin)
    assert api.post("/api/v1/admin/roles", json=body).status_code == 201


def test_create_edit_delete_custom_role(api, admin):
    step_up(api, admin)
    r = api.post(
        "/api/v1/admin/roles",
        json={
            "name": "Sekretariat Süd",
            "description": "Empfang",
            "permissions": ["aufgaben.use", "core.audit.read"],
        },
    )
    assert r.status_code == 201
    role = r.json()
    assert role["key"].startswith("sekretariat-sud") and role["is_system"] is False
    assert role["permissions"] == ["aufgaben.use", "core.audit.read"]

    r = api.put(
        f"/api/v1/admin/roles/{role['key']}",
        json={"name": "Sekretariat", "permissions": ["aufgaben.use"]},
    )
    assert r.json()["name"] == "Sekretariat" and r.json()["permissions"] == ["aufgaben.use"]

    ev = api.get("/api/v1/admin/audit", params={"q": "role.updated"}).json()["events"][0]
    assert ev["data"]["removed"] == ["core.audit.read"]

    assert api.delete(f"/api/v1/admin/roles/{role['key']}").status_code == 204
    keys = [x["key"] for x in api.get("/api/v1/admin/roles").json()["roles"]]
    assert role["key"] not in keys


def test_role_in_use_cannot_be_deleted(api, admin, make_user):
    step_up(api, admin)
    role = api.post("/api/v1/admin/roles", json={"name": "Team", "permissions": []}).json()
    users = api.get("/api/v1/admin/users").json()
    uid = users[0]["id"]
    roles = users[0]["roles"] + [role["key"]]
    assert api.put(f"/api/v1/admin/users/{uid}/roles", json={"roles": roles}).status_code == 200
    r = api.delete(f"/api/v1/admin/roles/{role['key']}")
    assert r.status_code == 409 and r.json()["detail"] == "role_in_use"


def test_system_roles_are_protected(api, admin):
    step_up(api, admin)
    assert api.delete("/api/v1/admin/roles/staff").json()["detail"] == "system_role"
    r = api.put("/api/v1/admin/roles/admin", json={"name": "x", "permissions": []})
    assert r.json()["detail"] == "admin_role_fixed"
    # staff permissions can be changed, its name not
    r = api.put(
        "/api/v1/admin/roles/staff", json={"name": "Anders", "permissions": ["aufgaben.use"]}
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Mitarbeitende" and r.json()["permissions"] == ["aufgaben.use"]
    api.put(
        "/api/v1/admin/roles/staff",
        json={"name": "Mitarbeitende", "permissions": ["aufgaben.use", "aufgaben.list.share"]},
    )


def test_unknown_permission_refused(api, admin):
    step_up(api, admin)
    r = api.post("/api/v1/admin/roles", json={"name": "X", "permissions": ["*"]})
    assert r.status_code == 422 and r.json()["detail"] == "unknown_permission"


def test_seeding_keeps_removed_defaults_removed(api, admin, seeded):
    from heinzel_api.cli import seed_tenants

    step_up(api, admin)
    api.put(
        "/api/v1/admin/roles/staff", json={"name": "Mitarbeitende", "permissions": ["aufgaben.use"]}
    )
    seed_tenants(seeded)
    staff = next(r for r in api.get("/api/v1/admin/roles").json()["roles"] if r["key"] == "staff")
    assert staff["permissions"] == ["aufgaben.use"]
    api.put(
        "/api/v1/admin/roles/staff",
        json={"name": "Mitarbeitende", "permissions": ["aufgaben.use", "aufgaben.list.share"]},
    )
