"""Building blocks for migrations, shared by core and module migrations.

Every tenant table must call `tenant_table_security()` in the migration that creates it.
"""

from alembic import op
from sqlalchemy import text

APP_ROLE = "heinzel_app"

_TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def ensure_app_role(password: str) -> None:
    """Create the runtime role if missing and refuse roles that could bypass RLS."""
    bind = op.get_bind()
    row = bind.execute(
        text("select rolsuper, rolbypassrls from pg_roles where rolname = :r"), {"r": APP_ROLE}
    ).first()
    if row is None:
        quoted = "'" + password.replace("'", "''") + "'"
        op.execute(f"create role {APP_ROLE} login password {quoted} nosuperuser nobypassrls")
    elif row.rolsuper or row.rolbypassrls:
        raise RuntimeError(f"role {APP_ROLE} must not be superuser or bypass RLS")
    database = bind.execute(text("select current_database()")).scalar_one()
    op.execute(f'grant connect on database "{database}" to {APP_ROLE}')


def tenant_table_security(table: str, privileges: str = "select, insert, update, delete") -> None:
    """Enable and force tenant isolation on schema.table and grant the runtime role access."""
    op.execute(f"alter table {table} enable row level security")
    op.execute(f"alter table {table} force row level security")
    op.execute(
        f"create policy tenant_isolation on {table} "
        f"using (tenant_id = {_TENANT_EXPR}) with check (tenant_id = {_TENANT_EXPR})"
    )
    op.execute(f"grant {privileges} on {table} to {APP_ROLE}")
