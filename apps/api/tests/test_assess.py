"""ASSESS business rules (ADR-005): partial disputes, dispute reasons, PayPal's own evidence requests."""
from __future__ import annotations

from app.agent.assess import assess
from app.agent.models import CaseInput, Document, Fact, Line, SourceRef
from app.agent.pipeline import analyze
from app.agent.roles import ReadAllPlanner, RuleExtractor, TemplateDrafter
from app.agent.validation import apply_inr_rules

PAYPAL = Document("pp", "payment_record", (Line(1, "Amount: 135.00 USD"),), "PAYPAL_API")
TRACK = Document("trk", "carrier_tracking", (Line(1, "Tracking TRK-1"), Line(2, "Status: DELIVERED")))


def paid(value="135.00", currency="USD"):
    return [Fact("payment_amount", value, SourceRef("pp", 1), "supported"),
            Fact("payment_currency", currency, SourceRef("pp", 1), "supported")]


def delivered():
    return [Fact("tracking_id", "TRK-1", SourceRef("trk", 1), "supported"),
            Fact("carrier_status", "DELIVERED", SourceRef("trk", 2), "supported")]


def test_partial_dispute_is_normal_not_a_mismatch():
    """B1: the buyer paid 135.00 but disputes 40.00 (one item of two)."""
    facts = paid()
    findings = apply_inr_rules(facts, [PAYPAL, TRACK], "40.00", "USD")
    assert not [f for f in findings if f.field.endswith("_vs_dispute")]
    a = assess(facts, findings, (PAYPAL, TRACK), "40.00", "USD")
    assert a.status("payment_matches") == "proven" and "disputes 40.00" in a.propositions[0].reason


def test_payment_below_the_dispute_or_in_another_currency_is_a_contradiction():
    low = paid("30.00")
    findings = apply_inr_rules(low, [PAYPAL], "40.00", "USD")
    assert any(f.field == "payment_amount_vs_dispute" for f in findings)
    assert assess(low, findings, (PAYPAL,), "40.00", "USD").status("payment_matches") == "contradicted"
    eur = paid("135.00", "EUR")
    assert assess(eur, [], (PAYPAL,), "135.00", "USD").status("payment_matches") == "contradicted"


def test_other_dispute_reasons_are_not_judged_by_shipping_rules():
    """B2: a 'not as described' dispute must not be told it lacks courier tracking."""
    case = CaseInput("X", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "135.00", "USD", (), (PAYPAL,))
    r = analyze(case, ReadAllPlanner(), RuleExtractor(), TemplateDrafter())
    assert r.assessment.propositions == () and r.assessment.readiness == "NEEDS_CHECK"
    assert "item not received" in r.assessment.next_action
    assert not [f for f in r.findings if f.kind == "missing"]


def test_paypals_own_evidence_request_is_part_of_readiness():
    """B3: PayPal asked for proof of fulfillment; it is covered only when shipping and delivery are proven."""
    facts = paid() + delivered()
    ok = assess(facts, [], (PAYPAL, TRACK), "135.00", "USD", requested=("PROOF_OF_FULFILLMENT",))
    assert ok.status("paypal_request_covered") == "proven" and ok.readiness == "READY"
    gap = assess(paid(), [], (PAYPAL, TRACK), "135.00", "USD", requested=("PROOF_OF_FULFILLMENT",))
    assert gap.status("paypal_request_covered") == "missing" and gap.readiness == "NEEDS_DOCUMENTS"
    odd = assess(facts, [], (PAYPAL, TRACK), "135.00", "USD", requested=("OTHER",))
    assert odd.status("paypal_request_covered") == "flagged" and odd.readiness == "NEEDS_CHECK"
    assert assess(facts, [], (PAYPAL, TRACK), "135.00", "USD").status("paypal_request_covered") == "not_applicable"


def test_a_request_for_proof_of_refund_alone_is_not_a_gap():
    facts = paid() + delivered()
    both = assess(facts, [], (PAYPAL, TRACK), "135.00", "USD", requested=("PROOF_OF_REFUND", "PROOF_OF_FULFILLMENT"))
    assert both.status("paypal_request_covered") == "proven" and both.readiness == "READY"
    assert "refund" not in next(p for p in both.propositions if p.id == "paypal_request_covered").reason
    alone = assess(facts, [], (PAYPAL, TRACK), "135.00", "USD", requested=("PROOF_OF_REFUND",))
    assert alone.status("paypal_request_covered") == "not_applicable"