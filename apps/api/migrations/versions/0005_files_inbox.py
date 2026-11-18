"""Files (attachments) and the inbox (Mein Eingang).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from heinzel_api.migration_helpers import tenant_table_security

revision: str = "0005"
down_revision: str | None = "0004"
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


def _ts(name: str, default: bool = False, nullable: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default else None,
    )


def upgrade() -> None:
    op.create_table(
        "attachment",
        _id(),
        _tenant_id(),
        # Who owns it: a module and one of its objects. Null target = uploaded, not yet linked.
        sa.Column("module", sa.String(41), nullable=False),
        sa.Column("target_type", sa.String(60)),
        sa.Column("target_id", sa.String(120)),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        # pending | clean | infected | skipped (no scanner configured)
        sa.Column("scan_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.app_user.id", ondelete="SET NULL"),
        ),
        _ts("created_at", default=True, nullable=False),
        _ts("deleted_at"),
        schema=S,
    )
    op.create_index(
        "ix_attachment_target", "attachment", ["tenant_id", "target_type", "target_id"], schema=S
    )
    tenant_table_security(f"{S}.attachment")

    op.create_table(
        "inbox_item",
        _id(),
        _tenant_id(),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(41), nullable=False),  # module key or "core"
        sa.Column("kind", sa.String(10), nullable=False),  # task | notice
        sa.Column("severity", sa.String(10)),  # null | urgent
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("context", sa.String(300)),  # short line under the title
        sa.Column("body", sa.Text()),
        sa.Column("reason", sa.String(300)),  # "Warum bei dir?"
        sa.Column("facts", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("link", sa.String(500)),
        sa.Column("actions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("attachments", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("ref_type", sa.String(60)),
        sa.Column("ref_id", sa.String(120)),
        sa.Column("actor_user_id", UUID(as_uuid=True)),
        _ts("due_at"),
        _ts("created_at", default=True, nullable=False),
        _ts("updated_at", default=True, nullable=False),
        _ts("read_at"),
        _ts("done_at"),
        sa.CheckConstraint("kind in ('task', 'notice')", name="ck_inbox_item_kind"),
        schema=S,
    )
    op.create_index(
        "ix_inbox_item_user_open", "inbox_item", ["user_id", "done_at", "created_at"], schema=S
    )
    # One open item per recipient and referenced object: a module re-delivering updates it.
    op.execute(
        f"create unique index uq_inbox_item_open_ref on {S}.inbox_item "
        "(user_id, source, kind, ref_type, ref_id) "
        "where done_at is null and ref_type is not null and ref_id is not null"
    )
    tenant_table_security(f"{S}.inbox_item")


def downgrade() -> None:
    op.execute(f"drop table if exists {S}.inbox_item")
    op.execute(f"drop table if exists {S}.attachment")
