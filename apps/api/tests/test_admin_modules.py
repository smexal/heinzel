"""Module administration and navigation areas."""

import pytest
from _flows import enrol

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture
def admin(api, make_user):
    return enrol(api, make_user(roles=("admin",)))


def _modules(api):
    r = api.get("/api/v1/admin/modules")
    assert r.status_code == 200, r.text
    return r.json()


def _aufgaben(data):
    return next(m for m in data["modules"] if m["key"] == "aufgaben")


def _save(api, data, **changes):
    m = _aufgaben(data)
    body = {
        "version": data["version"],
        "enabled": m["status"] == "active",
        "area": m["area"],
        "hidden_children": [c["path"] for c in m["children"] if not c["visible"]],
        "settings": m["settings"],
        "mcp_disabled": [i["name"] for i in m["mcp"] if not i["enabled"]],
        **changes,
    }
    return api.put("/api/v1/admin/modules/aufgaben", json=body)


def test_staff_cannot_manage_modules(api, make_user):
    enrol(api, make_user())
    assert api.get("/api/v1/admin/modules").status_code == 403


def test_overview(api, admin):
    data = _modules(api)
    m = _aufgaben(data)
    assert m["status"] == "active" and m["name"] == "Aufgaben"
    assert m["settings"]["personal_list_name"] == "Meine Aufgaben"
    assert m["settings_schema"]["properties"]["reminder"]["enum"]
    perm = next(p for p in m["permissions"] if p["id"] == "aufgaben.use")
    assert "Administration" in perm["roles"] and "Mitarbeitende" in perm["roles"]
    kinds = {i["name"]: i["kind"] for i in m["mcp"]}
    assert kinds["aufgaben.task.list"] == "read" and kinds["heute-faellig"] == "prompt"
    assert [a["key"] for a in data["areas"]] == ["unterhalt", "verwaltung", "it"]


def test_area_settings_and_disable_reach_the_shell(api, admin):
    data = _modules(api)
    r = _save(
        api,
        data,
        area="verwaltung",
        settings={**_aufgaben(data)["settings"], "quick_action_enabled": False},
    )
    assert r.status_code == 200 and r.json()["changed"]
    shell = api.get("/api/v1/shell").json()
    verwaltung = next(s for s in shell["navigation"] if s["key"] == "verwaltung")
    assert [i["label"] for i in verwaltung["items"]] == ["Aufgaben"]
    assert shell["quick_actions"] == []

    data = _modules(api)
    assert _save(api, data, enabled=False).status_code == 200
    shell = api.get("/api/v1/shell").json()
    labels = [i["label"] for s in shell["navigation"] for i in s["items"]]
    assert "Aufgaben" not in labels
    ev = api.get("/api/v1/admin/audit", params={"q": "module.disabled"}).json()["events"][0]
    assert ev["target_id"] == "aufgaben"

    data = _modules(api)
    _save(
        api,
        data,
        enabled=True,
        area=None,
        settings=_aufgaben(data)["settings"] | {"quick_action_enabled": True},
    )
    assert api.get("/api/v1/shell").json()["quick_actions"]


def test_invalid_module_input(api, admin):
    data = _modules(api)
    assert _save(api, data, area="nope").json()["detail"] == "unknown_area"
    bad = _save(api, data, settings={"reminder": "pigeon"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_settings"
    assert _save(api, data, mcp_disabled=["x.y"]).json()["detail"] == "unknown_mcp_item"
    assert _save(api, {**data, "version": data["version"] - 1}).status_code == 409


def test_navigation_areas(api, admin):
    s = api.get("/api/v1/admin/settings").json()
    nav = s["sections"]["navigation"]
    areas = [{"key": a["key"], "label": a["label"]["de"]} for a in nav["areas"]]
    body = {"hide_empty_areas": False, "areas": [*areas, {"key": None, "label": "Küche"}]}
    r = api.put("/api/v1/admin/settings/navigation", json={"version": s["version"], "values": body})
    assert r.status_code == 200
    shell = api.get("/api/v1/shell").json()
    assert "kuche" in [x["key"] for x in shell["navigation"]]  # empty areas now shown

    # an area in use cannot be removed
    data = _modules(api)
    _save(api, data, area="kuche")
    s = api.get("/api/v1/admin/settings").json()
    r = api.put(
        "/api/v1/admin/settings/navigation",
        json={"version": s["version"], "values": {"hide_empty_areas": True, "areas": areas}},
    )
    assert r.status_code == 409 and r.json()["detail"] == "area_in_use:kuche"
    data = _modules(api)
    _save(api, data, area=None)
    s = api.get("/api/v1/admin/settings").json()
    r = api.put(
        "/api/v1/admin/settings/navigation",
        json={"version": s["version"], "values": {"hide_empty_areas": True, "areas": areas}},
    )
    assert r.status_code == 200
