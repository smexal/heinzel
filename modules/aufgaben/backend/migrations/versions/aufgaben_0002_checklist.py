"""Aufgaben: checklist points of a task.

Revision ID: aufgaben_0002
Revises: aufgaben_0001
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from heinzel_api.migration_helpers import tenant_table_security
from sqlalchemy.dialects.postgresql import UUID

revision: str = "aufgaben_0002"
down_revision: str | None = "aufgaben_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "mod_aufgaben"


def _user(name: str) -> sa.Column:
    return sa.Column(
        name, UUID(as_uuid=True), sa.ForeignKey("core.app_user.id", ondelete="SET NULL")
    )


def upgrade() -> None:
    op.create_table(
        "task_check_item",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("core.tenant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        _user("done_by"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        _user("created_by"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema=S,
    )
    op.create_index(
        "ix_check_item_task", "task_check_item", ["tenant_id", "task_id", "position"], schema=S
    )
    tenant_table_security(f"{S}.task_check_item")


def downgrade() -> None:
    op.drop_table("task_check_item", schema=S)
