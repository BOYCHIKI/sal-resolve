"""PayPal's own transaction record as evidence (ADR-005), built from responses recorded in PayPal Sandbox:
the dispute (spike S4, 2026-10-12) and Transaction Search for its transaction (spike S9, 2026-10-15)."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

from app import paypal_evidence, worker
from app import repositories as repo
from app.agent.runner import baseline_roles, run_analysis
from app.db import tenant_session
from app.paypal import redact, to_internal
from app.seed import create_merchant
from tests.fakes import paypal

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "paypal"


def recorded(pattern: str) -> dict:
    return json.loads(sorted(CONTRACTS.glob(pattern))[-1].read_text(encoding="utf-8"))["response"]["body"]


DISPUTE = recorded("*_s4_show_dispute.json")
TRANSACTION = recorded("*_s9_transaction_search.json")["transaction_details"][0]


class FakeSource:
    def __init__(self, details=TRANSACTION, fail: Exception | None = None):
        self.details, self.fail, self.calls = details, fail, []

    def transaction(self, transaction_id, around):
        self.calls.append(transaction_id)
        if self.fail:
            raise self.fail
        return self.details


# --------------------------------------------------------------- offline
def test_record_is_rendered_from_paypal_fields_without_personal_data():
    lines = paypal_evidence.render_record(TRANSACTION)
    assert lines[0].startswith("PayPal transaction record")
    assert "Transaction ID: 2MK81285P20231246" in lines and "Status: Completed" in lines
    assert "Amount: 45.00 USD" in lines and "Date: 2026-10-12" in lines
    assert any(line.startswith("Invoice ID: SAL-INR-001") for line in lines)
    joined = " ".join(lines).lower()
    assert "@" not in joined and "address" not in joined and "payer" not in joined


# --------------------------------------------------------------- with Postgres
@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"PP-{uuid4().hex[:6]}")


def paypal_dispute(app_engine, merchant) -> UUID:
    with tenant_session(merchant, app_engine) as s:
        row, _ = repo.upsert_provider_dispute(s, merchant, to_internal(DISPUTE), redact(DISPUTE))
    return row.id


def evidence_rows(app_engine, merchant, dispute_id):
    with tenant_session(merchant, app_engine) as s:
        return s.execute(text("""SELECT origin, object_key, doc_type, content_lines FROM evidence
                                 WHERE dispute_id = :d"""), {"d": dispute_id}).all()


@pytest.mark.db
def test_paypal_record_is_stored_once_and_proves_the_payment(merchant, app_engine, worker_engine):
    dispute_id = paypal_dispute(app_engine, merchant)
    source = FakeSource()
    out = paypal_evidence.fetch_and_store(merchant, dispute_id, source, worker_engine)
    assert out["stored"] and source.calls == ["2MK81285P20231246"]
    [row] = evidence_rows(app_engine, merchant, dispute_id)
    assert (row.origin, row.object_key, row.doc_type) == ("PAYPAL_API", None, "payment_record")
    assert paypal_evidence.fetch_and_store(merchant, dispute_id, source, worker_engine) == {"skipped": "already stored"}

    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    with tenant_session(merchant, app_engine) as s:
        a = s.execute(text("SELECT assessment FROM analyses WHERE dispute_id = :d"), {"d": dispute_id}).scalar_one()
    payment = next(p for p in a["propositions"] if p["id"] == "payment_matches")
    # Proven without any model: the rules read SAL's own rendering of the PayPal record exactly.
    assert payment["status"] == "proven" and "45.00" in payment["reason"]
    assert payment["sources"][0]["evidence_id"] == "paypal-transaction"
    # Nothing from the courier yet, so the case is weak until tracking or delivery proof is added.
    assert a["readiness"] == "WEAK"


@pytest.mark.db
def test_paypal_lag_retries_and_missing_permission_fails_visibly(merchant, app_engine, worker_engine):
    dispute_id = paypal_dispute(app_engine, merchant)
    with pytest.raises(paypal_evidence.NotFoundYet):
        paypal_evidence.fetch_and_store(merchant, dispute_id, FakeSource(details=None), worker_engine)

    request = httpx.Request("GET", "https://api-m.sandbox.paypal.com/v1/reporting/transactions")
    denied = httpx.HTTPStatusError("403", request=request, response=httpx.Response(403, request=request))
    with tenant_session(merchant, app_engine) as s:
        repo.enqueue_job(s, merchant, "paypal_evidence", f"pp-test:{dispute_id}", dispute_id)
    ctx = worker.Context(worker_engine, paypal(lambda: FakeSource(fail=denied)))
    while worker.run_one_job(ctx):
        pass
    with tenant_session(merchant, app_engine) as s:
        state, error = s.execute(text("""SELECT state, last_error FROM jobs WHERE idempotency_key = :k"""),
                                 {"k": f"pp-test:{dispute_id}"}).one()
    assert state == "FAILED" and "403" in error


@pytest.mark.db
def test_sync_queues_the_paypal_record_for_paypal_disputes(merchant, app_engine, worker_engine):
    from app import sync

    class Source:
        def list_summaries(self):
            return {DISPUTE["dispute_id"]: DISPUTE.get("update_time")}

        def get(self, dispute_id):
            return DISPUTE

    sync.sync_all(merchant, Source(), app_engine)
    with tenant_session(merchant, app_engine) as s:
        kinds = s.execute(text("SELECT kind FROM jobs ORDER BY kind")).scalars().all()
    assert "paypal_evidence" in kinds and "analyze_dispute" in kinds
