"""Runtime settings, in one place. Every environment variable SAL reads is parsed and checked here, and the
API and the worker refuse to start on a bad configuration instead of failing later inside a job.
Secrets never appear in repr() or in logs; `summary()` says only whether they are set."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from uuid import UUID

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]

ENVS = {"dev", "prod"}
AGENT_ROLES = {"baseline", "llm"}
REASONING_EFFORTS = {"minimal", "low", "medium", "high"}
MIN_INTERNAL_TOKEN = 32


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
    # databases: one role per runtime, none can bypass row-level security
    app_database_url: str = field(repr=False)        # sal_app: API requests
    worker_database_url: str = field(repr=False)     # sal_worker: job claiming
    migrator_database_url: str = field(repr=False)   # sal_migrator: DDL only (Alembic)
    demo_merchant_id: UUID | None
    env: str
    storage_dir: Path                                # private evidence files, never served directly
    # agent / OpenAI (ADR-004)
    agent_roles: str
    llm_api_key: str = field(repr=False)
    llm_model: str
    llm_base_url: str
    llm_temperature: float | None
    llm_reasoning_effort: str | None
    # PayPal (sandbox only)
    paypal_client_id: str = field(repr=False)
    paypal_client_secret: str = field(repr=False)
    paypal_webhook_id: str | None
    # web -> API: the API answers only callers that present this token (required in prod)
    internal_token: str | None = field(repr=False)
    problems: tuple[str, ...] = ()

    def summary(self) -> dict:
        """Safe to log: no secret values, only whether they are set."""
        return {"env": self.env, "agent_roles": self.agent_roles, "llm_model": self.llm_model or None,
                "llm_key_set": bool(self.llm_api_key), "paypal_set": bool(self.paypal_client_id and self.paypal_client_secret),
                "webhook_set": bool(self.paypal_webhook_id), "internal_token_set": bool(self.internal_token),
                "demo_merchant_set": self.demo_merchant_id is not None, "storage_dir": str(self.storage_dir)}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
    problems: list[str] = []

    demo_raw = _env("SAL_DEMO_MERCHANT_ID")
    try:
        demo = UUID(demo_raw) if demo_raw else None
    except ValueError:
        demo, _ = None, problems.append("SAL_DEMO_MERCHANT_ID is not a UUID")

    temp_raw = _env("SAL_LLM_TEMPERATURE")
    try:
        temperature = float(Decimal(temp_raw)) if temp_raw else None
    except InvalidOperation:
        temperature, _ = None, problems.append("SAL_LLM_TEMPERATURE must be a number, e.g. 0")

    s = Settings(
        app_database_url=_env("SAL_APP_DATABASE_URL", "postgresql+psycopg://sal_app:app_dev_only@127.0.0.1:15432/sal"),
        worker_database_url=_env("SAL_WORKER_DATABASE_URL",
                                 "postgresql+psycopg://sal_worker:worker_dev_only@127.0.0.1:15432/sal"),
        migrator_database_url=_env("SAL_MIGRATOR_DATABASE_URL",
                                   "postgresql+psycopg://sal_migrator:migrator_dev_only@127.0.0.1:15432/sal"),
        demo_merchant_id=demo,
        env=_env("SAL_ENV", "dev").lower(),
        storage_dir=Path(_env("SAL_STORAGE_DIR") or API_DIR / "storage"),
        agent_roles=_env("SAL_AGENT_ROLES", "baseline").lower(),
        llm_api_key=_env("SAL_LLM_API_KEY"),
        llm_model=_env("SAL_LLM_MODEL"),
        llm_base_url=_env("SAL_LLM_BASE_URL"),
        llm_temperature=temperature,
        llm_reasoning_effort=_env("SAL_LLM_REASONING_EFFORT").lower() or None,
        paypal_client_id=_env("PAYPAL_CLIENT_ID"),
        paypal_client_secret=_env("PAYPAL_CLIENT_SECRET"),
        paypal_webhook_id=_env("PAYPAL_WEBHOOK_ID") or None,
        internal_token=_env("SAL_INTERNAL_TOKEN") or None,
    )
    problems += _check(s)
    return Settings(**{**s.__dict__, "problems": tuple(problems)})


def _check(s: Settings) -> list[str]:
    problems = []
    if s.env not in ENVS:
        problems.append(f"SAL_ENV must be one of {sorted(ENVS)}")
    if s.agent_roles not in AGENT_ROLES:
        problems.append(f"SAL_AGENT_ROLES must be one of {sorted(AGENT_ROLES)}")
    if s.agent_roles == "llm" and not (s.llm_api_key and s.llm_model):
        problems.append("SAL_AGENT_ROLES=llm needs SAL_LLM_API_KEY and SAL_LLM_MODEL")
    if s.llm_reasoning_effort and s.llm_reasoning_effort not in REASONING_EFFORTS:
        problems.append(f"SAL_LLM_REASONING_EFFORT must be one of {sorted(REASONING_EFFORTS)}")
    if bool(s.paypal_client_id) != bool(s.paypal_client_secret):
        problems.append("Set both PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET, or neither")
    if s.internal_token is not None and len(s.internal_token) < MIN_INTERNAL_TOKEN:
        problems.append(f"SAL_INTERNAL_TOKEN must be at least {MIN_INTERNAL_TOKEN} characters")
    if s.env == "prod":
        if not s.internal_token:
            problems.append("SAL_ENV=prod requires SAL_INTERNAL_TOKEN (the API must not answer anonymous callers)")
        if "_dev_only@" in s.app_database_url or "_dev_only@" in s.worker_database_url:
            problems.append("SAL_ENV=prod must not use the dev-only database passwords")
    return problems


def require_valid(settings: Settings | None = None) -> Settings:
    """Called when the API and the worker start: fail fast with every problem listed at once."""
    s = settings or get_settings()
    if s.problems:
        raise SystemExit("SAL configuration is invalid:\n  - " + "\n  - ".join(s.problems))
    return s
