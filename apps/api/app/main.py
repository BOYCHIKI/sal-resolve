"""SAL API. The merchant id always comes from the server-side identity, never from request input."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query

from app import repositories as repo
from app.config import get_settings
from app.db import tenant_session
from app.paypal import PayPalDisputes, redact, to_internal

app = FastAPI(title="SAL Resolve API", version="0.1.0")


def current_merchant() -> UUID:
    """Demo identity until the auth provider is chosen (v1.1 §8): a server-configured merchant.
    Deliberately does not read headers or query parameters."""
    merchant_id = get_settings().demo_merchant_id
    if merchant_id is None:
        raise HTTPException(503, detail={"code": "AUTH_NOT_CONFIGURED", "retryable": False})
    return merchant_id


ZERO_DECIMAL_CURRENCIES = {"JPY", "HUF", "TWD"}  # PayPal: amounts in whole units


def money_str(amount: Decimal, currency: str) -> str:
    """Exact decimal string at the currency's precision (NUMERIC(19,4) comes back as 45.0000)."""
    exp = Decimal(1) if currency in ZERO_DECIMAL_CURRENCIES else Decimal("0.01")
    if amount != amount.quantize(exp):
        return format(amount.normalize(), "f")  # never round away precision silently
    return str(amount.quantize(exp))


def _serialize(row: repo.DisputeRow) -> dict:
    return {
        "id": str(row.id), "origin": row.origin, "provider_dispute_id": row.provider_dispute_id,
        "case_ref": row.case_ref, "reason": row.reason,
        "amount": {"value": money_str(row.amount, row.currency), "currency": row.currency},
        "provider_status": row.provider_status, "lifecycle_stage": row.lifecycle_stage,
        "internal_state": row.internal_state,
        "deadline_at": row.deadline_at.isoformat() if row.deadline_at else None,
        "allowed_actions": row.allowed_actions, "version": row.version,
    }


@app.get("/api/disputes")
def list_disputes(merchant_id: UUID = Depends(current_merchant), limit: int = Query(50, ge=1, le=200),
                  after_deadline: datetime | None = None, after_id: UUID | None = None) -> dict:
    after = (after_deadline, after_id) if after_id else None
    with tenant_session(merchant_id) as s:
        rows = repo.list_disputes(s, merchant_id, limit=limit, after=after)
    items = [_serialize(r) for r in rows]
    cursor = ({"after_deadline": rows[-1].deadline_at.isoformat() if rows[-1].deadline_at else None,
               "after_id": str(rows[-1].id)} if len(rows) == limit else None)
    return {"items": items, "next": cursor}


@app.get("/api/disputes/{dispute_id}")
def get_dispute(dispute_id: UUID, merchant_id: UUID = Depends(current_merchant)) -> dict:
    with tenant_session(merchant_id) as s:
        row = repo.get_dispute(s, dispute_id)
    if row is None:  # another tenant's dispute is indistinguishable from a missing one
        raise HTTPException(404, detail={"code": "DISPUTE_NOT_FOUND", "retryable": False})
    return _serialize(row)


@app.post("/api/disputes/sync")
def sync_disputes(merchant_id: UUID = Depends(current_merchant)) -> dict:
    """Pull disputes from PayPal Sandbox. Network calls happen outside the DB transaction."""
    paypal = PayPalDisputes()
    fetched = [paypal.get(pid) for pid in paypal.list_dispute_ids()]
    changed = 0
    with tenant_session(merchant_id) as s:
        for raw in fetched:
            _, did_change = repo.upsert_provider_dispute(s, merchant_id, to_internal(raw), redact(raw))
            changed += did_change
        repo.write_audit(s, merchant_id, "system:paypal-sync", "disputes.synced",
                         summary={"fetched": len(fetched), "changed": changed})
    return {"fetched": len(fetched), "changed": changed}
