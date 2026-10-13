from __future__ import annotations

import os

# Tests never call a real LLM: an empty key makes the worker use the deterministic baseline roles,
# and .env loading uses setdefault, so a key in apps/api/.env cannot override this.
os.environ["SAL_LLM_API_KEY"] = ""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings

API_DIR = Path(__file__).resolve().parents[1]


def _db_available() -> bool:
    try:
        engine = create_engine(get_settings().migrator_database_url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except OperationalError:
        return False


DB_AVAILABLE = _db_available()


def pytest_collection_modifyitems(config, items):
    if DB_AVAILABLE:
        return
    skip = pytest.mark.skip(reason="Postgres not reachable - run `docker compose up -d` from the repo root")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def migrated_db():
    """Fresh schema for the test session: downgrade to base, upgrade to head (as sal_migrator)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_DIR / "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def tenants(migrated_db) -> dict[str, UUID]:
    from app.seed import create_merchant

    a = create_merchant("Tenant A", UUID("aaaaaaaa-0000-4000-8000-000000000001"))
    b = create_merchant("Tenant B", UUID("bbbbbbbb-0000-4000-8000-000000000002"))
    return {"a": a, "b": b}


@pytest.fixture(scope="session")
def app_engine():
    engine = create_engine(get_settings().app_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def worker_engine():
    engine = create_engine(get_settings().worker_database_url)
    yield engine
    engine.dispose()
