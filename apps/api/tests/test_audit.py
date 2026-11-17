import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from heinzel_api import audit
from heinzel_api.db import tenant_session
from heinzel_api.models import AuditEvent

pytestmark = pytest.mark.usefixtures("migrated")


@pytest.fixture
def factory(app_factory):
    return app_factory


def _record(factory, tenant_id, n=3):
    with tenant_session(factory, tenant_id) as s:
        for i in range(n):
            audit.record(s, tenant_id, "test.event", data={"i": i, "ü": "ä"}, ip="::1")


def test_chain_is_valid_and_per_tenant(factory, make_tenant):
    a, b = make_tenant(), make_tenant()
    _record(factory, a)
    _record(factory, b, 2)
    with tenant_session(factory, a) as s:
        check = audit.verify_chain(s, a)
        first = s.scalars(select(AuditEvent).order_by(AuditEvent.id)).first()
    assert check.ok and check.events == 3
    assert first.prev_hash == audit.GENESIS


def test_runtime_role_cannot_change_or_delete(factory, make_tenant):
    a = make_tenant()
    _record(factory, a, 1)
    for stmt in ("update core.audit_event set action = 'x'", "delete from core.audit_event"):
        with pytest.raises(DBAPIError, match="permission denied"), tenant_session(factory, a) as s:
            s.execute(text(stmt))


def test_owner_is_stopped_by_trigger(owner_engine, make_tenant, factory):
    a = make_tenant()
    _record(factory, a, 1)
    with pytest.raises(DBAPIError, match="append-only"), owner_engine.begin() as c:
        c.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(a)})
        c.execute(text("update core.audit_event set action = 'x'"))


def test_tampering_is_detected(owner_engine, make_tenant, factory):
    a = make_tenant()
    _record(factory, a, 3)
    with owner_engine.begin() as c:
        c.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(a)})
        c.execute(text("alter table core.audit_event disable trigger audit_event_no_update"))
        c.execute(
            text(
                "update core.audit_event set data = '{\"i\": 99}' where id = "
                "(select min(id) + 1 from core.audit_event where tenant_id = :t)"
            ),
            {"t": str(a)},
        )
        c.execute(text("alter table core.audit_event enable trigger audit_event_no_update"))
    with tenant_session(factory, a) as s:
        check = audit.verify_chain(s, a)
    assert not check.ok and check.reason == "content does not match hash"
