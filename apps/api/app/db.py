"""Tenant-scoped database sessions.

Every business query runs inside `tenant_session(merchant_id)`: one transaction whose first
statement sets `app.merchant_id` with `set_config(..., is_local => true)`. The setting dies with
the transaction, so a pooled connection never leaks a tenant into the next request, and RLS
fails closed when no tenant is set.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings


def _engine(url: str) -> Engine:
    return create_engine(
        url,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"options": "-c statement_timeout=5000 -c idle_in_transaction_session_timeout=10000"},
    )


@lru_cache
def app_engine() -> Engine:
    return _engine(get_settings().app_database_url)


@lru_cache
def worker_engine() -> Engine:
    return _engine(get_settings().worker_database_url)


def _set_tenant(session: Session, merchant_id: UUID) -> None:
    # SET LOCAL cannot take bind parameters; set_config can, so the id is never interpolated.
    session.execute(text("SELECT set_config('app.merchant_id', :mid, true)"), {"mid": str(merchant_id)})


@contextmanager
def tenant_session(merchant_id: UUID, engine: Engine | None = None) -> Iterator[Session]:
    if not isinstance(merchant_id, UUID):
        raise TypeError("merchant_id must be a UUID taken from the authenticated context")
    with Session(engine or app_engine(), expire_on_commit=False) as session, session.begin():
        _set_tenant(session, merchant_id)
        yield session


@contextmanager
def worker_session() -> Iterator[Session]:
    """Cross-tenant session for claiming jobs only. RLS still hides business rows here."""
    with Session(worker_engine(), expire_on_commit=False) as session, session.begin():
        yield session
