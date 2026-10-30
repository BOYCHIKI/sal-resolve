"""The three model-backed roles, as provider-neutral protocols, plus deterministic baselines.

An LLM adapter (any provider) implements these protocols. The baselines need no model: they give
the evaluation harness a floor that an LLM must beat, and make the pipeline testable offline.
"""
from __future__ import annotations

import re
from typing import Any, Protocol

from app.agent.models import CandidateFact, Claim, Document, Fact, Finding, SourceRef
from app.agent.tools import ToolSpec
from app.agent.validation import CURRENCY_CODES, _status_phrase, amounts_in, dates_in


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
        # SAL's own rendering of PayPal's transaction record (app/paypal_evidence.py): exact, so always read.
        ("transaction_id", r"^Transaction ID: ([A-Z0-9]{17})$", "{0}"),
        ("payment_amount", r"^Amount: (\d+\.\d{2}) ([A-Z]{3})$", "{0}"),
        ("payment_currency", r"^Amount: (\d+\.\d{2}) ([A-Z]{3})$", "{1}"),
        ("ship_to_city", r"^Ship-to city: (.{2,40})$", "{0}"),
        ("ship_to_postal_code", r"^Ship-to postal code: ([A-Za-z0-9 -]{3,12})$", "{0}"),
    ],
    "carrier_tracking": [
        ("tracking_id", r"^SYNTHETIC TRACKING \| (TRK-[A-Z0-9-]+)$", "{0}"),
        ("tracking_order_id", r"^Order reference: (ORD-[A-Z0-9-]+)$", "{0}"),
        ("ship_date", r"^Ship date: (\d{4}-\d{2}-\d{2})$", "{0}"),
        ("carrier_status", r"^Carrier status: ([A-Z_]+)$", "{0}"),
        ("carrier_event_date", r"^Latest event: (\d{4}-\d{2}-\d{2})$", "{0}"),
        ("delivery_city", r"^Delivered to city: (.{2,40})$", "{0}"),
        ("delivery_postal_code", r"^Delivered to postal code: ([A-Za-z0-9 -]{3,12})$", "{0}"),
    ],
    "delivery_proof": [
        ("delivery_tracking_id", r"^SYNTHETIC DELIVERY CONFIRMATION \| (TRK-[A-Z0-9-]+)$", "{0}"),
        ("delivery_status", r"^Delivery status: ([A-Z_]+)$", "{0}"),
        ("delivery_date", r"^Delivery date: (\d{4}-\d{2}-\d{2})$", "{0}"),
        ("delivery_city", r"^Delivered to city: (.{2,40})$", "{0}"),
        ("delivery_postal_code", r"^Delivered to postal code: ([A-Za-z0-9 -]{3,12})$", "{0}"),
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
    "order_amount": "The customer paid {v} {currency} for this order.",
    "order_id": "The order number is {v}.",
    "transaction_id": "PayPal transaction {v} is the payment for this order.",
    "tracking_id": "We shipped the order with tracking number {v}.",
    "carrier_status": "The courier marked the parcel as {v}.",
    "delivery_date": "The delivery receipt is dated {v}.",
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


# Labels real invoices, PayPal records and courier pages use (English, Indonesian, Filipino sellers).
_ID = r"(?=[A-Za-z0-9/-]*\d)[A-Za-z0-9][A-Za-z0-9/-]{3,39}"
_ORDER_LABEL = re.compile(r"\b(?:invoice(?:\s*no\.?)?|no\.?\s*pesanan|order(?:\s*no\.?)?|or\s*no\.?|nota|"
                          rf"receipt\s*no\.?)\s*[:#]?\s*(?P<id>{_ID})", re.I)
_TRACKING_LABEL = re.compile(r"\b(?:no\.?\s*resi|resi|tracking(?:\s*(?:no\.?|number))?|waybill(?:\s*no\.?)?|"
                             rf"nomor\s*kiriman|awb)\s*[:#]?\s*(?P<id>{_ID})", re.I)
_PAYPAL_TXN = re.compile(r"\b(?:transaction|transaksi)\b[^A-Z0-9]*(?P<id>[A-Z0-9]{17})\b", re.I)
_TOTAL = re.compile(r"(?<!sub)(?<!item )\btotal\b", re.I)
_PAYMENT = re.compile(r"\b(received|payment|amount|money)\b", re.I)
_ORDER_DATE = re.compile(r"\b(tanggal|tgl|date|ordered|issued)\b", re.I)
_SHIP_DATE = re.compile(r"\b(ship date|shipped|tanggal kirim|tgl kirim|posting|picked up|accepted)\b", re.I)
_DELIVERY_DATE = re.compile(r"\b(delivered|diterima)\b", re.I)
_STATUS_LINE = re.compile(r"^\s*status\s*:\s*(?P<v>.+)$", re.I)
# Where the courier delivered, as couriers label it ("ZIP: 94107", "Kode pos: 40115", "Kota: Bandung").
_POSTAL_LABEL = re.compile(r"\b(?:postal\s*code|post\s*code|postcode|zip(?:\s*code)?|kode\s*pos)\s*[:#]?\s*"
                           r"(?P<v>[A-Za-z0-9][A-Za-z0-9 -]{1,8}[A-Za-z0-9])\s*$", re.I)
_SHIP_TO = re.compile(r"^\s*ship-to (?P<k>city|postal code)\s*:\s*(?P<v>.+?)\s*$", re.I)
_CITY_LABEL = re.compile(r"^\s*(?:city|kota|kabupaten|town)\s*:\s*(?P<v>[^\d,:]{2,40}?)\s*$", re.I)
_CODE = re.compile(r"\b(" + "|".join(CURRENCY_CODES) + r")\b")


class LabelExtractor:
    """Deterministic reader for labelled lines in real documents ("No. Resi: ...", "Total: USD 60.00",
    "Transaction ID ..."). It gives the model a stable floor: what is plainly labelled is read the same way every
    run. Values are only proposed; grounding checks them like any other candidate."""

    def extract(self, documents):
        out: list[CandidateFact] = []
        for doc in documents:
            found: dict[str, tuple[str, Any]] = {}
            for line in doc.lines:
                for field, value in self._read(doc.type, line.text):
                    found.setdefault(field, (value, line))
            out += [CandidateFact(f, v, SourceRef(doc.evidence_id, ln.line), ln.text) for f, (v, ln) in found.items()]
        return out

    @staticmethod
    def _one(values: set) -> Any:
        return next(iter(values)) if len(values) == 1 else None

    def _read(self, doc_type: str, text: str) -> list[tuple[str, str]]:
        got: list[tuple[str, str]] = []
        txn = _PAYPAL_TXN.search(text)
        if txn and doc_type in ("order_invoice", "payment_record"):
            got.append(("transaction_id", txn.group("id")))
        amount = self._one(amounts_in(text))
        code = _CODE.search(text)
        currency = code.group(1) if code else ("IDR" if re.search(r"\bRp\b", text) else None)
        one_date = self._one(dates_in(text))
        if doc_type == "order_invoice":
            order = _ORDER_LABEL.search(text)
            if order:
                got.append(("order_id", order.group("id")))
            if _TOTAL.search(text) and amount is not None:
                got.append(("order_amount", f"{amount:.2f}"))
                if currency:
                    got.append(("currency", currency))
            if _ORDER_DATE.search(text) and one_date:
                got.append(("order_date", one_date))
        elif doc_type == "payment_record":
            ship_to = _SHIP_TO.match(text)
            if ship_to:  # SAL's own rendering of PayPal's address: exact, so always read
                got.append((f"ship_to_{ship_to.group('k').lower().replace(' ', '_')}", ship_to.group("v")))
            elif _PAYMENT.search(text) and amount is not None and code:
                got += [("payment_amount", f"{amount:.2f}"), ("payment_currency", code.group(1))]
        elif doc_type == "seller_shipment":
            tracking = _TRACKING_LABEL.search(text)
            if tracking:
                got.append(("tracking_id", tracking.group("id")))
        elif doc_type in ("carrier_tracking", "delivery_proof"):
            tracking = _TRACKING_LABEL.search(text)
            if tracking:
                got.append(("tracking_id" if doc_type == "carrier_tracking" else "delivery_tracking_id",
                            tracking.group("id")))
            postal, city = _POSTAL_LABEL.search(text), _CITY_LABEL.match(text)
            if postal:
                got.append(("delivery_postal_code", postal.group("v")))
            if city:
                got.append(("delivery_city", city.group("v")))
            if doc_type == "carrier_tracking":
                status = _STATUS_LINE.match(text)
                if status and _status_phrase(status.group("v")):
                    got.append(("carrier_status", status.group("v").strip()))
                if _SHIP_DATE.search(text) and one_date:
                    got.append(("ship_date", one_date))
                # "Delivered on 3 September 2026", "Diterima oleh: K. TANAKA - 9 Okt 2026": the delivery event.
                # Read every time, so a disagreeing proof-of-delivery date never depends on the model noticing it.
                if _status_phrase(text) == "DELIVERED" and one_date:
                    got.append(("carrier_event_date", one_date))
            elif _DELIVERY_DATE.search(text) and one_date:
                got.append(("delivery_date", one_date))
        return got


class UnionExtractor:
    """Candidates from several extractors, first ones first. Rules read known layouts exactly every time;
    the model covers everything else. Grounding treats all candidates the same, and when two disagree on a
    field the first extractor's fact is the one the rules use."""

    def __init__(self, *extractors: Extractor) -> None:
        self.extractors = extractors

    def extract(self, documents):
        return [c for e in self.extractors for c in e.extract(documents)]
