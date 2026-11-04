"""HTTP layer: identity comes from the server, and tenant isolation holds through the API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import repositories as repo
from app.db import tenant_session
from app.main import app, current_merchant

pytestmark = pytest.mark.db

client = TestClient(app)


@pytest.fixture
def as_tenant(tenants):
    def _use(name: str):
        app.dependency_overrides[current_merchant] = lambda: tenants[name]
    yield _use
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def api_seed(tenants, app_engine):
    ids = {}
    for name in ("a", "b"):
        with tenant_session(tenants[name], app_engine) as s:
            row, _ = repo.upsert_provider_dispute(s, tenants[name], {
                "origin": "PAYPAL_SANDBOX", "provider_dispute_id": f"PP-API-{name}", "reason": "ITEM_NOT_RECEIVED",
                "amount": {"value": "45.00", "currency": "USD"}, "provider_status": "OPEN"}, {})
            ids[name] = str(row.id)
    return ids


def test_list_returns_only_own_tenant(as_tenant, api_seed):
    as_tenant("a")
    body = client.get("/api/disputes").json()
    pids = {d["provider_dispute_id"] for d in body["items"]}
    assert "PP-API-a" in pids and "PP-API-b" not in pids
    assert next(d for d in body["items"] if d["provider_dispute_id"] == "PP-API-a")["amount"] == {
        "value": "45.00", "currency": "USD"}


def test_other_tenants_dispute_is_404(as_tenant, api_seed):
    as_tenant("a")
    assert client.get(f"/api/disputes/{api_seed['b']}").status_code == 404
    assert client.get(f"/api/disputes/{api_seed['a']}").status_code == 200


def test_merchant_cannot_be_chosen_by_client(as_tenant, api_seed, tenants):
    as_tenant("a")
    r = client.get("/api/disputes", headers={"X-Merchant-Id": str(tenants["b"])},
                   params={"merchant_id": str(tenants["b"])})
    assert "PP-API-b" not in {d["provider_dispute_id"] for d in r.json()["items"]}


def test_without_a_session_business_routes_are_401_even_with_a_demo_merchant():
    # The demo merchant no longer stands in for a signed-in seller (ADR-009).
    app.dependency_overrides.clear()
    assert client.get("/api/disputes").status_code == 401


@pytest.mark.parametrize("marked, shown", [(True, True), (False, False), (None, None)])
def test_seller_protection_is_what_paypal_marked_on_the_payment(as_tenant, tenants, app_engine, marked, shown):
    payload = {} if marked is None else {"disputed_transactions": [{"seller_protection_eligible": marked}]}
    with tenant_session(tenants["a"], app_engine) as s:
        row, _ = repo.upsert_provider_dispute(s, tenants["a"], {
            "origin": "PAYPAL_SANDBOX", "provider_dispute_id": f"PP-PROT-{marked}", "reason": "ITEM_NOT_RECEIVED",
            "amount": {"value": "45.00", "currency": "USD"}, "provider_status": "OPEN"}, payload)
    as_tenant("a")
    assert client.get(f"/api/disputes/{row.id}").json()["seller_protection_eligible"] is shown