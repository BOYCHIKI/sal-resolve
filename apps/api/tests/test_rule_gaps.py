"""Audit leads on reading couriers' words and tying a parcel to its order. Rules only, no model."""
from __future__ import annotations

import pytest

from app.agent.models import CandidateFact, Document, Fact, Line, SourceRef
from app.agent.roles import LabelExtractor
from app.agent.validation import _status_phrase, apply_inr_rules, ground, value_in_line


def fact(field: str, value: str, evidence: str = "E", line: int = 1) -> Fact:
    return Fact(field, value, SourceRef(evidence, line), "supported")


def conflicts(*facts: Fact) -> set[str]:
    docs = [Document("E", "carrier_tracking", (Line(1, "x"),)), Document("P", "delivery_proof", (Line(1, "x"),))]
    return {f.field for f in apply_inr_rules(list(facts), docs, "1.00", "USD") if f.kind == "conflict"}


@pytest.mark.parametrize("line", ["Status: NOT DELIVERED", "Status: Cannot be delivered", "Status: Never delivered",
                                  "Status: Scheduled to be delivered", "To be delivered by 2026-10-24",
                                  "Expected delivered 2026-10-24", "Akan diterima 24 Okt 2026", "Status: Undelivered"])
def test_wording_that_means_not_yet_is_not_delivered(line):
    assert _status_phrase(line) != "DELIVERED"
    assert not value_in_line("carrier_status", "DELIVERED", line)


@pytest.mark.parametrize("line", ["Status: DELIVERED", "Delivered on 3 September 2026", "Paket telah diterima oleh AIRA",
                                  "Carrier status: DELIVERED"])
def test_plain_delivered_wording_still_reads(line):
    assert value_in_line("carrier_status", "DELIVERED", line)


def test_underscored_statuses_still_read():
    assert value_in_line("carrier_status", "IN_TRANSIT", "Carrier status: IN_TRANSIT")


def test_a_model_cannot_ground_delivered_on_a_negated_upper_case_line():
    doc = Document("E", "carrier_tracking", (Line(1, "Status: NOT DELIVERED"),))
    got = ground([CandidateFact("carrier_status", "DELIVERED", SourceRef("E", 1), "Status: NOT DELIVERED")], [doc])
    assert got[0].status == "rejected"


@pytest.mark.parametrize("line", ["Not delivered on 2026-10-24", "Belum diterima 24 Okt 2026", "To be delivered by 2026-10-24"])
def test_a_date_on_a_not_delivered_line_is_no_delivery_date(line):
    doc = Document("P", "delivery_proof", (Line(1, line),))
    assert "delivery_date" not in {c.field for c in LabelExtractor().extract([doc])}
    assert not value_in_line("delivery_date", "2026-10-24", line)


def test_a_real_delivery_date_still_reads():
    doc = Document("P", "delivery_proof", (Line(1, "Delivered on 2026-10-24"),))
    assert "delivery_date" in {c.field for c in LabelExtractor().extract([doc])}


def test_a_delivery_before_the_order_goes_to_a_person_without_a_ship_date():
    assert "delivered_before_order" in conflicts(fact("order_date", "2026-10-10"), fact("delivery_date", "2026-09-01", "P"))


def test_a_delivery_after_the_order_is_fine():
    assert "delivered_before_order" not in conflicts(fact("order_date", "2026-10-10"), fact("delivery_date", "2026-10-20", "P"))


def test_a_courier_page_for_another_order_goes_to_a_person():
    assert "tracking_order_id" in conflicts(fact("order_id", "ORD-1"), fact("tracking_order_id", "ORD-2"))
    assert "tracking_order_id" not in conflicts(fact("order_id", "ORD-1"), fact("tracking_order_id", "ORD-1"))


@pytest.mark.parametrize(("page", "flagged"), [("Delivered 2026-10-20", True), ("Delivered TRK-123 on 2026-10-20", False)])
def test_a_dated_proof_must_mention_this_cases_parcel(page, flagged):
    found = apply_inr_rules([fact("tracking_id", "TRK-123"), fact("delivery_date", "2026-10-20", "P")],
                            [Document("P", "delivery_proof", (Line(1, page),))], "1.00", "USD")
    assert ("delivery_tracking_id" in {f.field for f in found if f.kind == "missing"}) is flagged


def test_a_long_warehouse_scan_is_not_a_failed_delivery():
    line = "Paket telah diterima di Gateway Soekarno-Hatta"
    doc = Document("E", "carrier_tracking", (Line(1, line),))
    rejected = ground([CandidateFact("carrier_status", line, SourceRef("E", 1), line)], [doc])
    assert rejected[0].status == "rejected"
    assert "delivery_status" not in {f.field for f in apply_inr_rules(rejected, [doc], "1.00", "USD")}


def test_a_status_that_says_it_failed_still_goes_to_a_person():
    line = "Status: Gagal antar, penerima tidak ada"
    doc = Document("E", "carrier_tracking", (Line(1, line),))
    rejected = ground([CandidateFact("carrier_status", "Gagal antar, penerima tidak ada", SourceRef("E", 1), line)], [doc])
    assert "delivery_status" in {f.field for f in apply_inr_rules(rejected, [doc], "1.00", "USD")}
