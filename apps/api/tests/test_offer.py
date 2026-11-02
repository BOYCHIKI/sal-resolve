"""OFFER_REFUND end to end: the card appears for a "not as described" inquiry, the merchant types the amount, and
SAL sends exactly one make-offer after re-reading the live dispute."""
from __future__ import annotations

import json
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import actions
from app.db import tenant_session
from app.main import app, current_merchant, paypal_sink
from app.seed import create_merchant
from app.seed_demo import seed_golden
from tests.test_actions import NOW
from tests.test_submission import FakePayPal

pytestmark = pytest.mark.db

OPTIONS = {"make_offer": {"offer_types": ["REFUND"]}, "accept_claim": {"accept_claim_types": ["REFUND"]}}
LIVE = {"status": "WAITING_FOR_SELLER_RESPONSE", "dispute_life_cycle_stage": "INQUIRY",
        "allowed_response_options": OPTIONS,
        "links": [{"rel": r} for r in ("self", "make_offer", "accept_claim")]}


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Offer-{uuid4().hex[:6]}")


@pytest.fixture
def client(merchant):
    app.dependency_overrides[current_merchant] = lambda: merchant
    yield TestClient(app)
    app.dependency_overrides.clear()


def offer_card(client, merchant, app_engine, worker_engine) -> dict:
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    with tenant_session(merchant, app_engine) as s:   # make it a sandbox "not as described" inquiry
        s.execute(text("""UPDATE disputes SET origin = 'PAYPAL_SANDBOX', reason = 'MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED',
                                              lifecycle_stage = 'INQUIRY', allowed_actions = '{make_offer,accept_claim}',
                                              provider_payload = CAST(:p AS jsonb) WHERE id = :d"""),
                  {"d": dispute_id, "p": json.dumps({"allowed_response_options": OPTIONS})})
    actions.refresh_dispute(merchant, dispute_id, NOW, worker_engine)
    return next(c for c in client.get("/api/actions", params={"dispute_id": str(dispute_id)}).json()["items"]
                if c["kind"] == "OFFER_REFUND")


def approve(client, card, amount, fake):
    app.dependency_overrides[paypal_sink] = lambda: fake
    return client.post(f"/api/actions/{card['id']}/approve",
                       json={"payload_hash": card["payload_hash"], "offer_amount": amount})


def test_the_typed_amount_is_offered_once(client, merchant, app_engine, worker_engine):
    card = offer_card(client, merchant, app_engine, worker_engine)
    assert card["payload"]["max_amount"] == "45.00" and "up to 45.00 USD" in card["rationale"]   # cents, not 45.0000
    fake = FakePayPal(show=LIVE)
    r = approve(client, card, "20.5", fake)
    assert r.status_code == 200 and r.json()["offer"] == {"amount": "20.50", "currency": "USD"}
    (_, payload), = fake.sent
    assert payload["offer_type"] == "REFUND" and payload["offer_amount"] == {"currency_code": "USD", "value": "20.50"}
    assert "20.50 USD" in payload["note"]
    assert approve(client, card, "20.50", fake).json()["detail"]["code"] == "ACTION_NOT_OPEN" and len(fake.sent) == 1
    with tenant_session(merchant, app_engine) as s:
        audit = s.execute(text("SELECT summary FROM audit_logs WHERE action = 'paypal.make_offer'")).scalar()
    assert audit["amount"] == "20.50"


@pytest.mark.parametrize("amount", [None, "", "0", "-1", "45.01", "1.005", "NaN", "abc"])
def test_a_bad_amount_sends_nothing_and_keeps_the_card_open(client, merchant, app_engine, worker_engine, amount):
    card = offer_card(client, merchant, app_engine, worker_engine)
    fake = FakePayPal(show=LIVE)
    r = approve(client, card, amount, fake)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_OFFER_AMOUNT" and fake.sent == []
    assert approve(client, card, "45.00", fake).status_code == 200      # still open: the merchant can fix it


def test_nothing_is_sent_when_paypal_no_longer_takes_offers(client, merchant, app_engine, worker_engine):
    card = offer_card(client, merchant, app_engine, worker_engine)
    fake = FakePayPal(show={**LIVE, "links": [{"rel": "self"}]})        # e.g. the buyer escalated meanwhile
    r = approve(client, card, "10", fake)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "OFFER_NOT_AVAILABLE" and fake.sent == []


def _refresh(merchant, dispute_id, worker_engine):
    actions.refresh_dispute(merchant, UUID(dispute_id), NOW, worker_engine)


def _open_offers(client, dispute_id) -> list[dict]:
    items = client.get("/api/actions", params={"dispute_id": dispute_id}).json()["items"]
    return [c for c in items if c["kind"] == "OFFER_REFUND"]


def test_a_paypal_5xx_may_have_arrived_so_no_new_card_appears(client, merchant, app_engine, worker_engine):
    card = offer_card(client, merchant, app_engine, worker_engine)
    down = httpx.HTTPStatusError("503", request=httpx.Request("POST", "https://x"), response=httpx.Response(503))
    r = approve(client, card, "10", FakePayPal(show=LIVE, fail=down))
    assert r.json()["detail"]["code"] == "OFFER_UNCONFIRMED"
    _refresh(merchant, card["dispute_id"], worker_engine)
    assert _open_offers(client, card["dispute_id"]) == []


def test_an_offer_in_flight_does_not_come_back_as_a_new_card(client, merchant, app_engine, worker_engine):
    card = offer_card(client, merchant, app_engine, worker_engine)
    actions._claim(merchant, UUID(card["id"]), card["payload_hash"], "APPROVED", "operator:test", app_engine)
    _refresh(merchant, card["dispute_id"], worker_engine)     # the process died, or PayPal is still answering
    assert _open_offers(client, card["dispute_id"]) == []


def test_paypal_refusing_fails_the_card_and_a_timeout_is_never_resent(client, merchant, app_engine, worker_engine):
    card = offer_card(client, merchant, app_engine, worker_engine)
    refused = httpx.HTTPStatusError("422", request=httpx.Request("POST", "https://x"),
                                    response=httpx.Response(422))
    r = approve(client, card, "10", FakePayPal(show=LIVE, fail=refused))
    assert r.status_code == 502 and r.json()["detail"]["code"] == "PAYPAL_REJECTED"

    card = offer_card(client, merchant, app_engine, worker_engine)     # a second case
    timeout = FakePayPal(show=LIVE, fail=httpx.ReadTimeout("slow"))
    r = approve(client, card, "10", timeout)
    assert r.json()["detail"]["code"] == "OFFER_UNCONFIRMED"
    done = client.get("/api/actions", params={"status": "DONE", "dispute_id": card["dispute_id"]}).json()["items"]
    assert done[0]["result"]["outcome"] == "unconfirmed"
    assert approve(client, card, "10", timeout).json()["detail"]["code"] == "ACTION_NOT_OPEN" and len(timeout.sent) == 1
