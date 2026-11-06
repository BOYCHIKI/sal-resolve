"""Deal Check on a PayPal invoice: PayPal's invoice in SAL's terms, the checks before PayPal is called, and only the
business that owns the PayPal credentials reading invoices with them. PayPal itself is faked."""
from __future__ import annotations

import copy
from collections.abc import Iterator
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app import agent_identity, paypal_invoices, worker
from app.agent_identity import AgentRole
from app.config import get_settings
from app.main import app, current_merchant, paypal_invoice_reader
from app.seed import create_merchant
from tests.fakes import NO_PAYPAL
from tests.test_deals import order_body

INVOICE_ID = "INV2-Z56S-5LLA-Q52L-CPZ5"

# Shaped like GET /v2/invoicing/invoices/{id}; only the fields SAL reads are kept.
PAYPAL_INVOICE = {
    "id": INVOICE_ID, "status": "DRAFT",
    "detail": {"invoice_number": "INV-0091", "invoice_date": "2026-11-03", "currency_code": "USD"},
    "primary_recipients": [{"shipping_info": {"address": {"country_code": "AU", "admin_area_2": "Perth",
                                                          "postal_code": "6000"}}}],
    "items": [{"name": "BP-2217-A", "description": "Brake pad set", "quantity": "40",
               "unit_amount": {"currency_code": "USD", "value": "30.00"}}],
    "amount": {"currency_code": "USD", "value": "1200.00",
               "breakdown": {"shipping": {"amount": {"currency_code": "USD", "value": "0.00"}},
                             "tax_total": {"currency_code": "USD", "value": "0.00"}}},
}


class FakeInvoices:
    def __init__(self, invoice: dict | None = None, status: int = 200) -> None:
        self.invoice, self.status, self.calls = invoice or PAYPAL_INVOICE, status, []

    def get_invoice(self, invoice_id: str) -> dict:
        self.calls.append(invoice_id)
        if self.status != 200:
            request = httpx.Request("GET", "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/x")
            raise httpx.HTTPStatusError("PayPal", request=request, response=httpx.Response(self.status, request=request))
        return self.invoice


def test_a_paypal_invoice_reads_as_a_sal_invoice():
    invoice = paypal_invoices.to_invoice(PAYPAL_INVOICE)
    assert invoice.invoice_ref == "INV-0091" and invoice.currency == "USD" and str(invoice.total) == "1200.00"
    assert invoice.lines[0].item_code == "BP-2217-A" and str(invoice.lines[0].quantity) == "40"
    assert invoice.ship_to is not None and invoice.ship_to.city == "Perth"


def test_an_item_name_that_is_not_a_code_is_explained():
    raw = copy.deepcopy(PAYPAL_INVOICE)
    raw["items"][0]["name"] = "Brake pad set"
    with pytest.raises(paypal_invoices.PayPalInvoiceError) as caught:
        paypal_invoices.to_invoice(raw)
    assert caught.value.code == "PAYPAL_INVOICE_UNUSABLE" and "item name" in caught.value.message


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"PayPalInv-{uuid4().hex[:6]}")


@pytest.fixture
def connected(merchant, monkeypatch):
    """This business owns the PayPal credentials, as the demo business does."""
    monkeypatch.setenv("SAL_DEMO_MERCHANT_ID", str(merchant))
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "sandbox-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "sandbox-secret")
    get_settings.cache_clear()


def _api(merchant: UUID, fake: FakeInvoices) -> TestClient:
    app.dependency_overrides[current_merchant] = lambda: merchant
    app.dependency_overrides[paypal_invoice_reader] = lambda: fake
    return TestClient(app)


@pytest.fixture
def order(merchant, app_engine, monkeypatch) -> Iterator[SimpleNamespace]:
    monkeypatch.setattr("app.deals.app_engine", lambda: app_engine)
    token = agent_identity.issue(merchant, "buyer-agent:garage-01", AgentRole.BUYER_AGENT, app_engine)
    buyer = TestClient(app, headers={"authorization": f"Bearer {token}"})
    assert buyer.post("/agent/v1/deals", json=order_body()).status_code == 201
    yield SimpleNamespace(ref="PO-7781")
    app.dependency_overrides.clear()


@pytest.mark.db
def test_a_paypal_invoice_is_checked_against_the_order(connected, merchant, order, worker_engine):
    fake = FakeInvoices()
    api = _api(merchant, fake)
    sent = api.post(f"/api/deals/{order.ref}/paypal-invoice", json={"invoice_id": INVOICE_ID.lower()})
    assert sent.status_code == 200 and sent.json()["status"] == "CHECKING"
    assert fake.calls == [INVOICE_ID]
    worker.drain(worker.Context(worker_engine, NO_PAYPAL))
    assert api.get(f"/api/deals/{order.ref}").json()["status"] == "CLEAR"

    wrong = copy.deepcopy(PAYPAL_INVOICE)
    wrong["items"][0]["quantity"] = "45"
    wrong["amount"]["value"] = "1350.00"
    _api(merchant, FakeInvoices(wrong)).post(f"/api/deals/{order.ref}/paypal-invoice", json={"invoice_id": INVOICE_ID})
    worker.drain(worker.Context(worker_engine, NO_PAYPAL))
    held = api.get(f"/api/deals/{order.ref}").json()
    assert held["status"] == "HOLD"
    assert {f["code"] for f in held["findings"]} == {"QUANTITY_DIFFERS", "OVER_APPROVED_LIMIT"}


@pytest.mark.db
def test_another_business_never_reads_the_paypal_account(connected, migrated_db, monkeypatch):
    other = create_merchant(f"Other-{uuid4().hex[:6]}")
    fake = FakeInvoices()
    refused = _api(other, fake).post("/api/deals/PO-7781/paypal-invoice", json={"invoice_id": INVOICE_ID})
    app.dependency_overrides.clear()
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "PAYPAL_NOT_CONNECTED"
    assert fake.calls == []


@pytest.mark.db
@pytest.mark.parametrize("invoice_id, status, code, calls", [
    ("not-an-id", 200, "BAD_INVOICE_ID", 0),
    (INVOICE_ID, 404, "PAYPAL_INVOICE_NOT_FOUND", 1),
    (INVOICE_ID, 500, "PAYPAL_UNAVAILABLE", 1),
])
def test_refusals_before_and_from_paypal(connected, merchant, order, invoice_id, status, code, calls):
    fake = FakeInvoices(status=status)
    response = _api(merchant, fake).post(f"/api/deals/{order.ref}/paypal-invoice", json={"invoice_id": invoice_id})
    assert response.json()["detail"]["code"] == code and len(fake.calls) == calls
