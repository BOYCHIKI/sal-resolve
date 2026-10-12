"""Mapping between PayPal Disputes API v1 and SAL's internal/golden-dataset vocabulary.

Enum values are taken from the official customer-disputes v1 schema. The evidence-type choices
marked HYPOTHESIS are SAL's guesses and must be confirmed by S6 (what PayPal accepts for INR).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

REASON_TO_INTERNAL = {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "ITEM_NOT_RECEIVED"}
INTERNAL_TO_REASON = {v: k for k, v in REASON_TO_INTERNAL.items()}

PROVIDER_STATUSES = {
    "OPEN",
    "WAITING_FOR_BUYER_RESPONSE",
    "WAITING_FOR_SELLER_RESPONSE",
    "UNDER_REVIEW",
    "RESOLVED",
    "OTHER",
}
LIFECYCLE_STAGES = {"INQUIRY", "CHARGEBACK", "PRE_ARBITRATION", "ARBITRATION"}

# HYPOTHESIS — confirm in S6.
EVIDENCE_TYPE_MAP = {
    "carrier_tracking": "PROOF_OF_FULFILLMENT",
    "delivery_proof": "PROOF_OF_FULFILLMENT",
    "order_invoice": "ORDER_DETAILS",
    "payment_record": "DETAILS_OF_PURCHASE",
    "support_message": "OTHER",
}


def provider_status(value: str | None) -> str:
    """Unknown provider statuses are kept visible as OTHER rather than guessed."""
    return value if value in PROVIDER_STATUSES else "OTHER"


def to_internal(dispute: dict[str, Any]) -> dict[str, Any]:
    """Normalize a PayPal show-dispute payload into the fields the golden dataset uses."""
    amount = dispute.get("dispute_amount") or {}
    txns = dispute.get("disputed_transactions") or [{}]
    return {
        "provider_dispute_id": dispute.get("dispute_id"),
        "origin": "PAYPAL_SANDBOX",
        "reason": REASON_TO_INTERNAL.get(dispute.get("reason", ""), dispute.get("reason")),
        "provider_status": provider_status(dispute.get("status")),
        "lifecycle_stage": dispute.get("dispute_life_cycle_stage"),
        "amount": {
            "value": str(Decimal(amount["value"])) if "value" in amount else None,
            "currency": amount.get("currency_code"),
        },
        "seller_transaction_id": txns[0].get("seller_transaction_id"),
        "buyer_transaction_id": txns[0].get("buyer_transaction_id"),
        "invoice_number": txns[0].get("invoice_number"),
        "custom": txns[0].get("custom"),
        "item_types": [i.get("item_type") for i in txns[0].get("items", [])],
        "requested_evidence": requested_evidence_types(dispute),
        "allowed_response_options": dispute.get("allowed_response_options"),
        "response_deadline": dispute.get("seller_response_due_date"),
        "created_at": dispute.get("create_time"),
    }


def compare_with_golden(internal: dict[str, Any], case: dict[str, Any]) -> list[str]:
    """Return human-readable mismatches between a sandbox dispute and its golden case."""
    golden = case["dispute"]
    issues = []
    if internal["reason"] != golden["reason"]:
        issues.append(f"reason: sandbox={internal['reason']} golden={golden['reason']}")
    s_amt, g_amt = internal["amount"], golden["amount"]
    if s_amt["currency"] != g_amt["currency"]:
        issues.append(f"currency: sandbox={s_amt['currency']} golden={g_amt['currency']}")
    if s_amt["value"] is None or Decimal(s_amt["value"]) != Decimal(g_amt["value"]):
        issues.append(f"amount: sandbox={s_amt['value']} golden={g_amt['value']}")
    return issues


def evidence_payload(case: dict[str, Any], carrier_name: str = "OTHER") -> dict[str, Any]:
    """Build the provide-evidence `input` JSON for a golden case.

    The golden dataset has no carrier field yet, so tracking uses carrier OTHER with a synthetic name.
    """
    evidences = []
    for ev in case["evidence"]:
        entry: dict[str, Any] = {
            "evidence_type": EVIDENCE_TYPE_MAP.get(ev["type"], "OTHER"),
            "notes": f"SYNTHETIC {ev['type']} {ev['evidence_id']}",
        }
        tracking_id = ev.get("fields", {}).get("tracking_id")
        if ev["type"] == "carrier_tracking" and tracking_id:
            info = {"carrier_name": carrier_name, "tracking_number": tracking_id}
            if carrier_name == "OTHER":
                info["carrier_name_other"] = "SYNTHETIC_CARRIER"
            entry["evidence_info"] = {"tracking_info": [info]}
        evidences.append(entry)
    return {"evidences": evidences}


def requested_evidence_types(dispute: dict[str, Any]) -> list[str]:
    """Evidence PayPal explicitly asked the seller for — the authoritative 'mandatory' set."""
    return [e["evidence_type"] for e in dispute.get("evidences") or []
            if e.get("source") == "REQUESTED_FROM_SELLER" and e.get("evidence_type")]


def single_evidence_payload(
    case: dict[str, Any], evidence_type: str, include_tracking: bool = True, carrier_name: str = "OTHER"
) -> dict[str, Any]:
    """One evidence entry carrying every document. PayPal requires item_id per entry when more than
    one evidence is sent, and disputes on items without item_id therefore accept exactly one."""
    entry: dict[str, Any] = {
        "evidence_type": evidence_type,
        "notes": "SYNTHETIC TEST. Attached: " + ", ".join(
            f"{ev['type']} ({ev['evidence_id']})" for ev in case["evidence"]),
    }
    if include_tracking:
        tracking = [
            {"carrier_name": carrier_name, "tracking_number": ev["fields"]["tracking_id"],
             **({"carrier_name_other": "SYNTHETIC_CARRIER"} if carrier_name == "OTHER" else {})}
            for ev in case["evidence"]
            if ev["type"] == "carrier_tracking" and ev.get("fields", {}).get("tracking_id")
        ]
        if tracking:
            entry["evidence_info"] = {"tracking_info": tracking}
    return {"evidences": [entry]}
