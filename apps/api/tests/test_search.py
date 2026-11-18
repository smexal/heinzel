"""Global search: index, permissions (twice), pages, highlights."""

import uuid

import pytest
from _flows import enrol
from sqlalchemy import select

from heinzel_api import search
from heinzel_api.db import tenant_session
from heinzel_api.models import User

pytestmark = pytest.mark.usefixtures("seeded")


def _tid(api):
    return api.app.state.registry.by_slug("schmelzi").id


def _search(api, q, **params):
    r = api.get("/api/v1/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _groups(result):
    return {g["key"]: g for g in result["groups"]}


def _rename(app_factory, tid, email, name, status=None):
    with tenant_session(app_factory, tid) as s:
        user = s.scalar(select(User).where(User.email == email))
        user.display_name = name
        if status:
            user.status = status


def test_requires_login(api):
    assert api.get("/api/v1/search?q=abc").status_code == 401


def test_people_only_for_user_admins_and_kept_current(api, make_user, app_factory):
    tag = uuid.uuid4().hex[:6]
    person = make_user()
    _rename(app_factory, _tid(api), person, f"Zoë Brändli {tag}")

    enrol(api, make_user(("admin", "staff")))
    res = _search(api, f"zoe brand {tag}")
    people = _groups(res)["core.person"]
    hit = people["items"][0]
    assert hit["title"] == f"Zoë Brändli {tag}" and hit["meta"] == person
    assert hit["title_hl"] == [[0, 3], [4, 9], [12, 18]]
    assert hit["link"].startswith("/admin/benutzer?q=")

    _rename(app_factory, _tid(api), person, f"Zoë Brändli {tag}", status="deactivated")
    hit = _groups(_search(api, tag))["core.person"]["items"][0]
    assert hit["chip"] == {"label": "Deaktiviert", "tone": "neutral"}

    staff = api.__class__(api.app, base_url="http://localhost")
    enrol(staff, make_user())
    assert "core.person" not in _groups(_search(staff, tag))


def test_module_documents_filtered_twice(api, make_user, app_factory):
    tid, tag = _tid(api), uuid.uuid4().hex[:6]
    with tenant_session(app_factory, tid) as s:
        for i, perm in enumerate(["aufgaben.use", "aufgaben.use", "core.audit.read"]):
            search.index(
                s,
                tid,
                module="aufgaben",
                entity_type="task",
                entity_id=f"{tag}-{i}",
                title=f"Fenstergriff {tag} Nummer {i}",
                body="Im Atelier beim Werkraum ist der Griff lose.",
                meta="IT-Team",
                link=f"/aufgaben/{i}",
                permission=perm,
                chip={"label": "Geplant", "tone": "neutral"},
            )
    search.register_provider(
        "aufgaben", "task", can_view=lambda s, uid, ids: {i for i in ids if not i.endswith("-1")}
    )
    try:
        enrol(api, make_user())
        res = _search(api, f"{tag} werkraum")
        tasks = _groups(res)["aufgaben.task"]
        # -1 hidden by can_view, -2 by permission: never counted
        assert tasks["count"] == 1 and tasks["label"] == "Aufgaben"
        assert tasks["icon"] == "check-square"
        item = tasks["items"][0]
        assert item["id"] == f"{tag}-0" and item["chip"]["label"] == "Geplant"
        assert "Werkraum" in item["snippet"]
        a, b = item["snippet_hl"][0]
        assert item["snippet"][a:b] == "Werkraum"
        # German stemming: plural finds the singular
        assert _groups(_search(api, f"{tag} fenstergriffe")).get("aufgaben.task")
    finally:
        search.register_provider("aufgaben", "task", can_view=lambda s, uid, ids: set(ids))
        with tenant_session(app_factory, tid) as s:
            search.remove(s, tid, module="aufgaben", entity_type="task")


def test_search_disabled_by_module_setting(api, make_user, app_factory):
    tid, tag = _tid(api), uuid.uuid4().hex[:6]
    with tenant_session(app_factory, tid) as s:
        search.index(
            s, tid, module="aufgaben", entity_type="task", entity_id=tag, title=tag, link="/a"
        )
    tenant = api.app.state.registry.by_slug("schmelzi").config
    off = tenant.model_copy(deep=True)
    off.modules[0].settings = {"search_enabled": False}
    perms = {"aufgaben.use"}
    with tenant_session(app_factory, tid) as s:
        kw = dict(manifests=api.app.state.manifests, user_id=uuid.uuid4(), permissions=perms)
        assert search.run(s, tenant=tenant, q=tag, **kw).total == 1
        assert search.run(s, tenant=off, q=tag, **kw).total == 0
        search.remove(s, tid, module="aufgaben", entity_id=tag, entity_type="task")


def test_pages_follow_permissions(api, make_user):
    enrol(api, make_user())
    assert _search(api, "audit")["total"] == 0
    pages = _groups(_search(api, "dunkel"))["pages"]["items"]
    assert pages[0]["link"] == "/profil?tab=appearance"

    admin = api.__class__(api.app, base_url="http://localhost")
    enrol(admin, make_user(("admin", "staff")))
    pages = _groups(_search(admin, "audit"))["pages"]
    assert pages["items"][0] == {
        "id": "/admin/audit",
        "title": "Audit-Log",
        "title_hl": [[0, 5]],
        "meta": "Administration",
        "snippet": None,
        "snippet_hl": [],
        "link": "/admin/audit",
        "chip": None,
    }
    smtp = _groups(_search(admin, "smtp"))["pages"]["items"]
    assert smtp[0]["link"] == "/admin/einstellungen?tab=email"


def test_short_or_empty_queries(api, make_user):
    enrol(api, make_user())
    assert _search(api, "a")["groups"] == []
    assert _search(api, "  ")["total"] == 0
    assert _search(api, "&|!:*()")["total"] == 0  # tsquery syntax is never passed through


def test_highlights():
    assert search.highlights("Rampe beim Eingang vereist", ["ein"]) == [(11, 14)]
    assert search.highlights("Straße", ["strass"]) == [(0, 5)]
    assert search.highlights("Zoë", ["zoe"]) == [(0, 3)]


def test_index_is_tenant_isolated(app_factory, make_tenant):
    from sqlalchemy import text

    a, b = make_tenant(), make_tenant()
    with tenant_session(app_factory, a) as s:
        search.index(s, a, module="core", entity_type="x", entity_id="1", title="Geheim", link="/")
    with tenant_session(app_factory, b) as s:
        n = s.execute(text("select count(*) from core.search_document")).scalar_one()
    assert n == 0
