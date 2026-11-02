from __future__ import annotations

import os

# Tests never call a real LLM: baseline roles only, and no key. .env loading uses setdefault,
# so values in apps/api/.env cannot override these.
os.environ["SAL_LLM_API_KEY"] = ""
os.environ["SAL_AGENT_ROLES"] = "baseline"

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from app.config import _load_dotenv, get_settings

# Tests run against their own database ("sal_test"), never the dev/demo one: same server and roles
# as configured, only the database name changes. migrated_db refuses anything not ending in _test.
TEST_DB = "sal_test"
_load_dotenv()
_configured = get_settings()
get_settings.cache_clear()
# Read apps/api/.env once, here. Later reloads would undo what a test sets or deletes with monkeypatch.
from app import config as _config  # noqa: E402
_config._load_dotenv = lambda *args, **kwargs: None
for _key, _url in (("SAL_APP_DATABASE_URL", _configured.app_database_url),
                   ("SAL_WORKER_DATABASE_URL", _configured.worker_database_url),
                   ("SAL_MIGRATOR_DATABASE_URL", _configured.migrator_database_url)):
    os.environ[_key] = make_url(_url).set(database=TEST_DB).render_as_string(hide_password=False)

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

    database = make_url(get_settings().migrator_database_url).database or ""
    if not database.endswith("_test"):
        pytest.exit(f"Refusing to reset database {database!r}: tests only run on a *_test database", returncode=2)
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


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Each test sees the environment as it sets it (settings are cached per process otherwise)."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_failed_attempts():
    """Failed token counts live for the process; each test starts without them."""
    from app.agent_identity import failed_attempts
    failed_attempts.clear()
    yield


@pytest.fixture(autouse=True)
def _fresh_extraction_cache():
    """The LLM extraction cache lives for the process; each test starts without it."""
    from app.agent.llm import clear_extraction_cache
    clear_extraction_cache()
    yield
    clear_extraction_cache()
