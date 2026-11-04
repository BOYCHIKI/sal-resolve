"""Approval and submission: exact-revision approval, no double sends, PayPal re-check, reconciliation.
Fake PayPal, plus PayPal Sandbox responses recorded on 2026-10-12 (contracts/paypal)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
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

    def make_offer(self, dispute_id, payload):
        self.sent.append((dispute_id, payload))
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


def test_reply_without_sentences_cannot_be_approved(client, merchant, app_engine, worker_engine):
    dispute_id, a = analyzed(app_engine, worker_engine, merchant)
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("UPDATE drafts SET claims = '[]'::jsonb WHERE dispute_id = :d"), {"d": dispute_id})
    r = approve(client, a)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOTHING_TO_SEND"
    with tenant_session(merchant, app_engine) as s:
        assert s.execute(text("SELECT count(*) FROM approvals")).scalar() == 0


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


def test_two_simultaneous_sends_reach_paypal_once(merchant, app_engine, worker_engine):
    """A double click, or two tabs pressing Send together: the atomic claim lets exactly one through."""
    import threading
    import time

    app.dependency_overrides[current_merchant] = lambda: merchant
    client = TestClient(app)
    _, a = analyzed(app_engine, worker_engine, merchant)
    approve(client, a)

    class SlowPayPal(FakePayPal):  # holds the first send open so the second one arrives mid-flight
        def provide_evidence(self, dispute_id, payload, files):
            time.sleep(0.5)
            return super().provide_evidence(dispute_id, payload, files)

    fake = SlowPayPal()
    gate = threading.Barrier(2)

    def send(results):
        gate.wait()
        results.append(submission.submit(merchant, UUID(a["draft"]["id"]), "operator:test", fake, app_engine))

    outcomes, errors = [], []

    def run():
        try:
            send(outcomes)
        except submission.SubmissionError as exc:
            errors.append(exc.code)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    app.dependency_overrides.clear()
    assert len(fake.sent) == 1, "evidence must reach PayPal exactly once"
    assert len(outcomes) == 1 and errors == ["NOT_SUBMITTABLE"]
    with tenant_session(merchant, app_engine) as s:
        sends = s.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'draft.submitted'")).scalar()
    assert sends == 1


def test_a_newer_draft_waits_while_another_send_of_the_case_is_open(client, merchant, app_engine, worker_engine):
    dispute_id, first = analyzed(app_engine, worker_engine, merchant)
    approve(client, first)
    fake = FakePayPal(fail=httpx.ReadTimeout("slow"))
    app.dependency_overrides[paypal_sink] = lambda: fake
    assert client.post(f"/api/drafts/{first['draft']['id']}/submit").status_code == 504   # may have reached PayPal
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)             # the case moves on
    second = client.get(f"/api/disputes/{dispute_id}/analysis").json()
    assert second["draft"]["id"] != first["draft"]["id"]
    approve(client, second)
    r = client.post(f"/api/drafts/{second['draft']['id']}/submit")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SEND_IN_PROGRESS"
    assert len(fake.sent) == 1


def test_a_changed_case_blocks_a_send_until_it_is_analysed_again(client, merchant, app_engine, worker_engine):
    dispute_id, a = analyzed(app_engine, worker_engine, merchant)
    approve(client, a)
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("UPDATE disputes SET version = version + 1 WHERE id = :d"), {"d": dispute_id})
    fake = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: fake
    r = client.post(f"/api/drafts/{a['draft']['id']}/submit")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DRAFT_OUT_OF_DATE" and fake.sent == []


def test_an_older_revision_is_never_sent(client, merchant, app_engine, worker_engine):
    dispute_id, first = analyzed(app_engine, worker_engine, merchant)
    approve(client, first)
    with tenant_session(merchant, app_engine) as s:   # a failed send that an analysis running during it left behind
        s.execute(text("""INSERT INTO drafts (merchant_id, dispute_id, revision, body, payload_hash, analysis_id, claims)
                          SELECT merchant_id, dispute_id, revision + 1, body, payload_hash, analysis_id, claims
                          FROM drafts WHERE id = :i"""), {"i": first["draft"]["id"]})
    fake = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: fake
    r = client.post(f"/api/drafts/{first['draft']['id']}/submit")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DRAFT_OUT_OF_DATE" and fake.sent == []


def _claimed(client, merchant, app_engine, worker_engine, note=None) -> UUID:
    """A send that has started and not come back yet (no outcome recorded)."""
    _, a = analyzed(app_engine, worker_engine, merchant)
    approve(client, a)
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("UPDATE drafts SET status = 'SUBMITTING', submit_started_at = now(), submit_note = :n WHERE id = :i"),
                  {"n": note, "i": a["draft"]["id"]})
    return UUID(a["draft"]["id"])


def test_reconcile_waits_for_a_send_still_in_flight(client, merchant, app_engine, worker_engine):
    draft_id = _claimed(client, merchant, app_engine, worker_engine)
    out = submission.reconcile(merchant, draft_id, FakePayPal(), worker_engine)
    assert out == {"draft_id": str(draft_id), "waiting": "send may still be running"}
    assert draft_row(app_engine, merchant, draft_id).status == "SUBMITTING"
    with tenant_session(merchant, app_engine) as s:
        queued = s.execute(text("SELECT count(*) FROM jobs WHERE kind = 'reconcile_submission' AND merchant_id = :m"),
                           {"m": merchant}).scalar()
    assert queued == 1


def test_reconcile_settles_a_send_that_already_came_back_unconfirmed(client, merchant, app_engine, worker_engine):
    draft_id = _claimed(client, merchant, app_engine, worker_engine, note="UNCONFIRMED")
    assert submission.reconcile(merchant, draft_id, FakePayPal(), worker_engine)["note"] == "NOT_RECEIVED"
    assert draft_row(app_engine, merchant, draft_id).status == "SUBMIT_FAILED"


def test_an_older_attempts_check_does_not_touch_a_newer_send(client, merchant, app_engine, worker_engine):
    draft_id = stuck(app_engine, worker_engine, merchant, "2026-10-12T11:45:20Z")
    out = submission.reconcile(merchant, draft_id, FakePayPal(), worker_engine, started_at="2026-10-12T10:00:00+00:00")
    assert out == {"skipped": "an older attempt"}
    assert draft_row(app_engine, merchant, draft_id).status == "SUBMITTING"


def test_paypals_yes_outranks_an_earlier_failed_verdict(client, merchant, app_engine, worker_engine):
    draft_id = _claimed(client, merchant, app_engine, worker_engine, note="UNCONFIRMED")
    started = draft_row(app_engine, merchant, draft_id).submit_started_at
    submission.reconcile(merchant, draft_id, FakePayPal(), worker_engine)
    with tenant_session(merchant, worker_engine) as s:
        dispute_id = s.execute(text("SELECT dispute_id FROM drafts WHERE id = :i"), {"i": draft_id}).scalar()
        assert submission._settle(s, merchant, draft_id, dispute_id, "PP-X", "test", started, sent=True, note=None,
                                  action="draft.submitted", summary={})
    assert draft_row(app_engine, merchant, draft_id).status == "SUBMITTED"


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
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").json()["detail"]["code"] == "DRAFT_OUT_OF_DATE"


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


@pytest.mark.parametrize("requested, sent", [
    ([], "PROOF_OF_FULFILLMENT"),
    (["PROOF_OF_REFUND", "PROOF_OF_FULFILLMENT", "PROOF_OF_DELIVERY_SIGNATURE"], "PROOF_OF_FULFILLMENT"),
    (["PROOF_OF_DELIVERY_SIGNATURE", "PROOF_OF_FULFILLMENT"], "PROOF_OF_FULFILLMENT"),
    (["PROOF_OF_DELIVERY_SIGNATURE"], "PROOF_OF_DELIVERY_SIGNATURE"),
    (["PROOF_OF_REFUND"], "PROOF_OF_FULFILLMENT"),      # courier documents never go out labelled as a refund
])
def test_one_entry_of_a_type_the_documents_back(requested, sent):
    payload = submission._payload([{"text": "Delivered."}], [], requested)
    assert [e["evidence_type"] for e in payload["evidences"]] == [sent]

def test_paypals_own_reason_for_refusing_a_send_is_kept():
    refused = httpx.Response(400, request=httpx.Request("POST", "https://x"), json={
        "name": "VALIDATION_ERROR", "message": "Invalid request",
        "details": [{"issue": "MISSING_REQUIRED_PARAMETER", "field": "x"}], "payer": {"email_address": "a@b.co"}})
    error, unknown = submission._send(FakePayPal(fail=httpx.HTTPStatusError("400", request=refused.request,
                                                                            response=refused)), "PP-1", {}, [])
    assert "VALIDATION_ERROR" in error and "MISSING_REQUIRED_PARAMETER" in error and not unknown
    assert "a@b.co" not in error

class RefusesTheFirstType(FakePayPal):
    """PayPal refusing an evidence type it may even have asked for (sandbox, 2026-10-30)."""

    def __init__(self, issue="EVIDENCE_TYPE_IS_NOT_ALLOWED", status=400):
        super().__init__()
        self.issue, self.status = issue, status

    def provide_evidence(self, dispute_id, payload, files):
        self.sent.append((dispute_id, payload, files))
        if len(self.sent) == 1:
            response = httpx.Response(self.status, request=httpx.Request("POST", "https://x"), json={
                "name": "INVALID_REQUEST", "message": "Invalid", "details": [{"issue": self.issue}]})
            raise httpx.HTTPStatusError("refused", request=response.request, response=response)
        return {}


def send_approved(client, a, fake):
    app.dependency_overrides[paypal_sink] = lambda: fake
    approve(client, a)
    return client.post(f"/api/drafts/{a['draft']['id']}/submit")


def test_a_refused_type_goes_once_more_as_other_with_the_same_notes_and_files(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant)
    fake = RefusesTheFirstType()
    assert send_approved(client, a, fake).status_code == 200 and len(fake.sent) == 2
    (_, first, first_files), (_, second, second_files) = fake.sent
    assert second["evidences"][0]["evidence_type"] == "OTHER" and "evidence_info" not in second["evidences"][0]
    assert second["evidences"][0]["notes"] == first["evidences"][0]["notes"] and second_files == first_files
    with tenant_session(merchant, app_engine) as s:
        audit = s.execute(text("SELECT summary FROM audit_logs WHERE action = 'draft.submitted'")).scalar()
    assert audit["evidence_type"] == "OTHER"


def test_any_other_refusal_is_not_retried(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant)
    fake = RefusesTheFirstType(issue="MISSING_REQUIRED_PARAMETER")
    assert send_approved(client, a, fake).status_code == 502 and len(fake.sent) == 1


def test_a_server_error_is_never_retried_because_it_may_have_arrived(client, merchant, app_engine, worker_engine):
    _, a = analyzed(app_engine, worker_engine, merchant)
    fake = RefusesTheFirstType(status=500)
    assert send_approved(client, a, fake).status_code == 504 and len(fake.sent) == 1


def test_digital_goods_go_as_other_without_a_courier():
    digital = {"disputed_transactions": [{"items": [{"item_type": "DIGITAL_DOWNLOAD"}]}]}
    assert submission._is_digital(digital) and not submission._is_digital({}) and not submission._is_digital(
        {"disputed_transactions": [{"items": [{"item_type": "PRODUCT"}]}]})
    facts = [{"field": "tracking_id", "value": "TRK-1", "status": "supported"}]
    entry = submission._payload([{"text": "Sent."}], facts, ["PROOF_OF_FULFILLMENT"], [], digital=True)["evidences"][0]
    assert entry["evidence_type"] == "OTHER" and "evidence_info" not in entry

# --------------------------------------------------------------- approval is bound to what the analysis read
def test_a_document_added_after_the_analysis_blocks_approval(client, merchant, app_engine, worker_engine):
    dispute_id, a = analyzed(app_engine, worker_engine, merchant)
    add_document(app_engine, merchant, dispute_id)
    r = approve(client, a)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EVIDENCE_CHANGED"


def test_an_analysis_that_read_an_older_document_set_is_discarded_and_redone(merchant, app_engine, worker_engine, monkeypatch):
    from app.agent import runner
    dispute_id, _ = analyzed(app_engine, worker_engine, merchant)
    real = runner.analyze

    def document_arrives_mid_run(*args, **kwargs):
        add_document(app_engine, merchant, dispute_id, checksum="arrived-during-the-run")
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "analyze", document_arrives_mid_run)
    result = run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    assert result["discarded"] == "documents changed"
    with tenant_session(merchant, app_engine) as s:
        queued = s.execute(text("SELECT count(*) FROM jobs WHERE kind = 'analyze_dispute' AND state = 'QUEUED'")).scalar()
    assert queued == 1

def test_a_file_that_went_missing_stops_the_send(tmp_path, monkeypatch):
    doc = SimpleNamespace(evidence_id="E", object_key="gone/file", mime="image/png",
                          content_lines=[], doc_type="packing_proof")
    monkeypatch.setenv("SAL_STORAGE_DIR", str(tmp_path))
    with pytest.raises(submission.SubmissionError) as missing:
        submission._files_to_send([doc])
    assert missing.value.code == "DOCUMENT_MISSING"
