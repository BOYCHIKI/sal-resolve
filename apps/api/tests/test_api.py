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


def test_no_identity_configured_is_503(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "get_settings", lambda: type("S", (), {"demo_merchant_id": None, "internal_token": None})())
    app.dependency_overrides.clear()
    assert client.get("/api/disputes").status_code == 503
