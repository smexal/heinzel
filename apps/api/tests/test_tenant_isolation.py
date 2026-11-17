"""Row level security: the runtime role only ever sees the bound tenant's rows."""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from heinzel_api.db import tenant_session
from heinzel_api.models import Tenant, User

pytestmark = pytest.mark.usefixtures("migrated")


def _add_user(factory, tenant_id, email):
    with tenant_session(factory, tenant_id) as s:
        s.add(User(tenant_id=tenant_id, email=email, display_name=email))


def test_runtime_role_cannot_bypass_rls(app_engine):
    with app_engine.connect() as c:
        row = c.execute(
            text("select rolsuper, rolbypassrls from pg_roles where rolname = current_user")
        ).one()
    assert row == (False, False)


def test_sees_only_bound_tenant(app_factory, make_tenant):
    a, b = make_tenant(), make_tenant()
    _add_user(app_factory, a, "anna@a.test")
    _add_user(app_factory, b, "bruno@b.test")

    with tenant_session(app_factory, a) as s:
        emails = set(s.scalars(select(User.email)))
    assert "anna@a.test" in emails and "bruno@b.test" not in emails


def test_no_tenant_bound_sees_nothing(app_factory, make_tenant):
    a = make_tenant()
    _add_user(app_factory, a, "x@a.test")
    with app_factory() as s:
        assert s.scalar(select(func.count()).select_from(User)) == 0


def test_cannot_write_into_other_tenant(app_factory, make_tenant):
    a, b = make_tenant(), make_tenant()
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        tenant_session(app_factory, a) as s,
    ):
        s.add(User(tenant_id=b, email="evil@b.test", display_name="evil"))


def test_cannot_move_row_to_other_tenant(app_factory, make_tenant):
    a, b = make_tenant(), make_tenant()
    _add_user(app_factory, a, "move@a.test")
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        tenant_session(app_factory, a) as s,
    ):
        user = s.scalar(select(User).where(User.email == "move@a.test"))
        user.tenant_id = b


def test_tenant_registry_is_read_only(app_factory):
    with pytest.raises(DBAPIError, match="permission denied"), app_factory() as s, s.begin():
        s.add(Tenant(slug=f"x-{uuid.uuid4().hex[:6]}", display_name="x"))


def test_setting_does_not_leak_to_next_transaction(app_factory, make_tenant):
    a = make_tenant()
    _add_user(app_factory, a, "leak@a.test")
    with app_factory() as s:
        with s.begin():
            s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(a)})
            assert s.scalar(select(func.count()).select_from(User)) >= 1
        with s.begin():
            assert s.scalar(select(func.count()).select_from(User)) == 0
