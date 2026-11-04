"""PayPal's own record of the disputed transaction, stored as evidence (ADR-005).

The worker reads the transaction through Transaction Search and keeps it as a "PayPal transaction record":
numbered text lines, origin PAYPAL_API, no file. Grounding, the rules, ASSESS and submission then treat it
like any other document, and it is the only kind of document that can prove a payment.
Personal data (payer name, e-mail, shipping address) never enters the record.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Engine, text

from app import repositories as repo
from app.db import tenant_session

SOURCE_REF = "paypal-transaction"
STATUS_WORDS = {"S": "Completed", "P": "Pending", "V": "Reversed", "D": "Denied"}


class TransactionSource(Protocol):
    def transaction(self, transaction_id: str, around: datetime) -> dict[str, Any] | None: ...


class NotFoundYet(Exception):
    """PayPal has no searchable record yet (Transaction Search lags behind payments); retry later."""


def render_record(details: dict[str, Any]) -> list[str]:
    info = details.get("transaction_info") or {}
    amount = info.get("transaction_amount") or {}
    lines = ["PayPal transaction record (retrieved from PayPal)",
             f"Transaction ID: {info.get('transaction_id', '')}",
             f"Status: {STATUS_WORDS.get(info.get('transaction_status', ''), info.get('transaction_status', ''))}",
             f"Amount: {amount.get('value', '')} {amount.get('currency_code', '')}".rstrip()]
    when = info.get("transaction_initiation_date")
    if when:
        lines.append(f"Date: {when[:10]}")
    if info.get("invoice_id"):
        lines.append(f"Invoice ID: {info['invoice_id']}")
    for item in ((details.get("cart_info") or {}).get("item_details") or [])[:5]:
        if item.get("item_name"):
            lines.append(f"Item: {item['item_name']}")
    # Where PayPal says the parcel should go: city and postal code only, enough to check the proof of delivery
    # against it. The buyer's name and street stay out of SAL.
    address = (details.get("shipping_info") or {}).get("address") or {}
    if address.get("city"):
        lines.append(f"Ship-to city: {address['city']}")
    if address.get("postal_code"):
        lines.append(f"Ship-to postal code: {address['postal_code']}")
    return lines


def fetch_and_store(merchant_id: UUID, dispute_id: UUID, source: TransactionSource,
                    engine: Engine | None = None) -> dict[str, Any]:
    with tenant_session(merchant_id, engine) as s:
        d = s.execute(text("SELECT provider_payload, origin FROM disputes WHERE id = :d"), {"d": dispute_id}).first()
        if d is None:
            return {"skipped": "dispute not found"}
        have = s.execute(text("SELECT 1 FROM evidence WHERE dispute_id = :d AND origin = 'PAYPAL_API'"),
                         {"d": dispute_id}).first()
    if d.origin != "PAYPAL_SANDBOX":
        return {"skipped": "not a PayPal dispute"}
    if have:
        return {"skipped": "already stored"}
    txn = ((d.provider_payload or {}).get("disputed_transactions") or [{}])[0]
    txn_id = txn.get("seller_transaction_id")
    if not txn_id:
        return {"skipped": "dispute has no seller transaction id"}
    created = txn.get("create_time")
    around = datetime.fromisoformat(created.replace("Z", "+00:00")) if created else datetime.now(timezone.utc)

    details = source.transaction(txn_id, around)  # network, outside any transaction
    if details is None:
        raise NotFoundYet(f"PayPal has no searchable record of {txn_id} yet")

    lines = [{"line": i, "text": t} for i, t in enumerate(render_record(details), 1)]
    body = json.dumps(lines)
    with tenant_session(merchant_id, engine) as s:
        inserted = s.execute(text("""
            INSERT INTO evidence (merchant_id, dispute_id, object_key, checksum, mime, size_bytes, uploaded_by,
                                  doc_type, content_lines, source_ref, origin)
            VALUES (:m, :d, NULL, :c, 'application/pdf', :n, 'paypal', 'payment_record', CAST(:l AS jsonb), :ref,
                    'PAYPAL_API')
            ON CONFLICT (dispute_id, checksum) DO NOTHING RETURNING id"""),
            {"m": merchant_id, "d": dispute_id, "c": hashlib.sha256(body.encode()).hexdigest(), "n": len(body),
             "l": body, "ref": SOURCE_REF}).first()
        if inserted:
            repo.enqueue_job(s, merchant_id, "analyze_dispute", f"analyze:{dispute_id}:paypal:{txn_id}", dispute_id)
            repo.write_audit(s, merchant_id, "system:paypal", "evidence.paypal_record", target=str(dispute_id),
                             summary={"transaction_id": txn_id, "lines": len(lines)})
    return {"transaction_id": txn_id, "stored": bool(inserted), "lines": len(lines)}
