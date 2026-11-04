"""Rule version 3: PayPal's proof of delivery must show the address on the payment, and ordered -> shipped ->
delivered must happen in that order. Both are checked by rules, never by the model."""
from __future__ import annotations

import pytest

from app.agent.models import CaseInput, Document, Line
from app.agent.pipeline import analyze
from app.agent.roles import LabelExtractor, ReadAllPlanner, RuleExtractor, TemplateDrafter, UnionExtractor
from app.agent.validation import same_city, same_postal
from app.paypal_evidence import render_record

PID = "delivered_to_paypal_address"


def paypal(*extra: str, origin: str = "PAYPAL_API") -> Document:
    lines = ["Transaction ID: 0CJ46492KP237862A", "Amount: 110.35 USD", *extra]
    return Document("pp", "payment_record", tuple(Line(i, t) for i, t in enumerate(lines, 1)), origin)


def tracking(ship: str = "2026-10-20", latest: str = "2026-10-24", *extra: str) -> Document:
    lines = ["SYNTHETIC TRACKING | TRK-SYN-1", f"Ship date: {ship}", "Carrier status: DELIVERED",
             f"Latest event: {latest}", *extra]
    return Document("trk", "carrier_tracking", tuple(Line(i, t) for i, t in enumerate(lines, 1)))


def proof(*extra: str, delivered: str = "2026-10-24") -> Document:
    lines = ["SYNTHETIC DELIVERY CONFIRMATION | TRK-SYN-1", "Delivery status: DELIVERED",
             f"Delivery date: {delivered}", *extra]
    return Document("pod", "delivery_proof", tuple(Line(i, t) for i, t in enumerate(lines, 1)))


def proof_with_status(status: str) -> Document:
    lines = ["SYNTHETIC DELIVERY CONFIRMATION | TRK-SYN-1", f"Delivery status: {status}", "Delivery date: 2026-10-24"]
    return Document("pod", "delivery_proof", tuple(Line(i, t) for i, t in enumerate(lines, 1)))


def run(*docs: Document):
    case = CaseInput("X", "ITEM_NOT_RECEIVED", "110.35", "USD", (), docs)
    return analyze(case, ReadAllPlanner(), UnionExtractor(RuleExtractor(), LabelExtractor()), TemplateDrafter())


# --------------------------------------------------------------- delivered to the PayPal address
def test_a_proof_of_delivery_to_the_paypal_postal_code_proves_the_address():
    r = run(paypal("Ship-to city: San Francisco", "Ship-to postal code: 94107"), tracking(),
            proof("Delivered to postal code: 94107-1234"))
    assert r.assessment.status(PID) == "proven" and r.assessment.readiness == "READY"


def test_a_different_postal_code_stops_the_send():
    r = run(paypal("Ship-to postal code: 94107"), tracking(), proof("Delivered to postal code: 10001"))
    assert r.assessment.status(PID) == "contradicted" and r.assessment.readiness == "NEEDS_CHECK"
    assert "different postal code" in r.assessment.next_action


def test_a_proof_without_any_address_is_not_enough_when_paypal_has_one():
    r = run(paypal("Ship-to postal code: 94107"), tracking(), proof())
    assert r.assessment.status(PID) == "missing" and r.assessment.readiness == "NEEDS_DOCUMENTS"
    assert "no delivery address" in r.assessment.next_action


def test_no_address_on_the_paypal_record_leaves_the_check_out():
    r = run(paypal(), tracking(), proof("Delivered to postal code: 94107"))
    assert r.assessment.status(PID) == "not_applicable" and r.assessment.readiness == "READY"


def test_a_city_is_compared_leniently_and_a_different_one_goes_to_a_person():
    same = run(paypal("Ship-to city: KOTA BANDUNG"), tracking(), proof("Kota: Bandung"))
    assert same.assessment.status(PID) == "proven"
    other = run(paypal("Ship-to city: Bandung"), tracking(), proof("Kota: Surabaya"))
    assert other.assessment.status(PID) == "flagged" and other.assessment.readiness == "NEEDS_CHECK"


def test_only_paypals_record_can_say_where_the_parcel_should_go():
    """A seller's own 'payment record' upload cannot set the address the proof is checked against."""
    r = run(paypal("Ship-to postal code: 94107", origin="UPLOAD"), tracking(), proof("ZIP: 94107"))
    assert r.assessment.status(PID) == "not_applicable"


def test_courier_labels_are_read_and_a_tracking_number_is_not_a_postal_code():
    r = run(paypal("Ship-to postal code: 40115"), tracking("2026-10-20", "2026-10-24", "Kode pos: 40115"),
            proof("Resi: JP8812345678"))
    codes = {f.value for f in r.facts if f.field == "delivery_postal_code" and f.status == "supported"}
    assert codes == {"40115"} and r.assessment.status(PID) == "proven"


def test_postal_and_city_matching():
    assert same_postal("94107", "94107-1234") and same_postal("sw1a 1aa", "SW1A1AA")
    assert not same_postal("94107", "94108") and not same_postal("1000", "10001")
    assert same_city("Kota Bandung", "BANDUNG") and same_city("City of Manila", "Manila")
    assert not same_city("Bandung", "Surabaya")


def test_the_paypal_record_keeps_city_and_postal_code_but_not_name_or_street():
    details = {"transaction_info": {"transaction_id": "0CJ46492KP237862A", "transaction_amount":
                                    {"value": "110.35", "currency_code": "USD"}},
               "shipping_info": {"name": "Buyer Person", "address": {"line1": "1 Main St", "city": "San Francisco",
                                                                     "postal_code": "94107", "country_code": "US"}}}
    lines = render_record(details)
    assert "Ship-to city: San Francisco" in lines and "Ship-to postal code: 94107" in lines
    assert not any("Buyer Person" in t or "Main St" in t for t in lines)


# --------------------------------------------------------------- ordered -> shipped -> delivered
def test_delivered_before_it_was_shipped_goes_to_a_person():
    r = run(paypal(), tracking("2026-10-25", "2026-10-24"), proof())
    assert r.assessment.status("delivered") == "contradicted" and r.assessment.readiness == "NEEDS_CHECK"
    assert any(f.field == "delivered_before_ship" for f in r.findings)


def test_shipped_before_the_order_goes_to_a_person():
    invoice = Document("inv", "order_invoice", (Line(1, "Invoice INV-77"), Line(2, "Order date: 2026-10-22")))
    r = run(paypal(), invoice, tracking("2026-10-20", "2026-10-24"), proof())
    assert any(f.field == "ship_before_order" for f in r.findings)
    assert r.assessment.status("shipped") == "contradicted" and r.assessment.readiness == "NEEDS_CHECK"


def test_a_normal_timeline_raises_nothing():
    invoice = Document("inv", "order_invoice", (Line(1, "Invoice INV-77"), Line(2, "Order date: 2026-10-18")))
    r = run(paypal(), invoice, tracking(), proof())
    assert not [f for f in r.findings if f.field in ("ship_before_order", "delivered_before_ship")]


# --------------------------------------------------------------- a failed delivery outvotes a dated proof
@pytest.mark.parametrize("status", ["RETURNED", "NOT_DELIVERED", "FAILED"])
def test_a_proof_saying_the_delivery_failed_never_proves_delivery(status):
    r = run(paypal(), tracking(), proof_with_status(status))
    assert r.assessment.status("delivered") == "contradicted" and r.assessment.readiness == "NEEDS_CHECK"
    assert any(f.field == "delivery_status" for f in r.findings)


def test_a_courier_page_saying_returned_stops_a_dated_proof():
    page = Document("trk", "carrier_tracking",
                    (Line(1, "SYNTHETIC TRACKING | TRK-SYN-1"), Line(2, "Ship date: 2026-10-20"),
                                                Line(3,
                                                     "Carrier status: RETURNED"), Line(4, "Latest event: 2026-10-24")))
    r = run(paypal(), page, proof())
    assert r.assessment.status("delivered") == "contradicted" and r.assessment.readiness == "NEEDS_CHECK"


def test_a_parcel_still_moving_on_the_courier_page_is_not_a_failed_delivery():
    page = Document("trk", "carrier_tracking",
                    (Line(1, "SYNTHETIC TRACKING | TRK-SYN-1"), Line(2, "Ship date: 2026-10-20"),
                                                Line(3, "Carrier status: IN_TRANSIT"), Line(4, "Latest event: 2026-10-24")))
    r = run(paypal(), page, proof())
    assert not [f for f in r.findings if f.field == "delivery_status"]

@pytest.mark.parametrize("status", ["COMPLETED", "PICKED_UP", "IN_TRANSIT"])
def test_an_ordinary_status_is_not_called_a_failed_delivery(status):
    from app.agent.models import CandidateFact, Fact, SourceRef
    from app.agent.validation import apply_inr_rules, ground
    doc = Document("trk", "carrier_tracking", (Line(1, f"Status: {status}"),))
    facts = ground([CandidateFact("carrier_status", status, SourceRef("trk", 1), f"Status: {status}")], [doc])
    assert isinstance(facts[0], Fact) and facts[0].status == "supported"
    assert not [f for f in apply_inr_rules(facts, [doc], "10.00", "USD") if f.field == "delivery_status"]