"""The three model-backed roles, as provider-neutral protocols, plus deterministic baselines.

An LLM adapter (any provider) implements these protocols. The baselines need no model: they give
the evaluation harness a floor that an LLM must beat, and make the pipeline testable offline.
"""
from __future__ import annotations

import re
from typing import Any, Protocol

from app.agent.models import CandidateFact, Claim, Document, Fact, Finding, SourceRef
from app.agent.tools import ToolSpec


class Planner(Protocol):
    """Gather stage: given the transcript so far, request one tool call or stop (return None)."""
    def next_call(self, tools: tuple[ToolSpec, ...], transcript: list[dict[str, Any]]) -> dict[str, Any] | None: ...


class Extractor(Protocol):
    """Extract candidate facts with an exact quote and source line from the documents it was given."""
    def extract(self, documents: list[Document]) -> list[CandidateFact]: ...


class Drafter(Protocol):
    """Write claims using only validated facts; each claim names the facts it relies on."""
    def draft(self, facts: list[Fact], findings: list[Finding]) -> list[Claim]: ...


# ---------------------------------------------------------------- baselines
class ReadAllPlanner:
    """List the evidence, then read each document once."""

    def next_call(self, tools, transcript):
        listed = next((t["result"] for t in transcript if t["tool"] == "list_evidence"), None)
        if listed is None:
            return {"tool": "list_evidence", "args": {}}
        read = {t["args"].get("evidence_id") for t in transcript if t["tool"] == "read_evidence"}
        for doc in listed.get("documents", []):
            if doc["evidence_id"] not in read:
                return {"tool": "read_evidence", "args": {"evidence_id": doc["evidence_id"]}}
        return None


# label in the document text -> (fact field, value pattern); applied per document type
_PATTERNS: dict[str, list[tuple[str, str, str]]] = {
    "order_invoice": [
        ("order_id", r"^SYNTHETIC INVOICE \| (ORD-[A-Z0-9-]+)$", "{0}"),
        ("transaction_id", r"^Transaction: (TXN-[A-Z0-9-]+)$", "{0}"),
        ("order_amount", r"^Amount: (\d+\.\d{2}) ([A-Z]{3})$", "{0}"),
        ("currency", r"^Amount: (\d+\.\d{2}) ([A-Z]{3})$", "{1}"),
        ("order_date", r"^Order date: (\d{4}-\d{2}-\d{2})$", "{0}"),
    ],
    "payment_record": [
        ("transaction_id", r"^SYNTHETIC PAYMENT RECORD \| (TXN-[A-Z0-9-]+)$", "{0}"),
        ("payment_amount", r"^Settled amount: (\d+\.\d{2}) ([A-Z]{3})$", "{0}"),
        ("payment_currency", r"^Settled amount: (\d+\.\d{2}) ([A-Z]{3})$", "{1}"),
        ("order_id", r"^Order reference: (ORD-[A-Z0-9-]+)$", "{0}"),
    ],
    "carrier_tracking": [
        ("tracking_id", r"^SYNTHETIC TRACKING \| (TRK-[A-Z0-9-]+)$", "{0}"),
        ("tracking_order_id", r"^Order reference: (ORD-[A-Z0-9-]+)$", "{0}"),
        ("ship_date", r"^Ship date: (\d{4}-\d{2}-\d{2})$", "{0}"),
        ("carrier_status", r"^Carrier status: ([A-Z_]+)$", "{0}"),
        ("carrier_event_date", r"^Latest event: (\d{4}-\d{2}-\d{2})$", "{0}"),
    ],
    "delivery_proof": [
        ("delivery_tracking_id", r"^SYNTHETIC DELIVERY CONFIRMATION \| (TRK-[A-Z0-9-]+)$", "{0}"),
        ("delivery_status", r"^Delivery status: ([A-Z_]+)$", "{0}"),
        ("delivery_date", r"^Delivery date: (\d{4}-\d{2}-\d{2})$", "{0}"),
    ],
    "support_message": [
        ("reported_payment_amount", r"^Buyer-reported amount: (\d+\.\d{2}) ([A-Z]{3})$", "{0}"),
    ],
}


class RuleExtractor:
    """Regex baseline over document *text* (never the typed `fields`, which the model would not see)."""

    def extract(self, documents):
        out: list[CandidateFact] = []
        for doc in documents:
            for field, pattern, template in _PATTERNS.get(doc.type, []):
                for line in doc.lines:
                    m = re.match(pattern, line.text.strip())
                    if m:
                        out.append(CandidateFact(field, template.format(*m.groups()),
                                                 SourceRef(doc.evidence_id, line.line), line.text))
                        break
        return out


_CLAIM_TEMPLATES = {
    "transaction_id": "The payment record references transaction {v}.",
    "order_id": "The order on file is {v}.",
    "order_amount": "The invoice amount is {v} {currency}.",
    "tracking_id": "The shipment was tracked under {v}.",
    "carrier_status": "The carrier reported the status {v}.",
    "delivery_date": "The delivery confirmation is dated {v}.",
}


class TemplateDrafter:
    """One plain claim per supported fact; conflicted facts are never asserted."""

    def draft(self, facts, findings):
        supported = {f.field: f for f in facts if f.status == "supported"}
        currency = supported.get("currency").value if "currency" in supported else ""
        claims = []
        for field, template in _CLAIM_TEMPLATES.items():
            if field in supported:
                claims.append(Claim(template.format(v=supported[field].value, currency=currency).replace("  ", " "),
                                    (field,) if field != "order_amount" else ("order_amount", "currency")))
        return claims
