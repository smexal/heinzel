"""Global search: one index table for core and module entities.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID

from heinzel_api.migration_helpers import tenant_table_security

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "core"


def upgrade() -> None:
    # unaccent is a trusted extension: the database owner may create it. An immutable
    # wrapper (core.f_unaccent) makes it usable in index expressions and keeps queries
    # independent of the schema the extension lives in.
    op.execute("create extension if not exists unaccent")
    ext_schema = (
        op.get_bind()
        .execute(
            sa.text(
                "select n.nspname from pg_extension e "
                "join pg_namespace n on n.oid = e.extnamespace where e.extname = 'unaccent'"
            )
        )
        .scalar_one()
    )
    op.execute(
        f"""
        create function {S}.f_unaccent(text) returns text
        language sql immutable parallel safe strict
        as $$ select {ext_schema}.unaccent('{ext_schema}.unaccent'::regdictionary, $1) $$
        """
    )

    op.create_table(
        "search_document",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.tenant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # "core" or a module id, plus the provider's entity type and the entity's id
        sa.Column("module", sa.String(41), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.String(120), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        # Searchable body text. Sensitive fields never go here.
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        # Second line in the result list, link target, optional status chip
        sa.Column("meta", sa.String(300), nullable=False, server_default=""),
        sa.Column("link", sa.String(500), nullable=False),
        sa.Column("chip", JSONB()),
        # First filter: only users holding this permission see the hit (null: everyone).
        # The provider's can_view check runs afterwards on every hit.
        sa.Column("permission", sa.String(120)),
        sa.Column("tsv", TSVECTOR(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("tenant_id", "module", "entity_type", "entity_id"),
        schema=S,
    )
    op.create_index(
        "ix_search_document_tsv", "search_document", ["tsv"], postgresql_using="gin", schema=S
    )
    tenant_table_security(f"{S}.search_document")


def downgrade() -> None:
    op.drop_table("search_document", schema=S)
    op.execute(f"drop function if exists {S}.f_unaccent(text)")
