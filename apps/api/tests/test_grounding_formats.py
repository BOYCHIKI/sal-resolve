"""Grounding on real-world formats: the same date, amount, status or reference written differently still
counts; anything ambiguous or merely implied does not."""
from __future__ import annotations

import pytest

from app.agent.evaluate import SPLIT_DIRS, load_cases, score_case, to_case_input
from app.agent.models import CandidateFact, Document, Line, SourceRef
from app.agent.pipeline import analyze
from app.agent.roles import ReadAllPlanner, TemplateDrafter
from app.agent.validation import ground, value_in_line


@pytest.mark.parametrize("field, value, text", [
    ("delivery_date", "2026-07-08", "Delivered: July 8, 2026 at 14:02"),
    ("delivery_date", "2026-07-08", "Delivered on 8th Jul 2026"),
    ("ship_date", "2026-07-03", "Shipped 2026/07/03 from Jakarta"),
    ("order_date", "2026-09-01", "Order placed Sept. 1, 2026"),
    ("order_amount", "1045.00", "Total: $1,045.00"),
    ("payment_amount", "45.00", "You paid 45 USD"),
    ("payment_amount", "45.00", "Amount received: €45"),
    ("order_amount", "45.50", "Grand total 45.5"),
    ("carrier_status", "DELIVERED", "Status: Delivered"),
    ("carrier_status", "IN_TRANSIT", "Your parcel is in transit"),
    ("carrier_status", "DELIVERED", "Delivered, In/At Mailbox"),
    ("order_id", "100245", "Order #100245"),
    ("tracking_id", "1Z999AA10123456784", "UPS tracking 1Z999AA10123456784"),
])
def test_same_value_in_another_format_counts(field, value, text):
    assert value_in_line(field, value, text)


@pytest.mark.parametrize("field, value, text, why", [
    ("delivery_date", "2026-07-08", "Delivered 08/07/2026", "day/month order is ambiguous"),
    ("delivery_date", "2026-07-08", "Delivered July 9, 2026", "different day"),
    ("order_amount", "45.00", "Order 45 of 300", "a bare number is not money"),
    ("order_amount", "5.00", "Total: $45.00", "part of a larger amount"),
    ("order_amount", "1045.00", "Total: $1,045.50", "different cents"),
    ("carrier_status", "DELIVERED", "Status: Out for delivery", "a different status"),
    ("order_id", "1002", "Order #100245", "part of a longer reference"),
    ("order_amount", "2.00", "QTY 2 PCS", "a 3-letter word is not a currency"),
    ("payment_amount", "45.00", "ORD 45 shipped", "an order prefix is not a currency"),
])
def test_ambiguous_or_different_values_do_not_count(field, value, text, why):
    assert not value_in_line(field, value, text), why


def test_ground_accepts_real_formats_and_normalizes():
    doc = Document("courier-email", "carrier_tracking", (
        Line(1, "Hi Sam, your UPS parcel 1Z999AA10123456784 was delivered."),
        Line(2, "Delivered: July 8, 2026 at 14:02 - Status: Delivered"),
    ))
    facts = ground([
        CandidateFact("tracking_id", "1Z999AA10123456784", SourceRef("courier-email", 1),
                      "Hi Sam, your UPS parcel 1Z999AA10123456784 was delivered."),
        CandidateFact("carrier_event_date", "2026-07-08", SourceRef("courier-email", 2), "Delivered: July 8, 2026"),
        CandidateFact("carrier_status", "Delivered", SourceRef("courier-email", 2), "Status: Delivered"),
        CandidateFact("carrier_event_date", "2026-07-09", SourceRef("courier-email", 2), "Delivered: July 8, 2026"),
    ], [doc])
    assert [(f.field, f.value, f.status) for f in facts] == [
        ("tracking_id", "1Z999AA10123456784", "supported"),
        ("carrier_event_date", "2026-07-08", "supported"),
        ("carrier_status", "DELIVERED", "supported"),
        ("carrier_event_date", "2026-07-09", "rejected"),  # the model's date is not the one written
    ]


class OracleExtractor:
    """Proposes exactly the labelled facts, quoting their lines: what a perfect model would return."""

    def __init__(self, case):
        self.case = case

    def extract(self, documents):
        lines = {(d.evidence_id, l.line): l.text for d in documents for l in d.lines}
        return [CandidateFact(f["field"], f["value"], SourceRef(f["source_ref"]["evidence_id"], f["source_ref"]["line"]),
                              lines[(f["source_ref"]["evidence_id"], f["source_ref"]["line"])])
                for f in self.case["ground_truth"]["supported_facts"]]


@pytest.mark.parametrize("case", load_cases("real_format", SPLIT_DIRS["real_format"]), ids=lambda c: c["case_id"])
def test_real_format_labels_are_groundable_and_consistent_with_rules(case):
    """Dataset check: every labelled fact survives grounding, and the rules find exactly the labelled
    missing documents and conflicts. Otherwise the gate would measure label errors, not the model."""
    result = analyze(to_case_input(case), ReadAllPlanner(), OracleExtractor(case), TemplateDrafter())
    s = score_case(case, result)
    assert [f for f in result.facts if f.status == "rejected"] == []
    assert (s.facts_found, s.facts_expected) == (s.facts_expected, len(case["ground_truth"]["supported_facts"]))
    assert (s.missing_fp, s.missing_fn, s.conflict_fp, s.conflict_fn) == (0, 0, 0, 0)
    expected_status = {(f["field"], f["value"]): f["expected_status"] for f in case["ground_truth"]["supported_facts"]}
    assert {(f.field, f.value): f.status for f in result.facts} == expected_status
    from app.agent.evaluate import expected_readiness
    assert result.assessment.readiness == expected_readiness(case)


def test_carrier_detail_after_the_status_is_dropped():
    doc = Document("usps", "carrier_tracking", (Line(1, "Delivered, In/At Mailbox"),))
    [f] = ground([CandidateFact("carrier_status", "Delivered, In/At Mailbox", SourceRef("usps", 1),
                                "Delivered, In/At Mailbox")], [doc])
    assert (f.value, f.status) == ("DELIVERED", "supported")


def test_two_values_for_one_field_are_a_conflict_never_a_silent_pick():
    """Review #1: a subtotal and a total both proposed as order_amount. Neither may reach the reply."""
    from app.agent.models import Claim
    from app.agent.validation import apply_inr_rules, verify_claims
    doc = Document("inv", "order_invoice", (Line(1, "Subtotal: $129.00"), Line(2, "Total: $135.00 USD")))
    facts = ground([CandidateFact("order_amount", "135.00", SourceRef("inv", 2), "Total: $135.00 USD"),
                    CandidateFact("order_amount", "129.00", SourceRef("inv", 1), "Subtotal: $129.00")], [doc])
    findings = apply_inr_rules(facts, [doc], "135.00", "USD")
    assert {f.status for f in facts} == {"conflicted"}
    assert any(f.kind == "conflict" and f.field == "order_amount" and len(f.source_refs) == 2 for f in findings)
    kept, _ = verify_claims([Claim("The customer paid 129.00.", ("order_amount",)),
                             Claim("The customer paid 135.00.", ("order_amount",))], facts)
    assert kept == []
