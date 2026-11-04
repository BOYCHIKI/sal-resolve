"""A resi the seller types in: recorded as the seller's word, never as proof. It names the parcel and the PayPal
carrier, catches a resi that differs from the courier page, and never shows the parcel moved or arrived."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent.assess import assess
from app.agent.models import CandidateFact, Document, Line, SourceRef
from app.agent.validation import apply_inr_rules, ground
from app.db import tenant_session
from app.main import app, current_merchant
from app.seed import create_merchant
from app.seed_demo import seed_golden


# --------------------------------------------------------------- what a typed resi can and cannot prove
def _seller_doc(resi: str) -> Document:
    return Document("S", "seller_shipment", (Line(1, f"Tracking number: {resi}"), Line(2, "Courier: JNE")),
                    "SELLER_INPUT")


def test_a_typed_resi_names_the_parcel_but_never_proves_it_moved_or_arrived():
    doc = _seller_doc("1102846637184921")
    facts = ground([CandidateFact("tracking_id", "1102846637184921", SourceRef("S", 1),
                                  "Tracking number: 1102846637184921"),
                    CandidateFact("carrier_status", "DELIVERED", SourceRef("S", 2), "Courier: JNE")], [doc])
    assert [(f.field, f.status) for f in facts] == [("tracking_id", "supported"), ("carrier_status", "rejected")]
    a = assess(facts, apply_inr_rules(facts, [doc], "45.00", "USD"), [doc], "45.00", "USD")
    status = {p.id: p.status for p in a.propositions}
    assert status["shipped"] == "missing" and status["delivered"] == "missing"
    assert "1102846637184921" in next(p.reason for p in a.propositions if p.id == "shipped")


def test_a_typed_resi_that_differs_from_the_courier_page_is_a_conflict():
    seller = _seller_doc("1102846637184921")
    courier = Document("T", "carrier_tracking", (Line(1, "No. Resi: 1102846637999999"),), "UPLOAD")
    facts = ground([CandidateFact("tracking_id", "1102846637184921", SourceRef("S", 1),
                                  "Tracking number: 1102846637184921"),
                    CandidateFact("tracking_id", "1102846637999999", SourceRef("T", 1), "No. Resi: 1102846637999999")],
                   [seller, courier])
    findings = apply_inr_rules(facts, [seller, courier], "45.00", "USD")
    assert [f.field for f in findings if f.kind == "conflict"] == ["tracking_id"]


# --------------------------------------------------------------- API
@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Resi-{uuid4().hex[:6]}")


@pytest.fixture
def client(merchant):
    app.dependency_overrides[current_merchant] = lambda: merchant
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.db
def test_entering_a_resi_records_it_with_the_paypal_carrier_and_queues_a_check(client, merchant, app_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-011")
    r = client.post(f"/api/disputes/{dispute_id}/tracking", json={"tracking_number": "1102 8466 3718 4921",
                                                                  "courier": "jne"})
    assert r.status_code == 201
    body = r.json()
    assert (body["tracking_number"], body["courier"], body["paypal_carrier"]) == ("1102846637184921", "JNE", "IDN_JNE")
    with tenant_session(merchant, app_engine) as s:
        row = s.execute(text("""SELECT origin, doc_type, mime, object_key, content_lines FROM evidence
                                WHERE id = :e"""), {"e": body["evidence_id"]}).one()
        queued = s.execute(text("SELECT count(*) FROM jobs WHERE kind = 'analyze_dispute' AND target_id = :d"),
                           {"d": dispute_id}).scalar()
    assert (row.origin, row.doc_type, row.mime, row.object_key) == ("SELLER_INPUT",
                                                                    "seller_shipment", "text/plain", None)
    assert [line["text"] for line in row.content_lines] == ["Tracking number: 1102846637184921", "Courier: JNE"]
    assert queued >= 1

    again = client.post(f"/api/disputes/{dispute_id}/tracking", json={"tracking_number": "1102846637184921",
                                                                      "courier": "JNE"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "DUPLICATE_TRACKING"


@pytest.mark.db
@pytest.mark.parametrize("payload, code", [
    ({"tracking_number": "12"}, "BAD_TRACKING_NUMBER"),                                  # too short
    ({"tracking_number": "ABCDEFGH"}, "BAD_TRACKING_NUMBER"),                            # no digit
    ({"tracking_number": "JP8812345678; DROP"}, "BAD_TRACKING_NUMBER"),                  # not a resi
    ({"tracking_number": "JP8812345678", "courier": "<script>"}, "BAD_COURIER"),
])
def test_a_bad_resi_or_courier_is_refused(client, merchant, app_engine, payload, code):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-011")
    r = client.post(f"/api/disputes/{dispute_id}/tracking", json=payload)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code


@pytest.mark.db
def test_another_merchant_cannot_add_a_resi_to_my_case(client, merchant, app_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-011")
    app.dependency_overrides[current_merchant] = lambda: create_merchant("Intruder")
    r = client.post(f"/api/disputes/{dispute_id}/tracking", json={"tracking_number": "JP8812345678"})
    assert r.status_code == 404
