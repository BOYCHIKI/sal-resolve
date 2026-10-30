"""Unauthorized payments are argued like 'not received': PayPal's Seller Protection covers them when the parcel
provably went to the address on the transaction, so that address is required, not optional."""
from __future__ import annotations

from app import actions
from app.agent.models import CaseInput
from app.agent.pipeline import analyze
from app.agent.roles import LabelExtractor, ReadAllPlanner, RuleExtractor, TemplateDrafter, UnionExtractor
from tests.test_actions import DRAFT, NOW, READY, dispute
from tests.test_inr_address_timeline import paypal, proof, tracking

PID = "delivered_to_paypal_address"


def run(*docs, reason="UNAUTHORISED"):
    case = CaseInput("U", reason, "110.35", "USD", (), docs)
    return analyze(case, ReadAllPlanner(), UnionExtractor(RuleExtractor(), LabelExtractor()), TemplateDrafter())


def test_delivery_to_the_paypal_address_makes_an_unauthorized_case_ready():
    r = run(paypal("Ship-to postal code: 94107"), tracking(), proof("ZIP: 94107"))
    assert r.assessment.readiness == "READY" and r.assessment.status(PID) == "proven"
    assert r.claims, "the reply states the delivery facts"


def test_without_paypals_address_an_unauthorized_case_is_not_ready():
    """For 'not received' the address check is skipped when PayPal has none; here it is the whole defence."""
    r = run(paypal(), tracking(), proof("ZIP: 94107"))
    assert r.assessment.status(PID) == "missing" and r.assessment.readiness == "NEEDS_DOCUMENTS"
    assert run(paypal(), tracking(), proof(), reason="ITEM_NOT_RECEIVED").assessment.status(PID) == "not_applicable"


def test_a_proof_without_an_address_is_not_enough():
    r = run(paypal("Ship-to postal code: 94107"), tracking(), proof())
    assert r.assessment.status(PID) == "missing" and "no delivery address" in r.assessment.next_action


def test_delivery_to_another_postal_code_stops_the_send():
    r = run(paypal("Ship-to postal code: 94107"), tracking(), proof("ZIP: 60601"))
    assert r.assessment.readiness == "NEEDS_CHECK"


def test_an_unauthorized_case_gets_a_send_card_instead_of_an_explanation():
    cards = actions.propose_for_dispute(dispute(reason="UNAUTHORISED"), READY, DRAFT, NOW)
    assert [c.kind for c in cards] == ["SEND_EVIDENCE"]


def test_not_as_described_is_still_explained_not_argued():
    cards = actions.propose_for_dispute(dispute(reason="MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"), READY, DRAFT, NOW)
    assert [c.kind for c in cards] == ["EXPLAIN_DISPUTE"]
