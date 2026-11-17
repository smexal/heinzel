from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from heinzel_api.config import get_settings
from heinzel_api.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    # Tests and the CLI pass the URL explicitly; otherwise use the settings.
    return config.attributes.get("url") or get_settings().migration_database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        # The version table lives in schema core, so the schema must exist first.
        connection.execute(text("create schema if not exists core"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="core",
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
