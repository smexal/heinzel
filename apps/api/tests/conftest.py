import uuid

import pytest
from _support import APP_URL, OWNER_URL, PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text

from heinzel_api.config import Settings
from heinzel_api.main import create_app


def _db_available() -> bool:
    """Reach the test database; create it on first use (the docker owner may create databases)."""
    try:
        with create_engine(OWNER_URL).connect() as c:
            c.execute(text("select 1"))
        return True
    except Exception:
        pass
    try:
        url = make_url(OWNER_URL)
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f'create database "{url.database}"'))
        admin.dispose()
        return True
    except Exception:
        return False


DB = _db_available()
requires_db = pytest.mark.skipif(not DB, reason="test database not reachable")


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        env="test",
        database_url=APP_URL,
        migration_database_url=OWNER_URL,
        secret_key="test-secret-key-0123456789",
    )


@pytest.fixture(scope="session")
def migrated(settings):
    """Fresh schema for the whole test run: downgrade to base, upgrade to head."""
    if not DB:
        pytest.skip("test database not reachable")
    from heinzel_api.cli import run_migrations

    run_migrations(OWNER_URL, "base", down=True)
    run_migrations(OWNER_URL, "head")
    return settings


@pytest.fixture(scope="session")
def owner_engine(migrated):
    engine = create_engine(OWNER_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_factory(migrated):
    """Session factory for the runtime role (RLS applies)."""
    from heinzel_api.db import make_sessionmaker

    return make_sessionmaker(APP_URL)


@pytest.fixture(scope="session")
def app_engine(migrated):
    engine = create_engine(APP_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def make_tenant(owner_engine):
    """Insert a tenant row with a unique slug; returns its id."""

    def _make(slug: str | None = None) -> uuid.UUID:
        slug = slug or f"t-{uuid.uuid4().hex[:10]}"
        with owner_engine.begin() as c:
            return c.execute(
                text(
                    "insert into core.tenant (slug, display_name) values (:s, :s) "
                    "on conflict (slug) do update set slug = excluded.slug returning id"
                ),
                {"s": slug},
            ).scalar_one()

    return _make


@pytest.fixture
def client():
    """App without a signed-in user. Endpoints that need the database are not used."""
    with TestClient(create_app(), base_url="http://localhost") as c:
        yield c


@pytest.fixture(scope="session")
def seeded(migrated):
    """The repository tenants (schmelzi) registered, with system roles."""
    from heinzel_api.cli import seed_tenants

    seed_tenants(migrated)
    return migrated


@pytest.fixture
def api(seeded):
    """App on the test database, talking to it as tenant schmelzi (host localhost)."""
    from heinzel_api.files import MemoryStorage
    from heinzel_api.mail import MemoryMailer
    from heinzel_api.ratelimit import MemoryRateLimiter

    class FakeScanner:
        """Marks uploads containing EVIL as infected."""

        def scan(self, data: bytes) -> str:
            return "infected" if b"EVIL" in data else "clean"

    app = create_app(
        seeded,
        mailer=MemoryMailer(),
        ratelimiter=MemoryRateLimiter(),
        storage=MemoryStorage(),
        scanner=FakeScanner(),
    )
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def make_user(seeded):
    """Create a schmelzi user with the given system roles; returns the e-mail."""
    from heinzel_api.cli import create_admin

    def _make(roles=("staff",), password=PASSWORD) -> str:
        from sqlalchemy import select

        from heinzel_api import identity, rbac
        from heinzel_api.db import make_sessionmaker, tenant_session
        from heinzel_api.manifests import load_manifests
        from heinzel_api.models import Tenant
        from heinzel_api.tenants import load_tenants

        email = f"u{uuid.uuid4().hex[:8]}@schmelzi.test"
        if "admin" in roles:
            create_admin(seeded, "schmelzi", email, "Ada Admin", password)
            return email
        factory = make_sessionmaker(OWNER_URL)
        config = load_tenants(seeded.tenants_dir)["schmelzi"]
        with factory() as s:
            tid = s.scalar(select(Tenant.id).where(Tenant.slug == "schmelzi"))
        with tenant_session(factory, tid) as s:
            all_roles = rbac.ensure_system_roles(s, tid, load_manifests(seeded.modules_dir))
            user = identity.create_user(s, tid, email, "Sam Staff", config.identity.local, password)
            for r in roles:
                rbac.assign_role(s, tid, user.id, all_roles[r].id)
        return email

    return _make
