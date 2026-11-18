"""Operator commands. Run from apps/api:  uv run heinzel <command>

migrate                     apply database migrations (as the schema owner)
seed-tenants                register tenants/<slug> folders in the database, create system roles
create-admin                create a user with the admin role
verify-audit                check the audit hash chain of a tenant
reindex-search              rebuild the search index of the core (people) for all tenants
files verify                check that every stored file exists and matches its checksum
files copy --to DIR         copy all files into another directory (moving storage)
demo-inbox                  example items for a user's Mein Eingang

Every command except migrate refuses to run while migrations are pending.
"""

import argparse
import getpass
import hashlib
import sys
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select

from heinzel_api import audit, identity, rbac, search
from heinzel_api.config import Settings, get_settings
from heinzel_api.db import get_engine, make_sessionmaker, tenant_session
from heinzel_api.files import LocalStorage, Storage, make_storage
from heinzel_api.manifests import load_manifests
from heinzel_api.models import Attachment, Tenant, TenantAsset, TenantSettings
from heinzel_api.tenants import TenantConfig, load_tenants

API_DIR = Path(__file__).resolve().parents[2]


def run_migrations(url: str, revision: str = "head", down: bool = False) -> None:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["url"] = url
    if down:
        command.downgrade(cfg, revision)
    else:
        command.upgrade(cfg, revision)


def pending_migrations(url: str) -> tuple[str | None, str | None]:
    """(current, head) when the database is behind the code, else (None, None)."""
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))
    head = script.get_current_head()
    with get_engine(url).connect() as conn:
        current = MigrationContext.configure(
            conn, opts={"version_table_schema": "core"}
        ).get_current_revision()
    return (current, head) if current != head else (None, None)


def tenant_ids(settings: Settings) -> list[tuple[str, uuid.UUID]]:
    factory = make_sessionmaker(settings.migration_database_url)
    with factory() as s:
        return [
            (r.slug, r.id) for r in s.execute(select(Tenant.slug, Tenant.id).order_by(Tenant.slug))
        ]


def verify_files(settings: Settings, storage: Storage) -> dict:
    """Every live attachment must exist in storage with its recorded checksum. Files in
    storage that no attachment references are reported as orphans (not deleted)."""
    factory = make_sessionmaker(settings.migration_database_url)
    report: dict = {"ok": 0, "missing": [], "corrupt": [], "orphans": []}
    known: set[str] = set()
    for _slug, tid in tenant_ids(settings):
        with tenant_session(factory, tid) as s:
            rows = s.execute(
                select(
                    Attachment.id, Attachment.storage_key, Attachment.sha256, Attachment.deleted_at
                )
            ).all()
        for att_id, key, sha, deleted in rows:
            known.add(key)
            if deleted is not None:
                continue
            if not storage.exists(key):
                report["missing"].append(str(att_id))
            elif hashlib.sha256(storage.get(key)).hexdigest() != sha:
                report["corrupt"].append(str(att_id))
            else:
                report["ok"] += 1
    report["orphans"] = [k for k in storage.iter_keys() if k not in known]
    return report


def copy_files(settings: Settings, source: Storage, target: Storage) -> dict:
    """Copy every live file to another storage, verifying checksums. Idempotent: files that
    are already there with the right checksum are skipped, so an interrupted run can resume."""
    factory = make_sessionmaker(settings.migration_database_url)
    counts = {"copied": 0, "skipped": 0, "failed": []}
    for _slug, tid in tenant_ids(settings):
        with tenant_session(factory, tid) as s:
            rows = s.execute(
                select(Attachment.id, Attachment.storage_key, Attachment.sha256).where(
                    Attachment.deleted_at.is_(None)
                )
            ).all()
        for att_id, key, sha in rows:
            if target.exists(key) and hashlib.sha256(target.get(key)).hexdigest() == sha:
                counts["skipped"] += 1
                continue
            data = source.get(key) if source.exists(key) else None
            if data is None or hashlib.sha256(data).hexdigest() != sha:
                counts["failed"].append(str(att_id))
                continue
            target.put(key, data)
            counts["copied"] += 1
    return counts


ASSET_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp"}


def _seed_config(config: TenantConfig) -> dict:
    """tenant.json without the operator-owned fields (slug, domains)."""
    return config.model_dump(mode="json", exclude={"slug", "domains"})


def seed_tenants(settings: Settings, reset_config: bool = False) -> list[str]:
    """Register tenants/<slug> folders: tenant row (slug, name, domains), settings and assets
    for new tenants, system roles. Existing settings stay untouched unless reset_config:
    after the first seed the portal's Einstellungen are the source of truth."""
    tenants = load_tenants(settings.tenants_dir)
    manifests = load_manifests(settings.modules_dir)
    factory = make_sessionmaker(settings.migration_database_url)
    done = []
    for config in tenants.values():
        with factory() as s, s.begin():
            row = s.scalar(select(Tenant).where(Tenant.slug == config.slug))
            created = row is None
            if row is None:
                row = Tenant(slug=config.slug, display_name=config.display_name)
                s.add(row)
            row.domains = [d.lower() for d in config.domains]
            s.flush()
            tenant_id = row.id
        with tenant_session(factory, tenant_id) as s:
            current = s.get(TenantSettings, tenant_id)
            if current is None:
                s.add(TenantSettings(tenant_id=tenant_id, config=_seed_config(config)))
            elif reset_config:
                current.config = _seed_config(config)
                current.version += 1
            assets_dir = settings.tenants_dir / config.slug / "assets"
            for path in sorted(assets_dir.glob("*")) if assets_dir.is_dir() else []:
                ctype = ASSET_TYPES.get(path.suffix.lower())
                if ctype is None:
                    continue
                existing = s.get(TenantAsset, {"tenant_id": tenant_id, "name": path.name})
                if existing is not None and not reset_config:
                    continue
                data = path.read_bytes()
                if existing is None:
                    existing = TenantAsset(tenant_id=tenant_id, name=path.name)
                    s.add(existing)
                existing.content_type = ctype
                existing.data = data
                existing.sha256 = hashlib.sha256(data).hexdigest()
            rbac.ensure_system_roles(s, tenant_id, manifests)
            search.reindex_core(s, tenant_id)
            if created:
                audit.record(s, tenant_id, "tenant.registered", channel="cli")
            elif reset_config and current is not None:
                audit.record(s, tenant_id, "settings.reset_from_seed", channel="cli")
        done.append(config.slug)
    return done


def create_admin(
    settings: Settings, slug: str, email: str, display_name: str, password: str
) -> None:
    manifests = load_manifests(settings.modules_dir)
    factory = make_sessionmaker(settings.migration_database_url)
    with factory() as s:
        row = s.execute(select(Tenant.id, Tenant.domains).where(Tenant.slug == slug)).first()
    if row is None:
        raise SystemExit(f"Mandant '{slug}' ist nicht registriert. Zuerst: heinzel seed-tenants")
    tenant_id = row.id
    with tenant_session(factory, tenant_id) as s:
        stored = s.get(TenantSettings, tenant_id)
        if stored is None:
            raise SystemExit(
                f"Mandant '{slug}' hat keine Einstellungen. Zuerst: heinzel seed-tenants"
            )
        config = TenantConfig.model_validate(
            {**stored.config, "slug": slug, "domains": list(row.domains)}
        )
    policy = config.identity.local
    with tenant_session(factory, tenant_id) as s:
        if identity.find_user(s, email):
            raise SystemExit(f"Benutzer {email} existiert bereits")
        roles = rbac.ensure_system_roles(s, tenant_id, manifests)
        user = identity.create_user(s, tenant_id, email, display_name, policy, password)
        rbac.assign_role(s, tenant_id, user.id, roles["admin"].id)
        rbac.assign_role(s, tenant_id, user.id, roles["staff"].id)
        audit.record(
            s,
            tenant_id,
            "user.created",
            channel="cli",
            target_type="user",
            target_id=str(user.id),
            data={"email": user.email, "roles": ["admin", "staff"]},
        )


def demo_inbox(settings: Settings, slug: str, email: str) -> int:
    """Example items in a user's Mein Eingang, to try the page before modules deliver any."""
    from datetime import UTC, datetime, timedelta

    from heinzel_api import inbox

    factory = make_sessionmaker(settings.migration_database_url)
    with factory() as s:
        tenant_id = s.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if tenant_id is None:
        raise SystemExit(f"Unbekannter Mandant '{slug}'")
    with tenant_session(factory, tenant_id) as s:
        user = identity.find_user(s, email)
        if user is None:
            raise SystemExit(f"Unbekannter Benutzer {email}")
        now = datetime.now(UTC)
        items = [
            dict(
                source="aufgaben",
                kind="task",
                title="Zugewiesen: Protokoll GL-Sitzung verschicken",
                context="Sekretariat · fällig heute",
                body="Bitte das Protokoll der GL-Sitzung vom Montag an alle Teilnehmenden senden.",
                reason="Die Aufgabe wurde dir zugewiesen.",
                facts=[("Liste", "Sekretariat"), ("Fällig", "heute")],
                link="/aufgaben",
                due_at=now + timedelta(hours=6),
                ref_type="demo",
                ref_id="task-1",
            ),
            dict(
                source="core",
                kind="task",
                title="Einladung von Nina Frei noch offen",
                context="seit 3 Tagen",
                body="Nina Frei hat die Einladung noch nicht angenommen.",
                reason="Du hast die Einladung verschickt.",
                link="/admin/benutzer",
                ref_type="demo",
                ref_id="task-2",
            ),
            dict(
                source="core",
                kind="notice",
                title="Deine Rollen wurden geändert",
                context="Neu: Mitarbeitende",
                ref_type="demo",
                ref_id="notice-1",
            ),
        ]
        for item in items:
            inbox.deliver(s, tenant_id, [user.id], **item)
    return len(items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heinzel")
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate", help="apply database migrations")
    m.add_argument("revision", nargs="?", default="head")
    sd = sub.add_parser("seed-tenants", help="register tenants and create system roles")
    sd.add_argument(
        "--reset-config",
        action="store_true",
        help="overwrite settings and assets with tenants/<slug> (discards portal changes)",
    )
    a = sub.add_parser("create-admin", help="create an administrator")
    a.add_argument("--tenant", required=True)
    a.add_argument("--email", required=True)
    a.add_argument("--name", required=True)
    v = sub.add_parser("verify-audit", help="verify the audit hash chain")
    v.add_argument("--tenant", required=True)
    di = sub.add_parser("demo-inbox", help="put example items into a user's Mein Eingang")
    di.add_argument("--tenant", required=True)
    di.add_argument("--email", required=True)
    sub.add_parser("reindex-search", help="rebuild the core's search index (people)")
    fl = sub.add_parser("files", help="check or move stored files")
    fsub = fl.add_subparsers(dest="files_cmd", required=True)
    fsub.add_parser("verify", help="every file present and matching its checksum")
    fc = fsub.add_parser("copy", help="copy all files into another directory")
    fc.add_argument("--to", required=True, type=Path, help="target directory")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.cmd != "migrate":
        current, head = pending_migrations(settings.migration_database_url)
        if head is not None:
            print(
                f"Die Datenbank ist nicht aktuell (Stand {current or 'leer'}, benötigt {head}).\n"
                "Zuerst ausführen: uv run heinzel migrate",
                file=sys.stderr,
            )
            return 3
    if args.cmd == "migrate":
        run_migrations(settings.migration_database_url, args.revision)
    elif args.cmd == "seed-tenants":
        for slug in seed_tenants(settings, reset_config=args.reset_config):
            print(f"✓ {slug}")
    elif args.cmd == "create-admin":
        password = getpass.getpass("Passwort: ")
        if password != getpass.getpass("Passwort wiederholen: "):
            print("Passwörter stimmen nicht überein", file=sys.stderr)
            return 1
        try:
            create_admin(settings, args.tenant, args.email, args.name, password)
        except identity.PasswordPolicyError as e:
            print(e, file=sys.stderr)
            return 1
        print(f"✓ {args.email} angelegt. Die Zwei-Faktor-Einrichtung folgt beim ersten Login.")
    elif args.cmd == "demo-inbox":
        n = demo_inbox(settings, args.tenant, args.email)
        print(f"✓ {n} Beispiel-Einträge für {args.email}")
    elif args.cmd == "reindex-search":
        factory = make_sessionmaker(settings.migration_database_url)
        for slug, tid in tenant_ids(settings):
            with tenant_session(factory, tid) as s:
                n = search.reindex_core(s, tid)
            print(f"✓ {slug}: {n} Personen")
    elif args.cmd == "files" and args.files_cmd == "verify":
        r = verify_files(settings, make_storage(settings))
        print(f"✓ {r['ok']} Dateien in Ordnung")
        problems = (("fehlen", "missing"), ("beschädigt", "corrupt"), ("verwaist", "orphans"))
        for label, key in problems:
            if r[key]:
                print(f"✗ {len(r[key])} {label}: " + ", ".join(r[key][:20]))
        return 2 if r["missing"] or r["corrupt"] else 0
    elif args.cmd == "files" and args.files_cmd == "copy":
        target = args.to.resolve()
        if target == settings.files_dir.resolve():
            print("Ziel ist der aktuelle Speicherort", file=sys.stderr)
            return 1
        c = copy_files(settings, make_storage(settings), LocalStorage(target))
        print(f"✓ {c['copied']} kopiert, {c['skipped']} schon vorhanden")
        if c["failed"]:
            failed = ", ".join(c["failed"][:20])
            print(f"✗ {len(c['failed'])} nicht lesbar oder beschädigt: {failed}")
            return 2
        print(f"Danach HEINZEL_FILES_DIR={target} setzen und die API neu starten.")
    elif args.cmd == "verify-audit":
        factory = make_sessionmaker(settings.migration_database_url)
        with factory() as s:
            tenant_id = s.scalar(select(Tenant.id).where(Tenant.slug == args.tenant))
        if tenant_id is None:
            print(f"Unbekannter Mandant '{args.tenant}'", file=sys.stderr)
            return 1
        with tenant_session(factory, tenant_id) as s:
            result = audit.verify_chain(s, tenant_id)
        if result.ok:
            print(f"✓ {result.events} Ereignisse, Kette intakt")
        else:
            print(f"✗ Kette gebrochen bei Ereignis {result.broken_at}: {result.reason}")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
