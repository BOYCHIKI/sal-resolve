"""Create the demo merchant (dev only). Prints the id to put in SAL_DEMO_MERCHANT_ID."""
from __future__ import annotations

import sys
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text

from app.config import get_settings


def create_merchant(name: str, merchant_id: UUID | None = None) -> UUID:
    """Runs as sal_migrator. merchants has FORCE RLS, so even the owner must act inside the tenant."""
    merchant_id = merchant_id or uuid4()
    engine = create_engine(get_settings().migrator_database_url)
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.merchant_id', :mid, true)"), {"mid": str(merchant_id)})
        conn.execute(text("INSERT INTO merchants (id, name) VALUES (:mid, :name)"),
                     {"mid": merchant_id, "name": name})
    engine.dispose()
    return merchant_id


if __name__ == "__main__":
    print(create_merchant(sys.argv[1] if len(sys.argv) > 1 else "SAL Demo Merchant"))
