"""Mein Eingang: delivery, dedupe by reference, views, states, badge, core notices."""

import uuid

import pytest
from _flows import enrol, link_token, step_up
from _support import PASSWORD
from fastapi.testclient import TestClient

from heinzel_api import inbox
from heinzel_api.db import tenant_session

pytestmark = pytest.mark.usefixtures("seeded")


def _me(api):
    return uuid.UUID(api.get("/api/v1/me").json()["id"])


def _tid(api):
    return api.app.state.registry.by_slug("schmelzi").id


def _badge(api):
    nav = api.get("/api/v1/shell").json()["navigation"][0]["items"]
    return next(i for i in nav if i["key"] == "inbox")["badge"]


def test_deliver_views_states_and_badge(api, make_user, app_factory):
    enrol(api, make_user())
    uid = _me(api)
    with tenant_session(app_factory, _tid(api)) as s:
        inbox.deliver(
            s,
            _tid(api),
            [uid],
            source="aufgaben",
            kind="task",
            title="Protokoll senden",
            facts=[("Liste", "Sekretariat")],
            ref_type="task",
            ref_id="1",
        )
        inbox.deliver(s, _tid(api), [uid], source="core", kind="notice", title="Rollen geändert")
    page = api.get("/api/v1/inbox").json()
    assert [i["title"] for i in page["items"]] == ["Protokoll senden", "Rollen geändert"]
    assert page["counts"] == {"open": 2, "tasks": 1, "notices": 1, "unread": 2}
    assert page["items"][0]["source_label"] == "Aufgaben"
    assert page["items"][0]["facts"] == [{"label": "Liste", "value": "Sekretariat"}]
    assert _badge(api) == 2

    task_id = page["items"][0]["id"]
    assert api.post(f"/api/v1/inbox/{task_id}/read").json()["read"] is True
    assert _badge(api) == 1
    assert api.post(f"/api/v1/inbox/{task_id}/done").json()["done"] is True
    assert [i["title"] for i in api.get("/api/v1/inbox?view=done").json()["items"]] == [
        "Protokoll senden"
    ]
    assert [i["title"] for i in api.get("/api/v1/inbox?view=notices").json()["items"]] == [
        "Rollen geändert"
    ]
    assert api.post("/api/v1/inbox/read-all").json()["marked"] == 1
    assert _badge(api) is None


def test_redelivery_updates_and_resolve_closes(api, make_user, app_factory):
    enrol(api, make_user())
    uid = _me(api)
    tid = _tid(api)
    with tenant_session(app_factory, tid) as s:
        inbox.deliver(
            s, tid, [uid], source="aufgaben", kind="task", title="A", ref_type="task", ref_id="9"
        )
    item = api.get("/api/v1/inbox").json()["items"][0]
    api.post(f"/api/v1/inbox/{item['id']}/read")
    with tenant_session(app_factory, tid) as s:
        inbox.deliver(
            s,
            tid,
            [uid],
            source="aufgaben",
            kind="task",
            title="A (geändert)",
            ref_type="task",
            ref_id="9",
        )
    items = api.get("/api/v1/inbox").json()["items"]
    assert len(items) == 1 and items[0]["title"] == "A (geändert)" and not items[0]["read"]
    with tenant_session(app_factory, tid) as s:
        assert inbox.resolve(s, source="aufgaben", ref_type="task", ref_id="9") == 1
    assert api.get("/api/v1/inbox").json()["items"] == []


def test_items_are_private(api, make_user, app_factory):
    enrol(api, make_user())
    uid = _me(api)
    with tenant_session(app_factory, _tid(api)) as s:
        [item] = inbox.deliver(s, _tid(api), [uid], source="core", kind="notice", title="Privat")
        item_id = item.id
    other = TestClient(api.app, base_url="http://localhost")
    enrol(other, make_user())
    assert other.get("/api/v1/inbox").json()["items"] == []
    assert other.post(f"/api/v1/inbox/{item_id}/read").status_code == 404


def test_actions_dispatch_to_source(api, make_user, app_factory):
    enrol(api, make_user())
    uid = _me(api)
    with tenant_session(app_factory, _tid(api)) as s:
        inbox.deliver(
            s,
            _tid(api),
            [uid],
            source="aufgaben",
            kind="task",
            title="Übernehmen?",
            actions=[inbox.Action("take", "Selbst übernehmen", "primary")],
        )
    item = api.get("/api/v1/inbox").json()["items"][0]
    assert api.post(f"/api/v1/inbox/{item['id']}/actions/take").status_code == 409  # no handler
    calls = []
    inbox.register_action("aufgaben", lambda s, it, key, u: calls.append(key) or "Übernommen.")
    try:
        r = api.post(f"/api/v1/inbox/{item['id']}/actions/take")
        assert r.status_code == 200 and r.json()["message"] == "Übernommen." and calls == ["take"]
        assert api.post(f"/api/v1/inbox/{item['id']}/actions/other").status_code == 409
    finally:
        inbox._handlers.pop("aufgaben", None)


def test_core_notices_for_invite_and_roles(api, make_user):
    admin_totp = enrol(api, make_user(roles=("admin",)))
    r = api.post(
        "/api/v1/admin/users",
        json={"email": f"n{uuid.uuid4().hex[:5]}@schmelzi.test", "display_name": "Nina Neu"},
    )
    user = r.json()["user"]
    token = link_token(api.app.state.mailer.sent[-1].text)
    guest = TestClient(api.app, base_url="http://localhost")
    guest.post("/api/v1/auth/password/set", json={"token": token, "password": PASSWORD})
    titles = [i["title"] for i in api.get("/api/v1/inbox").json()["items"]]
    assert "Nina Neu hat die Einladung angenommen" in titles

    step_up(api, admin_totp)
    api.put(f"/api/v1/admin/users/{user['id']}/roles", json={"roles": ["staff", "admin"]})
    enrol(guest, user["email"])
    notice = guest.get("/api/v1/inbox").json()["items"][0]
    assert notice["title"] == "Deine Rollen wurden geändert"
    assert notice["context"] == "Neu: Administration" and notice["actor_name"] == "Ada Admin"
