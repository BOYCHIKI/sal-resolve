"""Approval and submission: exact-revision approval, no double sends, PayPal re-check. Fake PayPal."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent.runner import baseline_roles, run_analysis
from app.db import tenant_session
from app.main import app, current_merchant, paypal_sink
from app.seed import create_merchant
from app.seed_demo import seed_golden

pytestmark = pytest.mark.db


class FakePayPal:
    def __init__(self, offers: bool = True, fail: bool = False) -> None:
        self.offers, self.fail, self.sent = offers, fail, []

    def get(self, dispute_id):
        rels = ["self", "provide_evidence"] if self.offers else ["self"]
        return {"dispute_id": dispute_id, "status": "WAITING_FOR_SELLER_RESPONSE", "links": [{"rel": r} for r in rels]}

    def provide_evidence(self, dispute_id, payload, files):
        if self.fail:
            raise RuntimeError("422 ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE")
        self.sent.append((dispute_id, payload, files))
        return {}


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Sub-{uuid4().hex[:6]}")


@pytest.fixture
def client(merchant):
    app.dependency_overrides[current_merchant] = lambda: merchant
    yield TestClient(app)
    app.dependency_overrides.clear()


def analyzed(app_engine, worker_engine, merchant, sandbox: bool = True) -> tuple[UUID, dict]:
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    if sandbox:
        with tenant_session(merchant, app_engine) as s:
            s.execute(text("UPDATE disputes SET origin = 'PAYPAL_SANDBOX' WHERE id = :d"), {"d": dispute_id})
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    return dispute_id, TestClient(app).get(f"/api/disputes/{dispute_id}/analysis").json()


def approve(client, analysis, **overrides):
    body = {"revision": analysis["draft"]["revision"], "snapshot_hash": analysis["snapshot_hash"], **overrides}
    return client.post(f"/api/drafts/{analysis['draft']['id']}/approve", json=body)


# --------------------------------------------------------------- approval
def test_approve_records_exact_revision_and_snapshot(client, merchant, app_engine, worker_engine):
    dispute_id, a = analyzed(app_engine, worker_engine, merchant)
    r = approve(client, a)
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    with tenant_session(merchant, app_engine) as s:
        row = s.execute(text("SELECT revision, snapshot_hash, actor FROM approvals")).one()
        state = s.execute(text("SELECT internal_state FROM disputes WHERE id = :d"), {"d": dispute_id}).scalar()
    assert (row.revision, row.snapshot_hash, row.actor) == (1, a["snapshot_hash"], "operator:demo")
    assert state == "APPROVED"
    assert approve(client, a).json()["detail"]["code"] == "DRAFT_NOT_PENDING"  # no double approval


def test_stale_snapshot_or_revision_is_rejected(client, merchant, app_engine, worker_engine):
    dispute_id, a = analyzed(app_engine, worker_engine, merchant)
    assert approve(client, a, snapshot_hash="0" * 64).json()["detail"]["code"] == "STALE_SNAPSHOT"
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)  # revision 2 supersedes 1
    r = approve(client, a)
    assert r.status_code == 409 and r.json()["detail"]["code"] in {"DRAFT_NOT_PENDING", "STALE_REVISION"}


def test_dispute_change_after_analysis_blocks_approval(client, merchant, app_engine, worker_engine):
    dispute_id, a = analyzed(app_engine, worker_engine, merchant)
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("UPDATE disputes SET version = version + 1 WHERE id = :d"), {"d": dispute_id})
    assert approve(client, a).json()["detail"]["code"] == "DISPUTE_CHANGED"


def test_other_tenant_cannot_approve(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant)
    app.dependency_overrides[current_merchant] = lambda: create_merchant("Intruder")
    assert approve(client, a).status_code == 404


# --------------------------------------------------------------- submission
def test_submit_sends_once_with_one_evidence_entry_and_pdfs(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant)
    fake = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: fake
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").status_code == 409  # not approved yet
    approve(client, a)
    r = client.post(f"/api/drafts/{a['draft']['id']}/submit")
    assert r.status_code == 200 and r.json()["files"] == 5
    _, payload, files = fake.sent[0]
    assert len(payload["evidences"]) == 1
    assert payload["evidences"][0]["evidence_info"]["tracking_info"][0]["tracking_number"] == "TRK-SYN-70000"
    assert all(data.startswith(b"%PDF") for _, data in files)
    again = client.post(f"/api/drafts/{a['draft']['id']}/submit")
    assert again.status_code == 409 and len(fake.sent) == 1  # never sent twice


def test_synthetic_fixture_is_never_sent(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant, sandbox=False)
    fake = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: fake
    approve(client, a)
    r = client.post(f"/api/drafts/{a['draft']['id']}/submit")
    assert r.json()["detail"]["code"] == "NOT_A_PAYPAL_DISPUTE" and fake.sent == []


def test_action_not_offered_or_paypal_error_is_recorded_and_retryable(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant)
    approve(client, a)
    app.dependency_overrides[paypal_sink] = lambda: FakePayPal(offers=False)
    r = client.post(f"/api/drafts/{a['draft']['id']}/submit")
    assert r.status_code == 502 and "no longer offers" in r.json()["detail"]["message"]
    app.dependency_overrides[paypal_sink] = lambda: FakePayPal(fail=True)
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").status_code == 502
    ok = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: ok
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").status_code == 200 and len(ok.sent) == 1
    with tenant_session(merchant, app_engine) as s:
        actions = s.execute(text("SELECT action FROM audit_logs WHERE action LIKE 'draft.%' ORDER BY id")).scalars().all()
    assert actions == ["draft.approved", "draft.submit_failed", "draft.submit_failed", "draft.submitted"]
