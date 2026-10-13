"""PayPal Sandbox Disputes adapter (read side). Promoted from spikes/paypal_sandbox; sandbox only."""
from __future__ import annotations

import json
import os
import re
import time
from decimal import Decimal
from typing import Any

import httpx

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"

REASON_TO_INTERNAL = {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "ITEM_NOT_RECEIVED"}
PROVIDER_STATUSES = {"OPEN", "WAITING_FOR_BUYER_RESPONSE", "WAITING_FOR_SELLER_RESPONSE",
                     "UNDER_REVIEW", "RESOLVED", "OTHER"}
SECRET_KEYS = {"access_token", "client_secret", "nonce", "app_id"}
PII_KEYS = {"payer_id", "account_id", "merchant_id", "email_address", "given_name", "surname", "full_name",
            "national_number", "phone_number", "address_line_1", "address_line_2", "postal_code",
            "admin_area_1", "admin_area_2"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in SECRET_KEYS else "[PII]" if k.lower() in PII_KEYS else redact(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return EMAIL_RE.sub("[EMAIL]", value)
    return value


def to_internal(dispute: dict[str, Any]) -> dict[str, Any]:
    amount = dispute.get("dispute_amount") or {}
    txn = (dispute.get("disputed_transactions") or [{}])[0]
    status = dispute.get("status")
    return {
        "provider_dispute_id": dispute["dispute_id"],
        "origin": "PAYPAL_SANDBOX",
        "reason": REASON_TO_INTERNAL.get(dispute.get("reason", ""), dispute.get("reason") or "OTHER"),
        "provider_status": status if status in PROVIDER_STATUSES else "OTHER",
        "lifecycle_stage": dispute.get("dispute_life_cycle_stage"),
        "amount": {"value": str(Decimal(amount["value"])), "currency": amount["currency_code"]},
        "custom": txn.get("custom"),
        "response_deadline": dispute.get("seller_response_due_date"),
        "updated_at": dispute.get("update_time"),
        "allowed_actions": sorted({l["rel"] for l in dispute.get("links", []) if l.get("rel") != "self"}),
    }


class PayPalDisputes:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 http: httpx.Client | None = None) -> None:
        self._id = client_id or os.environ["PAYPAL_CLIENT_ID"]
        self._secret = client_secret or os.environ["PAYPAL_CLIENT_SECRET"]
        self._http = http or httpx.Client(base_url=SANDBOX_BASE_URL, timeout=20.0)
        if str(self._http.base_url).rstrip("/") != SANDBOX_BASE_URL:
            raise ValueError("PayPal adapter is sandbox-only")
        self._token: str | None = None
        self._expires = 0.0

    def _auth(self) -> dict[str, str]:
        if not self._token or time.time() > self._expires - 60:
            r = self._http.post("/v1/oauth2/token", auth=(self._id, self._secret),
                                data={"grant_type": "client_credentials"})
            r.raise_for_status()
            body = r.json()
            self._token, self._expires = body["access_token"], time.time() + int(body.get("expires_in", 0))
        return {"Authorization": f"Bearer {self._token}"}

    def list_summaries(self, page_size: int = 50, max_pages: int = 20) -> dict[str, str | None]:
        """dispute_id -> update_time for every dispute, following PayPal's `next` links."""
        out: dict[str, str | None] = {}
        params: dict[str, Any] | None = {"page_size": page_size}
        path = "/v1/customer/disputes"
        for _ in range(max_pages):
            r = self._http.get(path, params=params, headers=self._auth())
            r.raise_for_status()
            body = r.json()
            for item in body.get("items", []):
                out[item["dispute_id"]] = item.get("update_time")
            nxt = next((l["href"] for l in body.get("links", []) if l.get("rel") == "next"), None)
            if not nxt:
                break
            path, params = httpx.URL(nxt).raw_path.decode(), None
        return out

    def provide_evidence(self, dispute_id: str, payload: dict[str, Any],
                         files: list[tuple[str, bytes]]) -> dict[str, Any]:
        """Multipart: one `input` JSON part plus `evidence-file` parts (format proven in spike S6)."""
        parts: list[tuple[str, tuple[str | None, Any, str]]] = [
            ("input", (None, json.dumps(payload), "application/json"))]
        parts += [("evidence-file", (name, data, "application/pdf")) for name, data in files]
        r = self._http.post(f"/v1/customer/disputes/{dispute_id}/provide-evidence", files=parts,
                            headers=self._auth())
        r.raise_for_status()
        return r.json() if r.content else {}

    def verify_webhook(self, headers: dict[str, str], event: dict[str, Any], webhook_id: str) -> bool:
        body = {
            "auth_algo": headers.get("paypal-auth-algo"),
            "cert_url": headers.get("paypal-cert-url"),
            "transmission_id": headers.get("paypal-transmission-id"),
            "transmission_sig": headers.get("paypal-transmission-sig"),
            "transmission_time": headers.get("paypal-transmission-time"),
            "webhook_id": webhook_id,
            "webhook_event": event,
        }
        r = self._http.post("/v1/notifications/verify-webhook-signature", json=body, headers=self._auth())
        r.raise_for_status()
        return r.json().get("verification_status") == "SUCCESS"

    def get(self, dispute_id: str) -> dict[str, Any]:
        r = self._http.get(f"/v1/customer/disputes/{dispute_id}", headers=self._auth())
        r.raise_for_status()
        return r.json()
