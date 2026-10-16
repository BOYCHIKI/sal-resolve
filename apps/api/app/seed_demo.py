"""Seed demo disputes from the golden dataset and analyze them (dev only, no PayPal, no LLM).

    python -m app.seed_demo            # uses SAL_DEMO_MERCHANT_ID, or creates a merchant and prints its id

Seeds one development case per scenario (complete, missing, conflicting, edge) so the UI has
something real to show. Disputes are labelled SYNTHETIC_FIXTURE.
"""
from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from app import repositories as repo
from app.agent.evaluate import load_cases
from app.agent.runner import baseline_roles, run_analysis
from app.config import get_settings
from app.db import app_engine, tenant_session, worker_engine
from app.seed import create_merchant

DEMO_CASES = ("SAL-INR-001", "SAL-INR-011", "SAL-INR-021", "SAL-INR-033")


def seed_golden(engine: Engine, merchant: UUID, case_id: str, deadline: str | None = None) -> UUID:
    case = next(c for c in load_cases("development") if c["case_id"] == case_id)
    d = case["dispute"]
    with tenant_session(merchant, engine) as s:
        row, _ = repo.upsert_provider_dispute(s, merchant, {
            "origin": "SYNTHETIC_FIXTURE", "provider_dispute_id": f"FX-{case_id}-{uuid4().hex[:6]}",
            "custom": case_id, "reason": d["reason"], "amount": d["amount"], "provider_status": "OPEN",
            "response_deadline": deadline, "allowed_actions": ["provide_evidence", "accept_claim"]},
            {"disputed_transactions": [{"invoice_number": d["order_id"], "items": [{"item_name": d["item"]}]}]})
        for e in case["evidence"]:
            lines = json.dumps(e["content_lines"])
            s.execute(text("""INSERT INTO evidence (merchant_id, dispute_id, object_key, checksum, mime, size_bytes,
                                                    uploaded_by, doc_type, content_lines, source_ref, origin)
                              VALUES (:m, :d, :k, :c, 'application/pdf', :n, 'seed', :t, CAST(:l AS jsonb), :ref,
                                      'SEED')"""),
                      {"m": merchant, "d": row.id, "k": f"{merchant}/{row.id}/{e['evidence_id']}.pdf",
                       "c": hashlib.sha256(lines.encode()).hexdigest(), "n": len(lines), "t": e["type"],
                       "l": lines, "ref": e["evidence_id"]})
    return row.id


def main() -> None:
    merchant = get_settings().demo_merchant_id
    if merchant is None:
        merchant = create_merchant("SAL Demo Merchant")
    else:  # recreate the configured merchant if the database was reset (e.g. by pytest)
        with tenant_session(merchant, app_engine()) as s:
            exists = s.execute(text("SELECT 1 FROM merchants WHERE id = :m"), {"m": merchant}).first()
        if not exists:
            create_merchant("SAL Demo Merchant", merchant)
    for i, case_id in enumerate(DEMO_CASES):
        deadline = f"2026-11-{10 + i * 3:02d}T23:59:00Z"
        dispute_id = seed_golden(app_engine(), merchant, case_id, deadline)
        out = run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine())
        print(f"{case_id}: dispute {dispute_id}  findings={out['findings']}  claims={out['claims']}")
    if get_settings().demo_merchant_id is None:
        print(f"\nSet SAL_DEMO_MERCHANT_ID={merchant} in apps/api/.env")


if __name__ == "__main__":
    main()
