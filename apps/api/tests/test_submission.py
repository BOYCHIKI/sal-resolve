"""Approval and submission: exact-revision approval, no double sends, PayPal re-check, reconciliation.
Fake PayPal, plus PayPal Sandbox responses recorded on 2026-10-12 (contracts/paypal)."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import submission
from app.agent.runner import baseline_roles, run_analysis
from app.db import tenant_session
from app.main import app, current_merchant, paypal_sink
from app.seed import create_merchant
from app.seed_demo import seed_golden

pytestmark = pytest.mark.db


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "paypal"


def recorded(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))["response"]["body"]


def http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api-m.sandbox.paypal.com/v1/customer/disputes/x/provide-evidence")
    return httpx.HTTPStatusError(f"{status}", request=request, response=httpx.Response(status, request=request))


class FakePayPal:
    def __init__(self, offers: bool = True, fail: Exception | None = None, show: dict | None = None,
                 get_fails: Exception | None = None) -> None:
        self.offers, self.fail, self.show, self.sent, self.get_fails = offers, fail, show, [], get_fails

    def get(self, dispute_id):
        if self.get_fails:
            raise self.get_fails
        if self.show is not None:
            return self.show
        rels = ["self", "provide_evidence"] if self.offers else ["self"]
        return {"dispute_id": dispute_id, "status": "WAITING_FOR_SELLER_RESPONSE", "links": [{"rel": r} for r in rels]}

    def provide_evidence(self, dispute_id, payload, files):
        self.sent.append((dispute_id, payload, files))
        if self.fail:
            raise self.fail
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
    assert all(data.startswith(b"%PDF") and mime == "application/pdf" for _, data, mime in files)
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
    app.dependency_overrides[paypal_sink] = lambda: FakePayPal(fail=http_error(422))
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").status_code == 502
    ok = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: ok
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").status_code == 200 and len(ok.sent) == 1
    with tenant_session(merchant, app_engine) as s:
        actions = s.execute(text("SELECT action FROM audit_logs WHERE action LIKE 'draft.%' ORDER BY id")).scalars().all()
    assert actions == ["draft.approved", "draft.submit_failed", "draft.submit_failed", "draft.submitted"]


def test_reanalysis_after_send_keeps_submitted_until_paypal_asks_again(merchant, app_engine, worker_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")

    def state_after_reanalysis(actions):
        with tenant_session(merchant, app_engine) as s:
            s.execute(text("""UPDATE disputes SET internal_state = 'SUBMITTED', allowed_actions = :a
                              WHERE id = :d"""), {"a": actions, "d": dispute_id})
        run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
        with tenant_session(merchant, app_engine) as s:
            return s.execute(text("SELECT internal_state FROM disputes WHERE id = :d"), {"d": dispute_id}).scalar()

    assert state_after_reanalysis(["provide_supporting_info"]) == "SUBMITTED"     # PayPal is reviewing
    assert state_after_reanalysis(["provide_evidence"]) == "NEEDS_REVIEW"         # PayPal wants more


# --------------------------------------------------------------- approval bound to documents (ADR-003 D1)
def add_document(app_engine, merchant, dispute_id, checksum="late-upload"):
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("""INSERT INTO evidence (merchant_id, dispute_id, object_key, checksum, mime, size_bytes,
                                                uploaded_by, doc_type)
                          VALUES (:m, :d, 'k', :c, 'image/png', 10, 'test', 'other')"""),
                  {"m": merchant, "d": dispute_id, "c": checksum})


def test_document_added_after_approval_is_never_sent(client, merchant, app_engine, worker_engine):
    dispute_id, a = analyzed(app_engine, worker_engine, merchant)
    approve(client, a)
    add_document(app_engine, merchant, dispute_id)  # before the re-analysis job has run
    fake = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: fake
    r = client.post(f"/api/drafts/{a['draft']['id']}/submit")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EVIDENCE_CHANGED" and fake.sent == []


def test_reanalysis_cancels_an_unsent_approval(client, merchant, app_engine, worker_engine):
    dispute_id, a = analyzed(app_engine, worker_engine, merchant)
    approve(client, a)
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    with tenant_session(merchant, app_engine) as s:
        old = s.execute(text("SELECT status FROM drafts WHERE id = :i"), {"i": a["draft"]["id"]}).scalar()
        state = s.execute(text("SELECT internal_state FROM disputes WHERE id = :d"), {"d": dispute_id}).scalar()
    assert (old, state) == ("SUPERSEDED", "NEEDS_REVIEW")
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").json()["detail"]["code"] == "NOT_SUBMITTABLE"


# --------------------------------------------------------------- unknown outcomes and reconciliation (D2)
def draft_row(app_engine, merchant, draft_id):
    with tenant_session(merchant, app_engine) as s:
        return s.execute(text("SELECT status, submit_note, submit_started_at FROM drafts WHERE id = :i"),
                         {"i": draft_id}).one()


def test_timeout_leaves_the_send_unconfirmed_and_schedules_a_check(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant)
    approve(client, a)
    app.dependency_overrides[paypal_sink] = lambda: FakePayPal(fail=httpx.ReadTimeout("timed out"))
    r = client.post(f"/api/drafts/{a['draft']['id']}/submit")
    assert r.status_code == 504 and r.json()["detail"]["code"] == "SUBMIT_UNCONFIRMED"
    row = draft_row(app_engine, merchant, a["draft"]["id"])
    assert (row.status, row.submit_note) == ("SUBMITTING", "UNCONFIRMED")
    with tenant_session(merchant, app_engine) as s:
        later = s.execute(text("""SELECT run_after > now() + interval '60 seconds' FROM jobs
                                  WHERE kind = 'reconcile_submission'""")).scalar_one()
    assert later  # not immediately: PayPal needs a moment to record the evidence
    # a second click cannot send again while the outcome is unknown
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").json()["detail"]["code"] == "NOT_SUBMITTABLE"


def test_paypal_5xx_is_unknown_not_a_failure(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant)
    approve(client, a)
    app.dependency_overrides[paypal_sink] = lambda: FakePayPal(fail=http_error(503))
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").status_code == 504
    assert draft_row(app_engine, merchant, a["draft"]["id"]).status == "SUBMITTING"


def stuck(app_engine, worker_engine, merchant, started_at: str) -> UUID:
    """An approved draft left in SUBMITTING, as if the process died during the PayPal call."""
    _, a = analyzed(app_engine, worker_engine, merchant)
    approve(TestClient(app), a)
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("UPDATE drafts SET status = 'SUBMITTING', submit_started_at = :t WHERE id = :i"),
                  {"t": started_at, "i": a["draft"]["id"]})
    return UUID(a["draft"]["id"])


@pytest.mark.parametrize("show, started, expected", [
    # Real sandbox responses: right after spike S6 sent 5 documents (11:45:32), and just before it.
    ("20261012T114646Z_s4_show_dispute.json", "2026-10-12T11:45:20Z", ("SUBMITTED", None)),
    ("20261012T114531Z_s6_show_before.json", "2026-10-12T11:45:20Z", ("SUBMIT_FAILED", "NOT_RECEIVED")),
    # Seller evidence older than this send does not count; PayPal no longer waits -> a person checks.
    ("20261012T114646Z_s4_show_dispute.json", "2026-10-12T12:30:00Z", ("SUBMIT_FAILED", "NEEDS_MANUAL_CHECK")),
])
def test_reconcile_settles_from_paypals_record(client, merchant, app_engine, worker_engine, show, started, expected):
    draft_id = stuck(app_engine, worker_engine, merchant, started)
    fake = FakePayPal(show=recorded(show))
    out = submission.reconcile(merchant, draft_id, fake, worker_engine)
    row = draft_row(app_engine, merchant, draft_id)
    assert (row.status, row.submit_note) == expected and out["settled"]
    assert fake.sent == []  # reconciliation only reads from PayPal
    with tenant_session(merchant, app_engine) as s:
        actor = s.execute(text("SELECT actor FROM audit_logs WHERE action = 'draft.submit_reconciled'")).scalar()
    assert actor == "worker"


def test_reconcile_after_a_normal_send_does_nothing(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant)
    approve(client, a)
    app.dependency_overrides[paypal_sink] = lambda: FakePayPal()
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").status_code == 200
    out = submission.reconcile(merchant, UUID(a["draft"]["id"]), FakePayPal(offers=False), worker_engine)
    assert out == {"skipped": "draft is SUBMITTED"}


def test_not_received_can_be_sent_again(client, merchant, app_engine, worker_engine):
    draft_id = stuck(app_engine, worker_engine, merchant, "2026-10-12T11:45:20Z")
    submission.reconcile(merchant, draft_id, FakePayPal(show=recorded("20261012T114531Z_s6_show_before.json")),
                         worker_engine)
    fake = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: fake
    assert client.post(f"/api/drafts/{draft_id}/submit").status_code == 200 and len(fake.sent) == 1


def test_reconcile_when_paypal_no_longer_shows_the_dispute(client, merchant, app_engine, worker_engine):
    """Review #3: a 4xx can never be fixed by retrying, so the send is settled for a person to check."""
    draft_id = stuck(app_engine, worker_engine, merchant, "2026-10-12T11:45:20Z")
    out = submission.reconcile(merchant, draft_id, FakePayPal(get_fails=http_error(404)), worker_engine)
    row = draft_row(app_engine, merchant, draft_id)
    assert (row.status, row.submit_note) == ("SUBMIT_FAILED", "NEEDS_MANUAL_CHECK") and out["settled"]
    with pytest.raises(httpx.HTTPStatusError):  # 5xx: let the job retry
        submission.reconcile(merchant, stuck(app_engine, worker_engine, merchant, "2026-10-12T11:45:20Z"),
                             FakePayPal(get_fails=http_error(503)), worker_engine)


def test_a_seller_note_without_documents_is_not_our_send():
    """Review #5: an escalation note is SUBMITTED_BY_SELLER too, but SAL always sends files."""
    from datetime import datetime, timezone
    started = datetime(2026, 10, 12, 11, 51, tzinfo=timezone.utc)
    show = {"evidences": [{"source": "SUBMITTED_BY_SELLER", "date": "2026-10-12T11:51:19.598Z", "documents": []}],
            "links": [{"rel": "self"}]}
    assert submission.decide(show, started) == (False, "NEEDS_MANUAL_CHECK")
    show["evidences"][0]["documents"] = [{"name": "proof.pdf"}]
    assert submission.decide(show, started) == (True, None)
