"""Deal Check on a PayPal invoice: read the seller's invoice from the PayPal Invoicing API (Sandbox) and check it
against the buyer's order before the seller sends it.

The PayPal credentials belong to one business, so only that business may read invoices with them; anyone else would
read another business's PayPal account. The invoice then goes through the same check as an uploaded one.
"""
from __future__ import annotations

import re
from typing import Any, Protocol
from uuid import UUID

import httpx
from pydantic import ValidationError
from sqlalchemy import Engine

from app import deals
from app.config import get_settings
from app.db import app_engine, tenant_session

INVOICE_ID = re.compile(r"^INV2(-[A-Z0-9]{4}){4}$")   # PayPal's format, e.g. INV2-Z56S-5LLA-Q52L-CPZ5


class InvoiceReader(Protocol):
    def get_invoice(self, invoice_id: str) -> dict[str, Any]: ...


class PayPalInvoiceError(Exception):
    def __init__(self, code: str, status: int, message: str = "") -> None:
        super().__init__(code)
        self.code, self.status, self.message = code, status, message


def connected(merchant_id: UUID) -> bool:
    """Whether this business owns the PayPal credentials SAL holds."""
    cfg = get_settings()
    return bool(cfg.paypal_client_id and cfg.paypal_client_secret) and merchant_id == cfg.demo_merchant_id


def _value(money: dict[str, Any] | None, default: str = "0") -> str:
    return str((money or {}).get("value") or default)


def to_invoice(raw: dict[str, Any]) -> deals.Invoice:
    """PayPal's invoice in SAL's terms. Each line's item name must be its item code (e.g. FLT-V60-100), because
    Deal Check matches lines by code; a PayPal invoice has no separate code field."""
    detail = raw.get("detail") or {}
    amount = raw.get("amount") or {}
    breakdown = amount.get("breakdown") or {}
    address = (((raw.get("primary_recipients") or [{}])[0].get("shipping_info") or {}).get("address") or {})
    payment = ((raw.get("payments") or {}).get("transactions") or [{}])[0].get("payment_id")
    body: dict[str, Any] = {
        "invoice_ref": detail.get("invoice_number"),
        "issued_at": f"{detail.get('invoice_date')}T00:00:00Z" if detail.get("invoice_date") else None,
        "currency": detail.get("currency_code") or amount.get("currency_code"),
        "total": _value(amount, ""),
        "shipping": _value((breakdown.get("shipping") or {}).get("amount")),
        "tax": _value(breakdown.get("tax_total")),
        "ship_to": {"country": address["country_code"], "city": address.get("admin_area_2") or "",
                    "postal_code": address.get("postal_code")} if address.get("country_code") else None,
        "lines": [{"item_code": (item.get("name") or "").strip(),
                   "description": (item.get("description") or item.get("name") or "").strip()[:200],
                   "quantity": str(item.get("quantity") or ""),
                   "unit_price": _value(item.get("unit_amount"), "")}
                  for item in raw.get("items") or []],
        "paypal_transaction_id": payment if payment and re.fullmatch(r"[A-Z0-9]{17}", payment) else None,
    }
    try:
        return deals.Invoice.model_validate(body)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        hint = " Put each line's item code in its PayPal item name." if "item_code" in where else ""
        raise PayPalInvoiceError("PAYPAL_INVOICE_UNUSABLE", 422, f"{where}: {first['msg']}.{hint}") from exc


def import_invoice(merchant_id: UUID, deal_ref: str, invoice_id: str, actor: str, paypal: InvoiceReader,
                   engine: Engine | None = None) -> dict[str, Any]:
    """Read the invoice from PayPal and record it on the deal; the worker then checks it like any invoice."""
    if not connected(merchant_id):
        raise PayPalInvoiceError("PAYPAL_NOT_CONNECTED", 409)
    invoice_id = invoice_id.strip().upper()
    if not INVOICE_ID.fullmatch(invoice_id):
        raise PayPalInvoiceError("BAD_INVOICE_ID", 422, "A PayPal invoice ID looks like INV2-XXXX-XXXX-XXXX-XXXX.")
    try:
        raw = paypal.get_invoice(invoice_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise PayPalInvoiceError("PAYPAL_INVOICE_NOT_FOUND", 404) from exc
        raise PayPalInvoiceError("PAYPAL_UNAVAILABLE", 502) from exc
    except httpx.HTTPError as exc:
        raise PayPalInvoiceError("PAYPAL_UNAVAILABLE", 502) from exc
    if raw.get("status") == "CANCELLED":
        raise PayPalInvoiceError("PAYPAL_INVOICE_UNUSABLE", 422, "This PayPal invoice was cancelled.")
    invoice = to_invoice(raw)
    with tenant_session(merchant_id, engine or app_engine()) as s:
        deals.record_invoice(s, merchant_id, deal_ref, invoice, actor)
    return deals.get_deal(merchant_id, deal_ref, engine)
