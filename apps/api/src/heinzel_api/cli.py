"""Operator commands. Run from apps/api:  uv run heinzel <command>

migrate                     apply database migrations (as the schema owner)
seed-tenants                register tenants/<slug> folders in the database, create system roles
create-admin                create a user with the admin role
verify-audit                check the audit hash chain of a tenant
"""

import argparse
import getpass
import hashlib
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from heinzel_api import audit, identity, rbac
from heinzel_api.config import Settings, get_settings
from heinzel_api.db import make_sessionmaker, tenant_session
from heinzel_api.manifests import load_manifests
from heinzel_api.models import Tenant, TenantAsset, TenantSettings
from heinzel_api.tenants import TenantConfig, load_tenants

API_DIR = Path(__file__).resolve().parents[2]


def run_migrations(url: str, revision: str = "head", down: bool = False) -> None:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["url"] = url
    if down:
        command.downgrade(cfg, revision)
    else:
        command.upgrade(cfg, revision)


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
    args = parser.parse_args(argv)

    settings = get_settings()
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
