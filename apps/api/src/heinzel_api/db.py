"""Database access.

Every request that touches tenant data runs in a transaction bound to one tenant:
`tenant_session()` sets `app.tenant_id` (transaction-local), and the row level security
policies in schema `core` only show and accept rows of that tenant. The runtime role
(`heinzel_app`) owns nothing, so it can never bypass those policies.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


@lru_cache
def get_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, future=True)


def make_sessionmaker(url: str) -> sessionmaker[Session]:
    return sessionmaker(get_engine(url), expire_on_commit=False)


def bind_tenant(session: Session, tenant_id: UUID) -> None:
    """Scope the current transaction to one tenant (is_local = true: ends with the transaction)."""
    session.execute(text("select set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})


@contextmanager
def tenant_session(factory: sessionmaker[Session], tenant_id: UUID) -> Iterator[Session]:
    """A transaction scoped to one tenant. Commits on success, rolls back on error."""
    with factory() as session, session.begin():
        bind_tenant(session, tenant_id)
        yield session


@contextmanager
def global_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    """A transaction without tenant scope. Only the tenant registry is visible."""
    with factory() as session, session.begin():
        yield session
