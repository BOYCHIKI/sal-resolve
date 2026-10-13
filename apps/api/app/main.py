"""SAL API. The merchant id always comes from the server-side identity, never from request input."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import repositories as repo
from app.config import get_settings
from app.db import app_engine, tenant_session
from app.paypal import PayPalDisputes

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


@app.post("/api/disputes/sync", status_code=202)
def sync_disputes(merchant_id: UUID = Depends(current_merchant)) -> dict:
    """Queues a sync. Repeated clicks within the same minute coalesce into one job."""
    bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    with tenant_session(merchant_id) as s:
        job_id = repo.enqueue_job_returning(s, merchant_id, "sync_disputes", f"sync_disputes:{merchant_id}:{bucket}")
    return {"job_id": str(job_id), "status_url": f"/api/jobs/{job_id}"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: UUID, merchant_id: UUID = Depends(current_merchant)) -> dict:
    with tenant_session(merchant_id) as s:
        job = repo.get_job(s, job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "JOB_NOT_FOUND", "retryable": False})
    return {"id": str(job["id"]), "kind": job["kind"], "state": job["state"], "attempts": job["attempts"],
            "max_attempts": job["max_attempts"], "error": job["last_error"], "result": job["result"]}


# ---------------------------------------------------------------- PayPal webhooks
MAX_WEBHOOK_BYTES = 256 * 1024


class WebhookVerifier(Protocol):
    def __call__(self, headers: dict[str, str], event: dict) -> bool: ...


def paypal_verifier() -> WebhookVerifier:
    webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID")
    if not webhook_id:
        raise HTTPException(503, detail={"code": "WEBHOOK_NOT_CONFIGURED", "retryable": True})
    client = PayPalDisputes()
    return lambda headers, event: client.verify_webhook(headers, event, webhook_id)


@app.post("/webhooks/paypal")
async def paypal_webhook(request: Request, verify: WebhookVerifier = Depends(paypal_verifier)) -> dict:
    """Verify, deduplicate, store. Routing to a merchant happens in the worker (tenant unknown here)."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_WEBHOOK_BYTES):
        raise HTTPException(413, detail={"code": "PAYLOAD_TOO_LARGE", "retryable": False})
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, detail={"code": "PAYLOAD_TOO_LARGE", "retryable": False})
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(400, detail={"code": "INVALID_JSON", "retryable": False}) from None
    if not isinstance(event, dict) or not event.get("id"):
        raise HTTPException(400, detail={"code": "INVALID_EVENT", "retryable": False})
    try:
        verified = await run_in_threadpool(verify, {k.lower(): v for k, v in request.headers.items()}, event)
    except Exception:  # PayPal verify API unavailable: let PayPal retry the delivery
        raise HTTPException(503, detail={"code": "VERIFICATION_UNAVAILABLE", "retryable": True}) from None
    if not verified:
        raise HTTPException(401, detail={"code": "INVALID_SIGNATURE", "retryable": False})
    with Session(app_engine()) as s, s.begin():
        stored = repo.insert_webhook_event(s, event)
    return {"received": True, "duplicate": not stored}
