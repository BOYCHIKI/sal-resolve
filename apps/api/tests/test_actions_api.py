"""Agent suggestions end to end (ADR-006): the worker proposes after an analysis, the merchant approves the exact
card, and only SEND_EVIDENCE reaches PayPal — once, through the ADR-003 submission path."""
from __future__ import annotations

import threading
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import worker
from app.agent.runner import baseline_roles, run_analysis
from app.db import tenant_session
from app.main import app, current_merchant, paypal_sink
from app.seed import create_merchant
from app.seed_demo import seed_golden
from tests.fakes import paypal
from tests.test_submission import FakePayPal

pytestmark = pytest.mark.db


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Cards-{uuid4().hex[:6]}")


@pytest.fixture
def client(merchant):
    app.dependency_overrides[current_merchant] = lambda: merchant
    yield TestClient(app)
    app.dependency_overrides.clear()


def ready_case(merchant, app_engine, worker_engine, golden="SAL-INR-001") -> UUID:
    """A PayPal Sandbox case whose documents prove everything, analysed, with its suggestions proposed."""
    dispute_id = seed_golden(app_engine, merchant, golden)
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("UPDATE disputes SET origin = 'PAYPAL_SANDBOX' WHERE id = :d"), {"d": dispute_id})
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    worker.drain(worker.Context(worker_engine, paypal(lambda: FakePayPal())))  # runs propose_actions
    return dispute_id


def cards(client, **params):
    return client.get("/api/actions", params=params).json()["items"]


def test_analysis_leads_to_one_send_card(client, merchant, app_engine, worker_engine):
    dispute_id = ready_case(merchant, app_engine, worker_engine)
    open_cards = cards(client, dispute_id=str(dispute_id))
    assert [c["kind"] for c in open_cards] == ["SEND_EVIDENCE"]
    assert open_cards[0]["title"] == "Send your evidence to PayPal"


def test_approving_the_card_sends_once_and_closes_it(client, merchant, app_engine, worker_engine):
    dispute_id = ready_case(merchant, app_engine, worker_engine)
    card = cards(client, dispute_id=str(dispute_id))[0]
    fake = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: fake

    stale = client.post(f"/api/actions/{card['id']}/approve", json={"payload_hash": "0" * 64})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE_ACTION" and fake.sent == []

    r = client.post(f"/api/actions/{card['id']}/approve", json={"payload_hash": card["payload_hash"]})
    assert r.status_code == 200 and r.json()["status"] == "DONE" and len(fake.sent) == 1
    again = client.post(f"/api/actions/{card['id']}/approve", json={"payload_hash": card["payload_hash"]})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "ACTION_NOT_OPEN" and len(fake.sent) == 1

    worker.drain(worker.Context(worker_engine, paypal(lambda: fake)))  # re-propose after the send
    assert cards(client, dispute_id=str(dispute_id)) == []          # nothing left to send
    done = cards(client, status="DONE", dispute_id=str(dispute_id))
    assert done[0]["result"]["outcome"] == "sent"


def test_two_simultaneous_approvals_send_once(client, merchant, app_engine, worker_engine):
    from app import actions
    dispute_id = ready_case(merchant, app_engine, worker_engine)
    card = cards(client, dispute_id=str(dispute_id))[0]
    fake = FakePayPal()
    gate, outcomes = threading.Barrier(2), []

    def press():
        gate.wait()
        try:
            outcomes.append(actions.approve(merchant, UUID(card["id"]), card["payload_hash"], "operator:test", fake,
                                            app_engine)["status"])
        except actions.ActionError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=press) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ACTION_NOT_OPEN", "DONE"] and len(fake.sent) == 1


def test_documents_changed_after_the_card_block_the_send(client, merchant, app_engine, worker_engine):
    dispute_id = ready_case(merchant, app_engine, worker_engine)
    card = cards(client, dispute_id=str(dispute_id))[0]
    with tenant_session(merchant, app_engine) as s:  # the case moved on (e.g. PayPal update) after the card
        s.execute(text("UPDATE disputes SET version = version + 1 WHERE id = :d"), {"d": dispute_id})
    fake = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: fake
    r = client.post(f"/api/actions/{card['id']}/approve", json={"payload_hash": card["payload_hash"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DISPUTE_CHANGED" and fake.sent == []
    assert cards(client, status="FAILED", dispute_id=str(dispute_id))[0]["result"]["code"] == "DISPUTE_CHANGED"


def test_guidance_cards_never_call_paypal(client, merchant, app_engine, worker_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-011")  # a case with missing evidence
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    worker.drain(worker.Context(worker_engine, paypal(lambda: FakePayPal())))
    open_cards = cards(client, dispute_id=str(dispute_id))
    assert open_cards and all(c["kind"] != "SEND_EVIDENCE" for c in open_cards)
    fake = FakePayPal()
    app.dependency_overrides[paypal_sink] = lambda: fake
    card = open_cards[0]
    r = client.post(f"/api/actions/{card['id']}/approve", json={"payload_hash": card["payload_hash"]})
    assert r.status_code == 200 and r.json()["status"] == "DONE" and fake.sent == []


def test_dismissed_card_cannot_be_approved(client, merchant, app_engine, worker_engine):
    dispute_id = ready_case(merchant, app_engine, worker_engine)
    card = cards(client, dispute_id=str(dispute_id))[0]
    assert client.post(f"/api/actions/{card['id']}/dismiss").json()["status"] == "DISMISSED"
    r = client.post(f"/api/actions/{card['id']}/approve", json={"payload_hash": card["payload_hash"]})
    assert r.status_code == 409


def test_another_merchant_cannot_see_or_decide_a_card(client, merchant, app_engine, worker_engine):
    dispute_id = ready_case(merchant, app_engine, worker_engine)
    card = cards(client, dispute_id=str(dispute_id))[0]
    app.dependency_overrides[current_merchant] = lambda: create_merchant("Intruder")
    assert cards(client) == []
    r = client.post(f"/api/actions/{card['id']}/approve", json={"payload_hash": card["payload_hash"]})
    assert r.status_code == 404
    assert client.post(f"/api/actions/{card['id']}/dismiss").status_code == 404


def test_a_kept_card_takes_new_wording_but_keeps_its_id_and_hash(client, merchant, app_engine, worker_engine):
    from dataclasses import replace

    from app import actions
    dispute_id = ready_case(merchant, app_engine, worker_engine)
    before = cards(client, dispute_id=str(dispute_id))[0]
    p = actions.Proposal(before["kind"], f"dispute:{dispute_id}", before["title"], before["rationale"],
                         before["payload"])
    result = actions.save(merchant, p.subject_key, dispute_id, [replace(p, rationale="Clearer words.")], worker_engine)
    after = cards(client, dispute_id=str(dispute_id))[0]
    assert result["kept"] == 1 and after["id"] == before["id"] and after["payload_hash"] == before["payload_hash"]
    assert after["rationale"] == "Clearer words."

def test_a_sent_case_stays_quiet_after_a_sync_re_analyses_it(client, merchant, app_engine, worker_engine):
    from datetime import datetime, timezone

    from app import actions
    dispute_id = ready_case(merchant, app_engine, worker_engine)
    card = cards(client, dispute_id=str(dispute_id))[0]
    app.dependency_overrides[paypal_sink] = lambda: FakePayPal()
    assert client.post(f"/api/actions/{card['id']}/approve",
                       json={"payload_hash": card["payload_hash"]}).status_code == 200
    with tenant_session(merchant, app_engine) as s:   # PayPal moved on (no evidence wanted) and the sync re-analysed
        s.execute(text("UPDATE disputes SET allowed_actions = '{accept_claim}' WHERE id = :d"), {"d": dispute_id})
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    actions.refresh_dispute(merchant, dispute_id, datetime.now(timezone.utc), worker_engine)
    assert cards(client, dispute_id=str(dispute_id)) == []