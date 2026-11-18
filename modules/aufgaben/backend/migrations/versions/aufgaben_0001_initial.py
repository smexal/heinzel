"""Aufgaben: lists, members, tasks.

Revision ID: aufgaben_0001
Revises:
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from heinzel_api.migration_helpers import tenant_table_security
from sqlalchemy.dialects.postgresql import UUID

revision: str = "aufgaben_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "mod_aufgaben"


def _tenant() -> sa.Column:
    return sa.Column(
        "tenant_id",
        UUID(as_uuid=True),
        sa.ForeignKey("core.tenant.id", ondelete="CASCADE"),
        nullable=False,
    )


def _user(name: str, nullable: bool = True, ondelete: str = "SET NULL") -> sa.Column:
    return sa.Column(
        name,
        UUID(as_uuid=True),
        sa.ForeignKey("core.app_user.id", ondelete=ondelete),
        nullable=nullable,
    )


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "task_list",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("name", sa.String(80)),
        _user("owner_id", nullable=False, ondelete="CASCADE"),
        _ts("created_at"),
        sa.CheckConstraint("kind in ('personal', 'shared')", name="ck_task_list_kind"),
        sa.CheckConstraint("kind = 'personal' or name is not null", name="ck_task_list_name"),
        schema=S,
    )
    op.create_index(
        "uq_task_list_personal",
        "task_list",
        ["tenant_id", "owner_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'personal'"),
        schema=S,
    )
    tenant_table_security(f"{S}.task_list")

    op.create_table(
        "task_list_member",
        sa.Column(
            "list_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.task_list.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("core.app_user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        _tenant(),
        sa.Column("role", sa.String(10), nullable=False, server_default="member"),
        _ts("added_at"),
        sa.CheckConstraint("role in ('owner', 'member')", name="ck_member_role"),
        schema=S,
    )
    op.create_index("ix_member_user", "task_list_member", ["tenant_id", "user_id"], schema=S)
    tenant_table_security(f"{S}.task_list_member")

    op.create_table(
        "task",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "list_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.task_list.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("due_date", sa.Date()),
        _user("assignee_id"),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        _user("done_by"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        _user("created_by"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("reminded_on", sa.Date()),
        sa.CheckConstraint("status in ('open', 'done')", name="ck_task_status"),
        schema=S,
    )
    op.create_index("ix_task_list", "task", ["tenant_id", "list_id", "status"], schema=S)
    op.create_index("ix_task_assignee", "task", ["tenant_id", "assignee_id", "status"], schema=S)
    op.create_index("ix_task_due", "task", ["tenant_id", "status", "due_date"], schema=S)
    tenant_table_security(f"{S}.task")


def downgrade() -> None:
    op.drop_table("task", schema=S)
    op.drop_table("task_list_member", schema=S)
    op.drop_table("task_list", schema=S)
