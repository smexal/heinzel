import pytest
from _flows import enrol

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture
def admin(api, make_user):
    email = make_user(roles=("admin",))
    enrol(api, email)
    return api.get("/api/v1/me").json()


def test_staff_cannot_read_audit(api, make_user):
    enrol(api, make_user())
    assert api.get("/api/v1/admin/audit").status_code == 403
    assert api.get("/api/v1/admin/audit/export.csv").status_code == 403


def test_list_filter_and_page(api, admin):
    page = api.get("/api/v1/admin/audit", params={"actor": admin["id"], "limit": 2}).json()
    assert page["chain"]["ok"] is True
    assert len(page["events"]) == 2 and page["next_before_id"] is not None
    first = page["events"][0]
    assert first["actor_name"] == "Ada Admin" and first["channel"] == "web"
    assert any(a["id"] == admin["id"] for a in page["actors"])

    older = api.get(
        "/api/v1/admin/audit",
        params={"actor": admin["id"], "before_id": page["next_before_id"]},
    ).json()
    assert all(e["id"] < page["next_before_id"] for e in older["events"])

    logins = api.get(
        "/api/v1/admin/audit", params={"q": "auth.login", "actor": admin["id"]}
    ).json()["events"]
    assert logins and all("auth.login" in e["action"] for e in logins)
    core = api.get("/api/v1/admin/audit", params={"area": "core"}).json()["events"]
    assert core and all(
        e["action"].split(".")[0] in {"auth", "user", "tenant", "audit"} for e in core
    )


def test_target_names_resolved(api, admin):
    import uuid

    email = f"t-{uuid.uuid4().hex[:6]}@schmelzi.test"
    api.post("/api/v1/admin/users", json={"email": email, "display_name": "Tina Target"})
    ev = api.get("/api/v1/admin/audit", params={"q": "user.invited"}).json()["events"][0]
    assert ev["target_name"] == "Tina Target"


def test_export_is_csv_and_audited(api, admin):
    r = api.get("/api/v1/admin/audit/export.csv", params={"actor": admin["id"]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.lstrip("﻿").splitlines()
    assert lines[0].startswith("id;zeit_utc;person")
    assert len(lines) > 1
    ev = api.get("/api/v1/admin/audit", params={"q": "audit.exported"}).json()["events"][0]
    assert ev["actor_user_id"] == admin["id"] and ev["data"]["rows"] == len(lines) - 1
