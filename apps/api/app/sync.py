"""PayPal -> SAL dispute sync.

Three phases so no DB transaction ever waits on the network:
  1. short read: what we already have (provider_updated_at per dispute)
  2. network: list summaries, fetch details only for new/changed disputes, in parallel
  3. short write: upsert + audit
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Engine, text

from app import repositories as repo
from app.db import tenant_session
from app.paypal import redact, to_internal

FETCH_CONCURRENCY = 4


class DisputeSource(Protocol):
    def list_summaries(self) -> dict[str, str | None]: ...
    def get(self, dispute_id: str) -> dict[str, Any]: ...


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def sync_all(merchant_id: UUID, source: DisputeSource, engine: Engine | None = None) -> dict[str, int]:
    with tenant_session(merchant_id, engine) as s:
        known = {pid: ts for pid, ts in s.execute(text(
            "SELECT provider_dispute_id, provider_updated_at FROM disputes WHERE merchant_id = :m"),
            {"m": merchant_id}).all()}

    summaries = source.list_summaries()
    stale = [pid for pid, ts in summaries.items()
             if pid not in known or known[pid] is None or _parse(ts) is None or _parse(ts) > known[pid]]
    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        fetched = list(pool.map(source.get, stale))

    changed = 0
    with tenant_session(merchant_id, engine) as s:
        for raw in fetched:
            _, did_change = repo.upsert_provider_dispute(s, merchant_id, to_internal(raw), redact(raw))
            changed += did_change
        repo.write_audit(s, merchant_id, "system:paypal-sync", "disputes.synced",
                         summary={"listed": len(summaries), "fetched": len(fetched), "changed": changed})
    return {"listed": len(summaries), "fetched": len(fetched), "changed": changed}


def sync_one(merchant_id: UUID, source: DisputeSource, dispute_id: str,
             engine: Engine | None = None) -> dict[str, int]:
    raw = source.get(dispute_id)
    with tenant_session(merchant_id, engine) as s:
        _, changed = repo.upsert_provider_dispute(s, merchant_id, to_internal(raw), redact(raw))
        repo.write_audit(s, merchant_id, "system:paypal-sync", "dispute.synced", target=dispute_id,
                         summary={"changed": changed})
    return {"fetched": 1, "changed": int(changed)}
