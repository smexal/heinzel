"""Export and import: everything moves to a fresh installation and still works there."""

import tarfile
import uuid

import pytest
from _flows import enrol
from _support import OWNER_URL
from sqlalchemy import create_engine, make_url, select, text

from heinzel_api import audit, crypto, files, transfer
from heinzel_api.cli import run_migrations
from heinzel_api.db import make_sessionmaker, tenant_session
from heinzel_api.identity import MFA_PURPOSE
from heinzel_api.models import Tenant, User

pytestmark = pytest.mark.usefixtures("seeded")

JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 300
TARGET_KEY = "another-secret-key-for-the-cloud-server"


@pytest.fixture
def target_url():
    """An empty second database, migrated like the source."""
    url = make_url(OWNER_URL)
    name = f"{url.database}_import_{uuid.uuid4().hex[:6]}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'create database "{name}"'))
    target = url.set(database=name).render_as_string(hide_password=False)
    run_migrations(target, "head")
    yield target
    with admin.connect() as c:
        c.execute(text(f'drop database "{name}" with (force)'))
    admin.dispose()


def _rows(url: str, sql: str, tenant_id=None):
    engine = create_engine(url)
    with engine.connect() as c:
        if tenant_id:
            c.execute(text("select set_config('app.tenant_id', :t, false)"), {"t": str(tenant_id)})
        out = c.execute(text(sql)).all()
    engine.dispose()
    return out


def test_round_trip(api, make_user, settings, target_url, tmp_path):
    email = make_user()
    enrol(api, email)
    task = api.post("/api/v1/aufgaben/tasks", json={"title": "Umzug", "checklist": ["A"]}).json()
    up = api.post(
        "/api/v1/files?module=aufgaben",
        content=JPEG,
        headers={"x-filename": "a.jpg", "content-type": "application/octet-stream"},
    ).json()
    api.post(
        f"/api/v1/aufgaben/tasks/{task['id']}/attachments", json={"attachment_ids": [up["id"]]}
    )
    source = api.app.state.storage

    manifest = transfer.export(
        OWNER_URL, settings.secret_key, source, settings.modules_dir, tmp_path
    )
    path = manifest["path"]
    names = {t["name"] for t in manifest["tables"]}
    assert "core.app_user" in names and "mod_aufgaben.task_check_item" in names
    assert "core.session" not in names
    assert manifest["migrations"]["core"] and manifest["migrations"]["aufgaben"]
    with tarfile.open(path) as tar:
        assert "manifest.json" in tar.getnames()

    target_store = files.MemoryStorage()
    # a different key needs the source key
    with pytest.raises(transfer.TransferError, match="source-key"):
        transfer.import_(path, target_url, TARGET_KEY, target_store, settings.modules_dir)
    with pytest.raises(transfer.TransferError, match="nicht der Schlüssel"):
        transfer.import_(
            path, target_url, TARGET_KEY, target_store, settings.modules_dir, source_key="wrong"
        )
    r = transfer.import_(
        path,
        target_url,
        TARGET_KEY,
        target_store,
        settings.modules_dir,
        source_key=settings.secret_key,
    )
    assert r["rekeyed"] and r["files"] == len(manifest["files"]) >= 1

    # the same rows, the files, a valid audit chain and a readable TOTP seed
    tenant_id = _rows(target_url, "select id from core.tenant where slug = 'schmelzi'")[0][0]
    for table in ("core.app_user", "core.audit_event", "mod_aufgaben.task"):
        src = _rows(OWNER_URL, f"select count(*) from {table}", tenant_id)[0][0]
        assert _rows(target_url, f"select count(*) from {table}", tenant_id)[0][0] == src
    assert target_store.get(next(iter(target_store.blobs))) == JPEG
    factory = make_sessionmaker(target_url)
    with tenant_session(factory, tenant_id) as s:
        assert audit.verify_chain(s, tenant_id).ok
        user = s.scalar(select(User).where(User.email == email))
        assert crypto.decrypt(TARGET_KEY, MFA_PURPOSE, user.mfa_secret)
        # new audit events continue the sequence
        audit.record(s, tenant_id, "test.after_import", channel="cli")
    with tenant_session(factory, tenant_id) as s:
        assert audit.verify_chain(s, tenant_id).ok
        assert s.scalar(select(Tenant.slug).where(Tenant.id == tenant_id)) == "schmelzi"

    # a second import refuses to overwrite users unless asked to
    with pytest.raises(transfer.TransferError, match="--replace"):
        transfer.import_(
            path, target_url, settings.secret_key, files.MemoryStorage(), settings.modules_dir
        )
    transfer.import_(
        path,
        target_url,
        settings.secret_key,
        files.MemoryStorage(),
        settings.modules_dir,
        replace=True,
    )


def test_damaged_or_foreign_archives_are_refused(api, settings, target_url, tmp_path):
    m = transfer.export(
        OWNER_URL, settings.secret_key, api.app.state.storage, settings.modules_dir, tmp_path
    )
    broken = tmp_path / "broken.tar.gz"
    with tarfile.open(m["path"]) as src, tarfile.open(broken, "w:gz") as dst:
        for member in src.getmembers():
            data = src.extractfile(member).read()
            if member.name == "db/core.app_user":
                data = data.replace(b"\t", b"\t ", 1)
            member.size = len(data)
            import io

            dst.addfile(member, io.BytesIO(data))
    with pytest.raises(transfer.TransferError, match="beschädigt"):
        transfer.import_(
            broken, target_url, settings.secret_key, files.MemoryStorage(), settings.modules_dir
        )
    other = tmp_path / "other.tar.gz"
    with tarfile.open(other, "w:gz"):
        pass
    with pytest.raises(transfer.TransferError, match="manifest.json"):
        transfer.import_(
            other, target_url, settings.secret_key, files.MemoryStorage(), settings.modules_dir
        )
