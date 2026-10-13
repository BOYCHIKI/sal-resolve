"""Offline tests (no database, no network)."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.db import tenant_session
from app.main import money_str
from app.paypal import redact, to_internal

RAW = {
    "dispute_id": "PP-R-RVX-10191107",
    "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    "status": "WAITING_FOR_SELLER_RESPONSE",
    "dispute_life_cycle_stage": "INQUIRY",
    "dispute_amount": {"currency_code": "USD", "value": "45.00"},
    "disputed_transactions": [{"custom": "SAL-INR-001", "buyer": {"name": "John Doe"}}],
    "seller_response_due_date": "2026-11-01T10:57:04.162Z",
    "links": [{"rel": "self"}, {"rel": "provide_evidence"}, {"rel": "accept_claim"}],
}


def test_to_internal_maps_recorded_sandbox_payload():
    d = to_internal(RAW)
    assert d["reason"] == "ITEM_NOT_RECEIVED"
    assert d["amount"] == {"value": "45.00", "currency": "USD"}
    assert d["custom"] == "SAL-INR-001"
    assert d["allowed_actions"] == ["accept_claim", "provide_evidence"]


def test_unknown_status_becomes_other():
    assert to_internal(dict(RAW, status="NEW_THING"))["provider_status"] == "OTHER"


def test_redact_strips_pii():
    out = redact({"payer_id": "X", "note": "a@b.com", "access_token": "t"})
    assert out == {"payer_id": "[PII]", "note": "[EMAIL]", "access_token": "[REDACTED]"}


@pytest.mark.parametrize("amount,currency,expected", [
    (Decimal("45.0000"), "USD", "45.00"),
    (Decimal("0.1000"), "GBP", "0.10"),
    (Decimal("1500.0000"), "JPY", "1500"),
    (Decimal("1.2345"), "USD", "1.2345"),  # never silently rounded
])
def test_money_str(amount, currency, expected):
    assert money_str(amount, currency) == expected


def test_tenant_session_rejects_non_uuid():
    with pytest.raises(TypeError):
        with tenant_session("aaaaaaaa-0000-4000-8000-000000000001"):  # type: ignore[arg-type]
            pass
    assert isinstance(UUID("aaaaaaaa-0000-4000-8000-000000000001"), UUID)
