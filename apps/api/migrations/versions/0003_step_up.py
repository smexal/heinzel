"""Step-up authentication; registry of module permissions already seeded into roles.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from heinzel_api.migration_helpers import tenant_table_security

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("session", sa.Column("step_up_at", sa.DateTime(timezone=True)), schema="core")
    # Default role permissions from manifests are applied once per tenant and permission;
    # afterwards the admin's choices stand (removing one is not undone by the next seed).
    op.create_table(
        "permission_seeded",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("core.tenant.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("permission", sa.String(120), primary_key=True),
        sa.Column(
            "seeded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="core",
    )
    # Permissions of tenants that exist already count as seeded. Row security is forced on
    # role_permission (also for the owner), so lift it for this one statement.
    op.execute("alter table core.role_permission no force row level security")
    op.execute(
        "insert into core.permission_seeded (tenant_id, permission) "
        "select distinct tenant_id, permission from core.role_permission where permission <> '*'"
    )
    op.execute("alter table core.role_permission force row level security")
    tenant_table_security("core.permission_seeded", privileges="select, insert")


def downgrade() -> None:
    op.execute("drop table if exists core.permission_seeded")
    op.drop_column("session", "step_up_at", schema="core")
