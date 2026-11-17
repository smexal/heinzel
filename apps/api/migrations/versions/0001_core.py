"""Core schema: tenants, users, roles, sessions, audit log. Row level security per tenant.

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

from heinzel_api.config import get_settings
from heinzel_api.migration_helpers import APP_ROLE, ensure_app_role, tenant_table_security

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "core"


def _id() -> sa.Column:
    return sa.Column(
        "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _tenant_id() -> sa.Column:
    return sa.Column(
        "tenant_id",
        UUID(as_uuid=True),
        sa.ForeignKey(f"{S}.tenant.id", ondelete="CASCADE"),
        nullable=False,
    )


def _ts(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default else None,
    )


def upgrade() -> None:
    op.execute(f"create schema if not exists {S}")
    ensure_app_role(get_settings().app_db_password)
    op.execute(f"grant usage on schema {S} to {APP_ROLE}")

    op.create_table(
        "tenant",
        _id(),
        sa.Column("slug", sa.String(41), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        _ts("created_at"),
        schema=S,
    )
    # The tenant registry is global: the runtime role may read it, only the owner writes.
    op.execute(f"grant select on {S}.tenant to {APP_ROLE}")

    op.create_table(
        "app_user",
        _id(),
        _tenant_id(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.Text()),
        sa.Column("mfa_secret", sa.Text()),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mfa_last_step", sa.BigInteger()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        _ts("locked_until", nullable=True, default=False),
        _ts("last_login_at", nullable=True, default=False),
        sa.Column("preferences", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "status in ('invited', 'active', 'deactivated')", name="ck_app_user_status"
        ),
        schema=S,
    )
    op.execute(
        f"create unique index uq_app_user_tenant_email on {S}.app_user (tenant_id, lower(email))"
    )

    op.create_table(
        "role",
        _id(),
        _tenant_id(),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        _ts("created_at"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_role_tenant_id_key"),
        schema=S,
    )

    op.create_table(
        "role_permission",
        _tenant_id(),
        sa.Column(
            "role_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.role.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("permission", sa.String(120), primary_key=True),
        schema=S,
    )

    op.create_table(
        "role_assignment",
        _tenant_id(),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.app_user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.role.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        _ts("created_at"),
        schema=S,
    )

    op.create_table(
        "session",
        _id(),
        _tenant_id(),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("mfa_passed", sa.Boolean(), nullable=False, server_default="false"),
        _ts("created_at"),
        _ts("last_seen_at"),
        _ts("expires_at", default=False),
        sa.Column("ip", INET),
        sa.Column("user_agent", sa.String(400)),
        schema=S,
    )
    op.create_index("ix_session_user_id", "session", ["user_id"], schema=S)

    op.create_table(
        "audit_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _tenant_id(),
        _ts("at", default=False),
        sa.Column("actor_user_id", UUID(as_uuid=True)),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("target_type", sa.String(60)),
        sa.Column("target_id", sa.String(120)),
        sa.Column("data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip", INET),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        schema=S,
    )
    op.create_index("ix_audit_event_tenant_id_id", "audit_event", ["tenant_id", "id"], schema=S)

    for table in ("app_user", "role", "role_permission", "role_assignment", "session"):
        tenant_table_security(f"{S}.{table}")

    # Audit log: append-only for the runtime role, and a trigger stops edits by anyone.
    tenant_table_security(f"{S}.audit_event", privileges="select, insert")
    op.execute(f"grant usage on sequence {S}.audit_event_id_seq to {APP_ROLE}")
    op.execute(
        f"""
        create function {S}.audit_event_immutable() returns trigger language plpgsql as $$
        begin
            raise exception 'audit_event is append-only';
        end $$
        """
    )
    op.execute(
        f"create trigger audit_event_no_update before update or delete on {S}.audit_event "
        f"for each row execute function {S}.audit_event_immutable()"
    )
    op.execute(
        f"create trigger audit_event_no_truncate before truncate on {S}.audit_event "
        f"for each statement execute function {S}.audit_event_immutable()"
    )


def downgrade() -> None:
    for table in (
        "audit_event",
        "session",
        "role_assignment",
        "role_permission",
        "role",
        "app_user",
        "tenant",
    ):
        op.drop_table(table, schema=S)
    op.execute(f"drop function if exists {S}.audit_event_immutable()")
