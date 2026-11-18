"""Tenant configuration in the database: domains on core.tenant, settings and assets per tenant.

tenants/<slug>/tenant.json and its assets become the seed for a new tenant
(`heinzel seed-tenants`); afterwards administrators change the settings in the portal.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB, UUID

from heinzel_api.migration_helpers import tenant_table_security

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "core"


def _tenant_pk() -> sa.Column:
    return sa.Column(
        "tenant_id",
        UUID(as_uuid=True),
        sa.ForeignKey(f"{S}.tenant.id", ondelete="CASCADE"),
        primary_key=True,
    )


def upgrade() -> None:
    # Domains are run by the platform operator, not the tenant admin: they stay on the
    # global registry (readable for host resolution, not writable by the runtime role).
    op.add_column(
        "tenant",
        sa.Column("domains", ARRAY(sa.String(253)), nullable=False, server_default="{}"),
        schema=S,
    )

    op.create_table(
        "tenant_settings",
        _tenant_pk(),
        sa.Column("config", JSONB, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_by", UUID(as_uuid=True)),
        schema=S,
    )
    tenant_table_security(f"{S}.tenant_settings", privileges="select, insert, update")

    op.create_table(
        "tenant_asset",
        _tenant_pk(),
        sa.Column("name", sa.String(100), primary_key=True),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("data", BYTEA, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema=S,
    )
    tenant_table_security(f"{S}.tenant_asset")


def downgrade() -> None:
    op.execute(f"drop table if exists {S}.tenant_asset")
    op.execute(f"drop table if exists {S}.tenant_settings")
    op.drop_column("tenant", "domains", schema=S)
