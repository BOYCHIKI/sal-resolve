"""Worker, job lifecycle, webhook routing and sync — against real Postgres, with a fake PayPal."""
from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app import repositories as repo
from app import worker
from app.config import get_settings
from app.db import tenant_session
from app.main import app, current_merchant, paypal_verifier
from app.seed import create_merchant

pytestmark = pytest.mark.db


def _raw(pid: str, status: str = "WAITING_FOR_SELLER_RESPONSE", updated: str = "2026-10-12T11:00:00Z",
         seller: str = "SELLER-A") -> dict:
    return {
        "dispute_id": pid, "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "status": status,
        "dispute_life_cycle_stage": "INQUIRY", "update_time": updated,
        "dispute_amount": {"currency_code": "USD", "value": "45.00"},
        "disputed_transactions": [{"custom": "SAL-INR-001", "seller": {"merchant_id": seller}}],
        "links": [{"rel": "self"}, {"rel": "provide_evidence"}],
    }


class FakePayPal:
    def __init__(self, disputes: dict[str, dict]) -> None:
        self.disputes = disputes
        self.get_calls: list[str] = []
        self.fail_next = 0

    def list_summaries(self) -> dict[str, str | None]:
        if self.fail_next:
            self.fail_next -= 1
            raise ConnectionError("paypal down")
        return {pid: d["update_time"] for pid, d in self.disputes.items()}

    def get(self, dispute_id: str) -> dict:
        self.get_calls.append(dispute_id)
        return self.disputes[dispute_id]


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Worker-{uuid4().hex[:6]}")


@pytest.fixture
def ctx(worker_engine):
    fake = FakePayPal({})
    return worker.Context(worker_engine, lambda: fake), fake


def _drain_jobs_for(ctx_, merchant_id) -> None:
    """Run due jobs until none of this merchant's jobs is runnable."""
    for _ in range(50):
        if not worker.run_one_job(ctx_):
            return


def _job(app_engine, merchant_id, job_id) -> dict:
    with tenant_session(merchant_id, app_engine) as s:
        return repo.get_job(s, job_id)


# --------------------------------------------------------------- sync optimisation
def test_sync_fetches_only_new_or_changed(merchant, ctx, app_engine):
    c, fake = ctx
    fake.disputes = {"PP-1": _raw("PP-1"), "PP-2": _raw("PP-2")}
    from app import sync
    first = sync.sync_all(merchant, fake, app_engine)
    assert first == {"listed": 2, "fetched": 2, "changed": 2}

    fake.get_calls.clear()
    assert sync.sync_all(merchant, fake, app_engine)["fetched"] == 0  # nothing changed: no detail calls

    fake.disputes["PP-2"] = _raw("PP-2", status="WAITING_FOR_BUYER_RESPONSE", updated="2026-10-12T12:00:00Z")
    third = sync.sync_all(merchant, fake, app_engine)
    assert fake.get_calls == ["PP-2"] and third["changed"] == 1


def test_timestamp_only_change_is_stored_without_version_bump(merchant, ctx, app_engine):
    _, fake = ctx
    from app import sync
    fake.disputes = {"PP-T": _raw("PP-T")}
    sync.sync_all(merchant, fake, app_engine)
    fake.disputes["PP-T"] = _raw("PP-T", updated="2026-10-12T13:00:00Z")  # e.g. a buyer message
    assert sync.sync_all(merchant, fake, app_engine)["changed"] == 0
    fake.get_calls.clear()
    assert sync.sync_all(merchant, fake, app_engine)["fetched"] == 0  # not re-fetched forever


# --------------------------------------------------------------- job lifecycle
def test_sync_job_runs_through_worker(merchant, ctx, app_engine):
    c, fake = ctx
    fake.disputes = {"PP-W": _raw("PP-W")}
    with tenant_session(merchant, app_engine) as s:
        job_id = repo.enqueue_job_returning(s, merchant, "sync_disputes", f"t:{uuid4()}")
    _drain_jobs_for(c, merchant)
    job = _job(app_engine, merchant, job_id)
    assert job["state"] == "SUCCEEDED" and job["result"]["changed"] == 1


def test_transient_failure_retries_with_backoff(merchant, ctx, app_engine, worker_engine):
    c, fake = ctx
    fake.disputes = {"PP-R": _raw("PP-R")}
    fake.fail_next = 1
    with tenant_session(merchant, app_engine) as s:
        job_id = repo.enqueue_job_returning(s, merchant, "sync_disputes", f"t:{uuid4()}")
    assert worker.run_one_job(c)
    job = _job(app_engine, merchant, job_id)
    assert job["state"] == "QUEUED" and "paypal down" in job["last_error"]
    with worker_engine.begin() as conn:  # backoff pushed it into the future
        assert conn.execute(text("SELECT run_after > now() FROM jobs WHERE id = :i"), {"i": job_id}).scalar()
        conn.execute(text("UPDATE jobs SET run_after = now() WHERE id = :i"), {"i": job_id})
    _drain_jobs_for(c, merchant)
    assert _job(app_engine, merchant, job_id)["state"] == "SUCCEEDED"


def test_permanent_failure_and_unknown_kind_fail_fast(merchant, ctx, app_engine):
    c, _ = ctx
    with tenant_session(merchant, app_engine) as s:
        bad = repo.enqueue_job_returning(s, merchant, "sync_dispute", f"t:{uuid4()}")  # no payload
        unknown = repo.enqueue_job_returning(s, merchant, "launch_rockets", f"t:{uuid4()}")
    _drain_jobs_for(c, merchant)
    for job_id in (bad, unknown):
        job = _job(app_engine, merchant, job_id)
        assert job["state"] == "FAILED" and job["attempts"] == 1


def test_exhausted_lease_becomes_failed(merchant, ctx, app_engine, worker_engine):
    c, _ = ctx
    with tenant_session(merchant, app_engine) as s:
        job_id = repo.enqueue_job_returning(s, merchant, "sync_disputes", f"t:{uuid4()}")
    with worker_engine.begin() as conn:  # simulate a worker that died on its final attempt
        conn.execute(text("""UPDATE jobs SET state='RUNNING', attempts=max_attempts,
                             lease_until = now() - interval '1 minute' WHERE id = :i"""), {"i": job_id})
    worker.run_one_job(c)
    job = _job(app_engine, merchant, job_id)
    assert job["state"] == "FAILED" and "lease expired" in job["last_error"]


# --------------------------------------------------------------- webhooks
def _connect_paypal(merchant: UUID, seller: str) -> None:
    engine = create_engine(get_settings().migrator_database_url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO paypal_connections (merchant_id, paypal_merchant_id) VALUES (:m, :p)"),
                     {"m": merchant, "p": seller})
    engine.dispose()


def _event(pid: str, seller: str, event_id: str | None = None) -> dict:
    return {"id": event_id or f"WH-{uuid4()}", "event_type": "CUSTOMER.DISPUTE.UPDATED",
            "resource": _raw(pid, seller=seller)}


@pytest.fixture
def webhook_client():
    app.dependency_overrides[paypal_verifier] = lambda: (lambda headers, event: headers.get("x-test-sig") == "ok")
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_webhook_rejects_bad_signature_and_oversize(webhook_client):
    ev = _event("PP-X", "SELLER-X")
    assert webhook_client.post("/webhooks/paypal", json=ev, headers={"x-test-sig": "no"}).status_code == 401
    big = webhook_client.post("/webhooks/paypal", content=b"{" + b" " * 300_000 + b"}",
                              headers={"x-test-sig": "ok", "content-type": "application/json"})
    assert big.status_code == 413


def test_webhook_dedupes_and_routes_to_tenant_job(webhook_client, merchant, ctx, app_engine, worker_engine):
    c, fake = ctx
    seller = f"SELLER-{uuid4().hex[:8]}"
    _connect_paypal(merchant, seller)
    fake.disputes = {"PP-H": _raw("PP-H", seller=seller)}
    ev = _event("PP-H", seller)
    first = webhook_client.post("/webhooks/paypal", json=ev, headers={"x-test-sig": "ok"}).json()
    again = webhook_client.post("/webhooks/paypal", json=ev, headers={"x-test-sig": "ok"}).json()
    assert first["duplicate"] is False and again["duplicate"] is True

    while worker.route_one_webhook(worker_engine):
        pass
    _drain_jobs_for(c, merchant)
    with tenant_session(merchant, app_engine) as s:
        row = s.execute(text("SELECT provider_status FROM disputes WHERE provider_dispute_id='PP-H'")).one()
    assert row.provider_status == "WAITING_FOR_SELLER_RESPONSE"


def test_unroutable_webhook_is_recorded_not_lost(webhook_client, worker_engine):
    ev = _event("PP-U", "SELLER-NOBODY")
    webhook_client.post("/webhooks/paypal", json=ev, headers={"x-test-sig": "ok"})
    while worker.route_one_webhook(worker_engine):
        pass
    with worker_engine.begin() as conn:
        err = conn.execute(text("SELECT error FROM webhook_events WHERE provider_event_id = :e"),
                           {"e": ev["id"]}).scalar()
    assert err and err.startswith("unroutable")


def test_api_role_cannot_read_webhook_payloads_or_connections(app_engine):
    for stmt in ("SELECT payload FROM webhook_events", "SELECT * FROM paypal_connections"):
        with app_engine.connect() as conn, pytest.raises(Exception, match="permission denied"):
            conn.execute(text(stmt))


# --------------------------------------------------------------- API
def test_sync_endpoint_queues_and_coalesces(merchant, app_engine):
    app.dependency_overrides[current_merchant] = lambda: merchant
    try:
        client = TestClient(app)
        a = client.post("/api/disputes/sync")
        b = client.post("/api/disputes/sync")
        assert a.status_code == 202 and a.json()["job_id"] == b.json()["job_id"]
        status = client.get(a.json()["status_url"]).json()
        assert status["state"] == "QUEUED" and status["kind"] == "sync_disputes"
    finally:
        app.dependency_overrides.clear()
