"""Deal Check: what was ordered, invoiced and delivered must match before delivery. Reads only, never PayPal."""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from app import agent_identity, deals, worker
from app.agent_identity import AgentRole
from app.deals import DealCategory, DealStatus, FindingCode, Invoice, PurchaseOrder, check_deal
from app.agent.models import CandidateFact, Document, Line, SourceRef
from app.agent.validation import ground
from app.db import tenant_session
from app.main import app, current_merchant
from app.seed import create_merchant
from app.seed_demo import seed_golden


def order_body(**overrides) -> dict:
    body = {"deal_ref": "PO-7781", "category": "GOODS", "currency": "USD", "max_total": "1300.00",
            "approved_by": "buyer-agent:garage-01", "expires_at": "2026-12-01T00:00:00Z",
            "ship_to": {"country": "AU", "city": "Perth", "postal_code": "6000"},
            "lines": [{"item_code": "BP-2217-A", "description": "Brake pad set", "quantity": "40",
                       "unit_price": "30.00"}]}
    return {**body, **overrides}


def invoice_body(**overrides) -> dict:
    body = {"invoice_ref": "INV-0091", "issued_at": "2026-11-03T09:00:00+07:00", "currency": "USD",
            "total": "1200.00", "ship_to": {"country": "AU", "city": "Perth", "postal_code": "6000"},
            "lines": [{"item_code": "BP-2217-A", "description": "Brake pad set", "quantity": "40",
                       "unit_price": "30.00"}]}
    return {**body, **overrides}


def codes(order: dict, invoice: dict) -> set[FindingCode]:
    return {f.code for f in check_deal(PurchaseOrder.model_validate(order), Invoice.model_validate(invoice)).findings}


# --------------------------------------------------------------- reading the data exactly
def test_a_matching_deal_is_clear():
    result = check_deal(PurchaseOrder.model_validate(order_body()), Invoice.model_validate(invoice_body()))
    assert result.status is DealStatus.CLEAR and result.findings == ()


@pytest.mark.parametrize("value", [1200.0, 1200, True, "1,200.00", "1.200,00", "NaN", "Infinity", "-1", ""])
def test_money_must_be_an_exact_decimal_string(value):
    with pytest.raises(ValidationError):
        Invoice.model_validate(invoice_body(total=value))


def test_a_typing_slip_in_a_field_name_is_refused_not_ignored():
    with pytest.raises(ValidationError):
        PurchaseOrder.model_validate(order_body(max_totl="1.00"))


def test_a_lowercase_item_code_reads_the_same_but_a_different_letter_does_not():
    lowercase = invoice_body(lines=[{"item_code": " bp-2217-a ", "description": "Brake pad set", "quantity": "40",
                                     "unit_price": "30.00"}])
    assert codes(order_body(), lowercase) == set()
    different = invoice_body(lines=[{"item_code": "BP-2217-B", "description": "Brake pad set", "quantity": "40",
                                     "unit_price": "30.00"}])
    assert codes(order_body(), different) == {FindingCode.ITEM_NOT_ORDERED, FindingCode.ITEM_NOT_INVOICED}


def test_the_same_item_twice_in_one_document_is_refused():
    line = {"item_code": "A-1", "description": "x", "quantity": "1", "unit_price": "1.00"}
    with pytest.raises(ValidationError):
        Invoice.model_validate(invoice_body(lines=[line, {**line, "item_code": "a-1"}]))


def test_a_date_without_a_time_zone_is_refused():
    with pytest.raises(ValidationError):
        PurchaseOrder.model_validate(order_body(expires_at="2026-12-01T00:00:00"))


def test_goods_need_an_address_and_services_do_not():
    with pytest.raises(ValidationError):
        PurchaseOrder.model_validate(order_body(ship_to=None))
    service = order_body(category="SERVICE", ship_to=None)
    assert codes(service, invoice_body(ship_to=None)) == set()


# --------------------------------------------------------------- rules
@pytest.mark.parametrize(("change", "expected"), [
    ({"lines": [{"item_code": "BP-2217-A", "description": "x", "quantity": "39", "unit_price": "30.00"}],
      "total": "1170.00"}, {FindingCode.QUANTITY_DIFFERS}),
    ({"lines": [{"item_code": "BP-2217-A", "description": "x", "quantity": "40", "unit_price": "29.00"}],
      "total": "1160.00"}, {FindingCode.UNIT_PRICE_DIFFERS}),
    ({"total": "1250.00"}, {FindingCode.TOTAL_DOES_NOT_ADD_UP}),
    ({"shipping": "150.00", "total": "1350.00"}, {FindingCode.OVER_APPROVED_LIMIT}),
    ({"issued_at": "2026-12-02T00:00:00Z"}, {FindingCode.APPROVAL_EXPIRED}),
    ({"ship_to": {"country": "AU", "city": "Perth", "postal_code": "6100"}}, {FindingCode.ADDRESS_DIFFERS}),
    ({"ship_to": {"country": "NZ", "city": "Perth", "postal_code": "6000"}}, {FindingCode.ADDRESS_DIFFERS}),
])
def test_each_difference_holds_the_deal(change, expected):
    assert codes(order_body(), invoice_body(**change)) == expected


def test_amounts_in_two_currencies_are_never_compared():
    assert codes(order_body(), invoice_body(currency="EUR", total="9999.00")) == {FindingCode.CURRENCY_DIFFERS}


def test_a_finding_shows_both_values():
    result = check_deal(PurchaseOrder.model_validate(order_body()),
                        Invoice.model_validate(invoice_body(ship_to={"country": "AU", "city": "Perth",
                                                                     "postal_code": "6100"})))
    finding = result.findings[0]
    assert result.status is DealStatus.HOLD
    assert (finding.ordered, finding.invoiced) == ("AU 6000", "AU 6100")


def test_a_digital_deal_ignores_addresses():
    digital = order_body(category="DIGITAL", ship_to=None)
    assert codes(digital, invoice_body(ship_to=None)) == set()


def test_values_in_code_match_the_database_checks():
    sql = next(Path(__file__).resolve().parents[1].glob("migrations/sql/*_deals.sql")).read_text(encoding="utf-8")
    for enum in (DealCategory, DealStatus):
        allowed = re.search(rf"{enum.__name__}: (.+)", sql).group(1)
        assert set(re.findall(r"[A-Z_]{3,}", allowed)) == {e.value for e in enum}


def test_money_keeps_its_exact_value():
    assert Invoice.model_validate(invoice_body()).total == Decimal("1200.00")


# --------------------------------------------------------------- autonomous run
class NoPayPal:
    def __call__(self):
        raise AssertionError("Deal Check must never touch PayPal")


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Deal-{uuid4().hex[:6]}")


@pytest.fixture
def client(merchant, app_engine, monkeypatch):
    monkeypatch.setattr("app.deals.app_engine", lambda: app_engine)
    app.dependency_overrides[current_merchant] = lambda: merchant
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def agents(merchant, app_engine) -> SimpleNamespace:
    def client_for(name: str, role: AgentRole) -> TestClient:
        token = agent_identity.issue(merchant, name, role, app_engine)
        return TestClient(app, headers={"authorization": f"Bearer {token}"})
    return SimpleNamespace(buyer=client_for("buyer-agent:garage-01", AgentRole.BUYER_AGENT),
                           seller=client_for("seller-agent:shop", AgentRole.SELLER_AGENT))


def ctx(worker_engine) -> worker.Context:
    return worker.Context(worker_engine, NoPayPal())


@pytest.mark.db
def test_the_worker_checks_a_deal_by_itself(client, agents, merchant, worker_engine):
    assert agents.buyer.post("/agent/v1/deals", json=order_body()).json()["status"] == "WAITING_INVOICE"
    wrong = invoice_body(lines=[{"item_code": "BP-2217-B", "description": "Brake pad set", "quantity": "40",
                                 "unit_price": "30.00"}])
    assert agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=wrong).json()["status"] == "CHECKING"
    worker.drain(ctx(worker_engine))
    held = client.get("/api/deals/PO-7781").json()
    assert held["status"] == "HOLD"
    assert {f["code"] for f in held["findings"]} == {"ITEM_NOT_ORDERED", "ITEM_NOT_INVOICED"}

    agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=invoice_body())
    worker.drain(ctx(worker_engine))
    clear = client.get("/api/deals/PO-7781").json()
    assert clear["status"] == "CLEAR" and clear["findings"] == []


@pytest.mark.db
def test_going_back_to_an_earlier_invoice_is_checked_again(client, agents, merchant, worker_engine):
    agents.buyer.post("/agent/v1/deals", json=order_body())
    for total in ("1200.00", "1250.00", "1200.00"):
        agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=invoice_body(total=total))
        worker.drain(ctx(worker_engine))
    assert client.get("/api/deals/PO-7781").json()["status"] == "CLEAR"


@pytest.mark.db
def test_a_result_for_an_older_invoice_is_never_kept(client, agents, merchant, worker_engine, app_engine):
    agents.buyer.post("/agent/v1/deals", json=order_body())
    agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=invoice_body(total="1250.00"))
    agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=invoice_body())
    worker.drain(ctx(worker_engine))
    deal = client.get("/api/deals/PO-7781").json()
    assert deal["status"] == "CLEAR" and deal["invoice"]["total"] == "1200.00"


@pytest.mark.db
def test_the_watch_round_finishes_a_check_whose_job_never_ran(client, agents, merchant, worker_engine):
    agents.buyer.post("/agent/v1/deals", json=order_body())
    agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=invoice_body())
    assert deals.check_open_deals(merchant, worker_engine) == 1
    assert client.get("/api/deals/PO-7781").json()["status"] == "CLEAR"


def _cards(client) -> list[dict]:
    return [c for c in client.get("/api/actions").json()["items"] if c["kind"] == "REVIEW_DEAL_HOLD"]


@pytest.mark.db
def test_a_hold_raises_a_card_and_clearing_it_removes_the_card(client, agents, worker_engine):
    agents.buyer.post("/agent/v1/deals", json=order_body())
    agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=invoice_body(total="1250.00"))
    worker.drain(ctx(worker_engine))
    card, = _cards(client)
    assert "PO-7781" in card["title"] and card["dispute_id"] is None
    agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=invoice_body())
    worker.drain(ctx(worker_engine))
    assert _cards(client) == []


TXN = "4KX12345AB678901C"


def _paypal_dispute(app_engine, merchant) -> UUID:
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("UPDATE disputes SET provider_payload = CAST(:p AS jsonb) WHERE id = :d"),
                  {"d": dispute_id, "p": json.dumps({"disputed_transactions": [{"seller_transaction_id": TXN}]})})
    return dispute_id


def _deal_records(app_engine, merchant, dispute_id) -> list:
    with tenant_session(merchant, app_engine) as s:
        return s.execute(text("""SELECT content_lines FROM evidence
                                 WHERE dispute_id = :d AND doc_type = 'deal_record'"""), {"d": dispute_id}).all()


@pytest.mark.db
def test_a_clear_deal_joins_its_dispute_as_evidence_once(client, agents, merchant, app_engine, worker_engine):
    agents.buyer.post("/agent/v1/deals", json=order_body())
    agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=invoice_body(paypal_transaction_id=TXN))
    worker.drain(ctx(worker_engine))
    dispute_id = _paypal_dispute(app_engine, merchant)
    assert deals.attach_to_dispute(merchant, dispute_id, worker_engine) == 1
    assert deals.attach_to_dispute(merchant, dispute_id, worker_engine) == 0
    lines = [line["text"] for line in _deal_records(app_engine, merchant, dispute_id)[0].content_lines]
    assert any("BP-2217-A" in line for line in lines) and any("matched" in line for line in lines)


@pytest.mark.db
def test_a_held_deal_is_not_evidence(client, agents, merchant, app_engine, worker_engine):
    agents.buyer.post("/agent/v1/deals", json=order_body())
    agents.seller.put("/agent/v1/deals/PO-7781/invoice", json=invoice_body(total="1250.00", paypal_transaction_id=TXN))
    worker.drain(ctx(worker_engine))
    dispute_id = _paypal_dispute(app_engine, merchant)
    assert deals.attach_to_dispute(merchant, dispute_id, worker_engine) == 0


def test_a_deal_record_proves_no_fact_by_itself():
    doc = Document("D", "deal_record", (Line(1, "Status: DELIVERED Tracking: JP8812345678"),), "SELLER_INPUT")
    facts = ground([CandidateFact("tracking_id", "JP8812345678", SourceRef("D", 1), "Tracking: JP8812345678")], [doc])
    assert {f.status for f in facts} == {"rejected"}


@pytest.mark.db
def test_a_second_order_with_the_same_reference_is_refused(client, agents):
    assert agents.buyer.post("/agent/v1/deals", json=order_body()).status_code == 201
    assert agents.buyer.post("/agent/v1/deals", json=order_body(max_total="9999.00")).status_code == 409


@pytest.mark.db
def test_an_invoice_for_an_unknown_deal_is_refused(client, agents):
    assert agents.seller.put("/agent/v1/deals/PO-NOPE/invoice", json=invoice_body()).status_code == 404


@pytest.mark.db
def test_a_bad_amount_is_refused_at_the_door(client, agents):
    assert agents.buyer.post("/agent/v1/deals", json=order_body(max_total=1300.0)).status_code == 422


@pytest.mark.db
def test_one_merchant_never_reads_anothers_deal(client, agents, merchant, app_engine):
    agents.buyer.post("/agent/v1/deals", json=order_body())
    other = create_merchant(f"Deal-{uuid4().hex[:6]}")
    app.dependency_overrides[current_merchant] = lambda: other
    assert client.get("/api/deals/PO-7781").status_code == 404
    assert client.get("/api/deals").json()["items"] == []
