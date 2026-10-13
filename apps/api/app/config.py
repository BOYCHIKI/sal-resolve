"""Runtime settings from the environment. Each runtime role has its own connection string."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import UUID

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]


def _load_dotenv(path: Path = API_DIR / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    app_database_url: str        # sal_app — API requests, bound by RLS
    worker_database_url: str     # sal_worker — job claiming, bound by RLS
    migrator_database_url: str   # sal_migrator — DDL only, used by Alembic
    demo_merchant_id: UUID | None
    env: str


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
    demo = os.environ.get("SAL_DEMO_MERCHANT_ID")
    return Settings(
        app_database_url=os.environ.get(
            "SAL_APP_DATABASE_URL", "postgresql+psycopg://sal_app:app_dev_only@127.0.0.1:54329/sal"),
        worker_database_url=os.environ.get(
            "SAL_WORKER_DATABASE_URL", "postgresql+psycopg://sal_worker:worker_dev_only@127.0.0.1:54329/sal"),
        migrator_database_url=os.environ.get(
            "SAL_MIGRATOR_DATABASE_URL", "postgresql+psycopg://sal_migrator:migrator_dev_only@127.0.0.1:54329/sal"),
        demo_merchant_id=UUID(demo) if demo else None,
        env=os.environ.get("SAL_ENV", "dev"),
    )
