"""Spike configuration. Sandbox only: the base URL is fixed and cannot be overridden."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"

SPIKE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SPIKE_DIR.parents[1]
CONTRACTS_DIR = REPO_ROOT / "contracts" / "paypal"
STATE_FILE = SPIKE_DIR / ".spike_state.json"
DEFAULT_GOLDEN_DIR = REPO_ROOT / "data" / "golden" / "v1.0.0"


def load_dotenv(path: Path = SPIKE_DIR / ".env") -> None:
    """Minimal .env loader (KEY=VALUE per line) so the spike needs no extra dependency."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    client_id: str
    client_secret: str
    buyer_email: str | None
    webhook_id: str | None
    golden_dir: Path
    base_url: str = SANDBOX_BASE_URL

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        override = os.environ.get("PAYPAL_BASE_URL")
        if override and override.rstrip("/") != SANDBOX_BASE_URL:
            raise SystemExit(f"Refusing to run: PAYPAL_BASE_URL={override!r} is not the sandbox host.")
        missing = [k for k in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET") if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"Missing {', '.join(missing)} - copy .env.example to .env and fill it in.")
        return cls(
            client_id=os.environ["PAYPAL_CLIENT_ID"],
            client_secret=os.environ["PAYPAL_CLIENT_SECRET"],
            buyer_email=os.environ.get("PAYPAL_SANDBOX_BUYER_EMAIL") or None,
            webhook_id=os.environ.get("PAYPAL_WEBHOOK_ID") or None,
            golden_dir=Path(os.environ.get("GOLDEN_DATASET_DIR") or DEFAULT_GOLDEN_DIR),
        )
