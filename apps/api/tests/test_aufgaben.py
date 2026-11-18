"""Aufgaben module: lists, tasks, assignment via Mein Eingang, pictures, search, widget, jobs."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from _flows import enrol
from fastapi.testclient import TestClient
from sqlalchemy import select

from heinzel_api.db import tenant_session
from heinzel_api.modules import JobContext

pytestmark = pytest.mark.usefixtures("seeded")

A = "/api/v1/aufgaben"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


def _client(api, make_user, roles=("staff",)):
    c = TestClient(api.app, base_url="http://localhost")
    enrol(c, make_user(roles))
    c.me = c.get("/api/v1/me").json()
    return c


def _tid(api):
    return api.app.state.registry.by_slug("schmelzi").id


def _svc():
    from heinzel_modules.aufgaben import service

    return service


def _new(c, title, **kw):
    r = c.post(f"{A}/tasks", json={"title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_personal_list_quick_add_sort_and_done(api, make_user):
    c = _client(api, make_user)
    lists = c.get(f"{A}/lists").json()
    assert [(x["kind"], x["name"], x["role"]) for x in lists["lists"]] == [
        ("personal", "Meine Aufgaben", "owner")
    ]
    today = date.today()
    _new(c, "Ohne Datum")
    _new(c, "Morgen", due_date=str(today + timedelta(days=1)))
    over = _new(c, "  Überfällig   alt ", due_date=str(today - timedelta(days=2)))
    assert over["title"] == "Überfällig alt" and over["due_tone"] == "over"
    assert over["due_label"].startswith("Überfällig · ")
    t = c.get(f"{A}/tasks").json()
    assert [x["title"] for x in t["tasks"]] == ["Überfällig alt", "Morgen", "Ohne Datum"]
    assert t["tasks"][1]["due_label"] == "Morgen" and t["tasks"][2]["due_label"] == "Kein Datum"

    done = c.post(f"{A}/tasks/{over['id']}/complete").json()
    assert done["status"] == "done" and done["due_label"] == "Erledigt"
    assert c.post(f"{A}/tasks/{over['id']}/complete").json()["done_at"] == done["done_at"]
    t = c.get(f"{A}/tasks").json()
    assert (t["open"], t["done"], len(t["tasks"])) == (2, 1, 2)
    assert len(c.get(f"{A}/tasks?done=true").json()["tasks"]) == 3
    assert c.post(f"{A}/tasks/{over['id']}/reopen").json()["status"] == "open"
    assert c.post(f"{A}/tasks", json={"title": "   "}).status_code == 422

    r = c.patch(f"{A}/tasks/{over['id']}", json={"title": "Neu", "due_date": None, "note": "x"})
    assert r.json()["title"] == "Neu" and r.json()["due_date"] is None and r.json()["note"] == "x"


def test_tasks_are_private_to_list_members(api, make_user):
    a, b = _client(api, make_user), _client(api, make_user)
    t = _new(a, "Geheim")
    assert b.get(f"{A}/tasks/{t['id']}").status_code == 404
    assert b.post(f"{A}/tasks/{t['id']}/complete").status_code == 404
    assert t["id"] not in {x["id"] for x in b.get(f"{A}/tasks").json()["tasks"]}


def test_shared_list_members_assignment_and_inbox(api, make_user):
    owner, member, outsider = (_client(api, make_user) for _ in range(3))
    lst = owner.post(f"{A}/lists", json={"name": "  IT-Team "}).json()
    assert lst["name"] == "IT-Team" and lst["role"] == "owner"
    lid = lst["id"]
    assert (
        owner.post(f"{A}/lists/{lid}/members", json={"user_id": member.me["id"]}).status_code == 204
    )
    names = {m["id"]: m["role"] for m in owner.get(f"{A}/lists/{lid}/members").json()}
    assert names == {owner.me["id"]: "owner", member.me["id"]: "member"}
    # the new member hears about it
    notice = member.get("/api/v1/inbox?view=notices").json()["items"][0]
    assert notice["title"] == "Neue geteilte Liste: IT-Team"
    # members cannot manage members
    assert (
        member.post(f"{A}/lists/{lid}/members", json={"user_id": outsider.me["id"]}).status_code
        == 403
    )

    # only members can be assigned (default setting)
    bad = owner.post(
        f"{A}/tasks", json={"title": "x", "list_id": lid, "assignee_id": outsider.me["id"]}
    )
    assert bad.status_code == 422 and bad.json()["detail"] == "assignee_not_member"

    due = str(date.today())
    t = _new(
        owner, "Firewall-Updates einplanen", list_id=lid, assignee_id=member.me["id"], due_date=due
    )
    assert t["assignee"]["id"] == member.me["id"] and t["list_name"] == "IT-Team"
    assert {p["id"] for p in t["assignable"]} == {owner.me["id"], member.me["id"]}
    item = member.get("/api/v1/inbox").json()["items"][0]
    assert item["title"] == "Zugewiesen: Firewall-Updates einplanen"
    assert item["source_label"] == "Aufgaben" and item["actions"][0]["key"] == "done"
    assert item["link"] == f"/aufgaben?aufgabe={t['id']}"
    assert outsider.get(f"{A}/tasks/{t['id']}").status_code == 404

    # the assignee ticks it off in Mein Eingang; the creator gets a notice
    r = member.post(f"/api/v1/inbox/{item['id']}/actions/done")
    assert r.status_code == 200 and r.json()["message"].startswith("Erledigt")
    assert owner.get(f"{A}/tasks/{t['id']}").json()["status"] == "done"
    assert member.get("/api/v1/inbox").json()["counts"]["tasks"] == 0
    n = owner.get("/api/v1/inbox?view=notices").json()["items"][0]
    assert n["title"] == "Erledigt: Firewall-Updates einplanen"

    # reassigning moves the inbox item
    t2 = _new(owner, "Laptop vorbereiten", list_id=lid, assignee_id=member.me["id"])
    owner.patch(f"{A}/tasks/{t2['id']}", json={"assignee_id": owner.me["id"]})
    assert member.get("/api/v1/inbox").json()["counts"]["tasks"] == 0

    # a member leaves: their open tasks become unassigned
    t3 = _new(owner, "Kabel ordnen", list_id=lid, assignee_id=member.me["id"])
    assert member.delete(f"{A}/lists/{lid}/members/{member.me['id']}").status_code == 204
    assert owner.get(f"{A}/tasks/{t3['id']}").json()["assignee"] is None
    assert owner.delete(f"{A}/lists/{lid}/members/{owner.me['id']}").status_code == 422

    # renaming and deleting are for the owner
    assert owner.put(f"{A}/lists/{lid}", json={"name": "IT"}).json()["name"] == "IT"
    assert owner.delete(f"{A}/lists/{lid}").status_code == 204
    assert owner.get(f"{A}/tasks/{t3['id']}").status_code == 404


def test_tenant_wide_assignment_setting(api, make_user, app_factory):
    owner, other = _client(api, make_user), _client(api, make_user)
    registry = api.app.state.registry
    entry = registry.by_slug("schmelzi")
    original = entry.config.modules[0].settings
    entry.config.modules[0].settings = {**original, "assign_scope": "tenant"}
    try:
        t = _new(owner, "Für dich", assignee_id=other.me["id"])
        # the assignee sees it though not a member of the personal list, may complete, not delete
        assert other.get(f"{A}/tasks/{t['id']}").json()["can_delete"] is False
        assert t["id"] in {x["id"] for x in other.get(f"{A}/tasks").json()["tasks"]}
        assert other.delete(f"{A}/tasks/{t['id']}").status_code == 403
        assert other.post(f"{A}/tasks/{t['id']}/complete").json()["status"] == "done"
    finally:
        entry.config.modules[0].settings = original


def test_sharing_needs_permission_and_setting(api, make_user, app_factory):
    c = _client(api, make_user)
    entry = api.app.state.registry.by_slug("schmelzi")
    original = entry.config.modules[0].settings
    entry.config.modules[0].settings = {**original, "shared_lists_enabled": False}
    try:
        assert c.get(f"{A}/lists").json()["can_share"] is False
        r = c.post(f"{A}/lists", json={"name": "X"})
        assert r.status_code == 422 and r.json()["detail"] == "shared_lists_disabled"
    finally:
        entry.config.modules[0].settings = original


def test_attachments_follow_task_visibility(api, make_user):
    a, b = _client(api, make_user), _client(api, make_user)
    t = _new(a, "Rampe vereist")
    up = a.post(
        "/api/v1/files?module=aufgaben",
        content=JPEG,
        headers={"x-filename": "rampe.jpg", "content-type": "application/octet-stream"},
    ).json()
    d = a.post(f"{A}/tasks/{t['id']}/attachments", json={"attachment_ids": [up["id"]]}).json()
    assert [x["id"] for x in d["attachments"]] == [up["id"]] and d["attachments_count"] == 1
    assert a.get(f"{A}/tasks").json()["tasks"][0]["attachments_count"] == 1
    assert b.get(up["url"]).status_code == 404  # not a member

    lst = a.post(f"{A}/lists", json={"name": "Unterhalt"}).json()
    a.post(f"{A}/lists/{lst['id']}/members", json={"user_id": b.me["id"]})
    a.patch(f"{A}/tasks/{t['id']}", json={"list_id": lst["id"]})
    assert b.get(up["url"]).status_code == 200  # now a member of the task's list

    d = a.delete(f"{A}/tasks/{t['id']}/attachments/{up['id']}").json()
    assert d["attachments"] == [] and a.get(up["url"]).status_code == 404

    pdf = a.post(
        "/api/v1/files?module=aufgaben",
        content=b"%PDF-1.7\n" + b"x" * 50,
        headers={"x-filename": "a.pdf", "content-type": "application/octet-stream"},
    ).json()
    d = a.post(f"{A}/tasks/{t['id']}/attachments", json={"attachment_ids": [pdf["id"]]}).json()
    assert [x["filename"] for x in d["attachments"]] == ["a.pdf"]
    assert a.get(pdf["url"]).headers["content-disposition"].startswith("attachment")


def test_search_finds_only_visible_tasks(api, make_user):
    a, b = _client(api, make_user), _client(api, make_user)
    tag = uuid.uuid4().hex[:8]
    t = _new(a, f"Offerte {tag} prüfen", note="Zwei Angebote vergleichen")
    groups = {g["key"]: g for g in a.get(f"/api/v1/search?q={tag}").json()["groups"]}
    hit = groups["aufgaben.task"]["items"][0]
    assert (
        hit["link"] == f"/aufgaben?aufgabe={t['id']}"
        and groups["aufgaben.task"]["label"] == "Aufgaben"
    )
    assert a.get(f"/api/v1/search?q={tag} angebote").json()["total"] == 1
    assert b.get(f"/api/v1/search?q={tag}").json()["total"] == 0
    a.delete(f"{A}/tasks/{t['id']}")
    assert a.get(f"/api/v1/search?q={tag}").json()["total"] == 0


def test_home_widget_due_today(api, make_user):
    c = _client(api, make_user)
    today = date.today()
    _new(c, "Heute", due_date=str(today))
    _new(c, "Gestern", due_date=str(today - timedelta(days=1)))
    _new(c, "Später", due_date=str(today + timedelta(days=3)))
    w = {x["key"]: x for x in c.get("/api/v1/home").json()["widgets"]}["heute-faellig"]
    assert [i["title"] for i in w["items"]] == ["Gestern", "Heute"]
    assert w["items"][0]["tone"] == "danger" and w["items"][0]["meta"].startswith("Überfällig seit")
    assert w["title"] == "Heute fällig" and w["link"] == "/aufgaben"


def _job_ctx(api):
    s = api.app.state
    return JobContext(
        db=s.db,
        tenants=s.registry.all(),
        manifests=s.manifests,
        mailer=s.mailer,
        storage=s.storage,
        settings=s.settings,
    )


def _job(api, name):
    return next(j for j in api.app.state.modules["aufgaben"].jobs if j.name == name)


def test_reminders_once_per_due_date(api, make_user):
    c = _client(api, make_user)
    t = _new(c, "Protokoll verschicken", due_date=str(date.today()))
    _job(api, "aufgaben.reminders").run(_job_ctx(api))
    items = c.get("/api/v1/inbox").json()["items"]
    assert [i["title"] for i in items] == ["Heute fällig: Protokoll verschicken"]
    c.post(f"/api/v1/inbox/{items[0]['id']}/done")
    _job(api, "aufgaben.reminders").run(_job_ctx(api))  # not again for the same date
    assert c.get("/api/v1/inbox").json()["counts"]["tasks"] == 0
    # a new due date earns a new reminder; completing closes it
    c.patch(f"{A}/tasks/{t['id']}", json={"due_date": str(date.today() - timedelta(days=1))})
    _job(api, "aufgaben.reminders").run(_job_ctx(api))
    assert c.get("/api/v1/inbox").json()["items"][0]["title"].startswith("Überfällig:")
    c.post(f"{A}/tasks/{t['id']}/complete")
    assert c.get("/api/v1/inbox").json()["counts"]["tasks"] == 0


def test_retention_deletes_old_done_tasks(api, make_user, app_factory):
    c = _client(api, make_user)
    t = _new(c, "Alt")
    c.post(f"{A}/tasks/{t['id']}/complete")
    task_model = __import__("heinzel_modules.aufgaben.models", fromlist=["Task"]).Task
    with tenant_session(app_factory, _tid(api)) as s:
        s.get(task_model, uuid.UUID(t["id"])).done_at = datetime.now(UTC) - timedelta(days=800)
    _job(api, "aufgaben.retention").run(_job_ctx(api))
    assert c.get(f"{A}/tasks/{t['id']}").status_code == 404


def test_deactivated_assignee_hands_tasks_back(api, make_user):
    owner, member = _client(api, make_user), _client(api, make_user)
    admin = _client(api, make_user, roles=("admin", "staff"))
    lst = owner.post(f"{A}/lists", json={"name": "Sekretariat"}).json()
    owner.post(f"{A}/lists/{lst['id']}/members", json={"user_id": member.me["id"]})
    t = _new(owner, "Briefe", list_id=lst["id"], assignee_id=member.me["id"])
    r = admin.post(f"/api/v1/admin/users/{member.me['id']}/deactivate")
    assert r.status_code == 200, r.text
    assert owner.get(f"{A}/tasks/{t['id']}").json()["assignee"]["id"] == owner.me["id"]
    titles = [i["title"] for i in owner.get("/api/v1/inbox").json()["items"]]
    assert "Zurück bei dir: Briefe" in titles


def test_disabled_module_answers_404(api, make_user):
    c = _client(api, make_user)
    entry = api.app.state.registry.by_slug("schmelzi")
    entry.config.modules[0].enabled = False
    try:
        r = c.get(f"{A}/lists")
        assert r.status_code == 404 and r.json()["detail"] == "module_disabled"
        assert "heute-faellig" not in {w["key"] for w in c.get("/api/v1/home").json()["widgets"]}
    finally:
        entry.config.modules[0].enabled = True


def test_tenant_isolation(app_factory, make_tenant):
    from heinzel_modules.aufgaben.models import TaskList

    from heinzel_api.models import User

    a, b = make_tenant(), make_tenant()
    with tenant_session(app_factory, a) as s:
        u = User(tenant_id=a, email=f"{uuid.uuid4().hex[:6]}@a.test", display_name="A")
        s.add(u)
        s.flush()
        s.add(TaskList(tenant_id=a, kind="personal", owner_id=u.id))
    with tenant_session(app_factory, b) as s:
        assert s.scalars(select(TaskList)).all() == []


def test_checklist(api, make_user):
    owner, member = _client(api, make_user), _client(api, make_user)
    lst = owner.post(f"{A}/lists", json={"name": "Sekretariat"}).json()
    owner.post(f"{A}/lists/{lst['id']}/members", json={"user_id": member.me["id"]})
    tag = uuid.uuid4().hex[:8]
    t = _new(
        owner,
        "Protokoll verschicken",
        list_id=lst["id"],
        assignee_id=member.me["id"],
        checklist=["Anhang holen", f"Präsenzliste {tag}"],
    )
    assert [c["text"] for c in t["checklist"]] == ["Anhang holen", f"Präsenzliste {tag}"]
    assert (t["checklist_total"], t["checklist_done"]) == (2, 0)
    tid = t["id"]

    d = member.post(f"{A}/tasks/{tid}/checklist", json={"text": "  An alle   senden "}).json()
    first, second, third = (c["id"] for c in d["checklist"])
    assert d["checklist"][2]["text"] == "An alle senden"

    # tick (idempotent), rename, move to the top, untick
    d = member.patch(f"{A}/tasks/{tid}/checklist/{first}", json={"done": True}).json()
    d = member.patch(f"{A}/tasks/{tid}/checklist/{first}", json={"done": True}).json()
    assert d["checklist"][0]["done"] and d["checklist"][0]["done_by"]["id"] == member.me["id"]
    assert (d["checklist_total"], d["checklist_done"]) == (3, 1)
    d = owner.patch(f"{A}/tasks/{tid}/checklist/{third}", json={"position": 0, "text": "Senden"})
    assert [c["text"] for c in d.json()["checklist"]] == [
        "Senden",
        "Anhang holen",
        f"Präsenzliste {tag}",
    ]
    d = owner.delete(f"{A}/tasks/{tid}/checklist/{second}").json()
    assert [c["id"] for c in d["checklist"]] == [third, first]

    # the list line, the assignee's inbox and the search know about it
    line = next(x for x in owner.get(f"{A}/tasks").json()["tasks"] if x["id"] == tid)
    assert (line["checklist_total"], line["checklist_done"]) == (2, 1)
    item = member.get("/api/v1/inbox").json()["items"][0]
    assert {"label": "Checkliste", "value": "1 von 2"} in item["facts"]
    owner.post(f"{A}/tasks/{tid}/checklist", json={"text": f"Archiv {tag}"})
    assert owner.get(f"/api/v1/search?q=archiv {tag}").json()["total"] == 1

    # outsiders cannot touch it; foreign item ids are not found
    outsider = _client(api, make_user)
    r = outsider.patch(f"{A}/tasks/{tid}/checklist/{first}", json={"done": False})
    assert r.status_code == 404
    other = _new(owner, "Andere")
    r = owner.patch(f"{A}/tasks/{other['id']}/checklist/{first}", json={"done": False})
    assert r.status_code == 404
    assert owner.post(f"{A}/tasks/{tid}/checklist", json={"text": " "}).status_code == 422

    # completing the task leaves the points as they are
    done = owner.post(f"{A}/tasks/{tid}/complete").json()
    assert [c["done"] for c in done["checklist"]] == [False, True, False]


def test_markdown_note_is_searchable_without_markers(api, make_user):
    c = _client(api, make_user)
    tag = uuid.uuid4().hex[:8]
    _new(c, "Mit Notiz", note=f"# Ablauf\n- **{tag}** prüfen\n- [Doku](https://schmelzi.ch/doku)")
    hit = c.get(f"/api/v1/search?q={tag}").json()["groups"][0]["items"][0]
    assert hit["snippet"] and "**" not in hit["snippet"] and "#" not in hit["snippet"]
    assert c.get(f"/api/v1/search?q={tag} doku").json()["total"] == 1
