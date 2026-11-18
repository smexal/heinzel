"""Database migrations: the core first, then every module with migrations.

The core's migrations live in apps/api/migrations (version table core.alembic_version).
A module's migrations live in modules/<id>/backend/migrations with its own version table in
the module's schema mod_<id>, so modules are versioned independently of each other. A
module's env.py is two lines:

    from heinzel_api.migrate import run_module_env
    run_module_env()
"""

from pathlib import Path

from alembic import command, context
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from heinzel_api.db import get_engine
from heinzel_api.migration_helpers import APP_ROLE

API_DIR = Path(__file__).resolve().parents[2]


def module_schema(module_id: str) -> str:
    return "mod_" + module_id.replace("-", "_")


def core_config(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["url"] = url
    return cfg


def module_config(url: str, module_id: str, migrations_dir: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("path_separator", "os")
    cfg.attributes["url"] = url
    cfg.attributes["module_id"] = module_id
    return cfg


def module_migration_dirs(modules_dir: Path) -> list[tuple[str, Path]]:
    """(module id, migrations dir) for every module that has migrations, by folder name."""
    return [
        (env.parents[2].name, env.parent)
        for env in sorted(modules_dir.glob("*/backend/migrations/env.py"))
    ]


def _configs(url: str, modules_dir: Path) -> list[tuple[str, Config, str]]:
    out = [("core", core_config(url), "core")]
    for module_id, d in module_migration_dirs(modules_dir):
        out.append((module_id, module_config(url, module_id, d), module_schema(module_id)))
    return out


def upgrade(url: str, modules_dir: Path) -> None:
    for _name, cfg, _schema in _configs(url, modules_dir):
        command.upgrade(cfg, "head")


def downgrade_all(url: str, modules_dir: Path) -> None:
    """Everything to base: modules first (they reference core tables), then the core."""
    for _name, cfg, _schema in reversed(_configs(url, modules_dir)):
        command.downgrade(cfg, "base")


def pending(url: str, modules_dir: Path) -> list[tuple[str, str | None, str | None]]:
    """(name, current, head) for every part that is behind its code."""
    behind = []
    with get_engine(url).connect() as conn:
        for name, cfg, schema in _configs(url, modules_dir):
            head = ScriptDirectory.from_config(cfg).get_current_head()
            current = MigrationContext.configure(
                conn, opts={"version_table_schema": schema}
            ).get_current_revision()
            if current != head:
                behind.append((name, current, head))
    return behind


def run_module_env() -> None:
    """env.py body for module migrations (online only)."""
    config = context.config
    module_id = config.attributes["module_id"]
    schema = module_schema(module_id)
    engine = create_engine(config.attributes["url"])
    with engine.connect() as connection:
        connection.execute(text(f"create schema if not exists {schema}"))
        connection.execute(text(f"grant usage on schema {schema} to {APP_ROLE}"))
        connection.commit()
        context.configure(connection=connection, version_table_schema=schema, include_schemas=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
