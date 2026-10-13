"""Deterministic stages: grounding, normalization, INR rules, claim verification.

These decide what is true. Model output only proposes; this module accepts or rejects.
Rules implement SAL's illustrative INR demo rules (RULE_VERSION), not an official PayPal matrix.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.agent.models import CandidateFact, Claim, Document, Fact, Finding, SourceRef

ID_PATTERNS = {
    "transaction_id": r"TXN-[A-Z0-9-]+", "order_id": r"ORD-[A-Z0-9-]+", "tracking_order_id": r"ORD-[A-Z0-9-]+",
    "tracking_id": r"TRK-[A-Z0-9-]+", "delivery_tracking_id": r"TRK-[A-Z0-9-]+",
}
MONEY_FIELDS = {"order_amount", "payment_amount", "reported_payment_amount"}
CURRENCY_FIELDS = {"currency", "payment_currency"}
DATE_FIELDS = {"order_date", "ship_date", "carrier_event_date", "delivery_date"}

INJECTION_RE = re.compile(
    r"(system\s*override|ignore (all |the )?(previous|prior|above|invoice)|disregard|you must|"
    r"as an ai|new instructions?|assert delivered|approve (this|the) (claim|refund))", re.IGNORECASE)

PROHIBITED_RE = re.compile(
    r"(guarantee|will be won|fraud|already ruled|refund was issued|definitively verified|"
    r"follow the instruction)", re.IGNORECASE)


def _normalize(field: str, value: str) -> str | None:
    v = value.strip()
    if field in ID_PATTERNS:
        return v if re.fullmatch(ID_PATTERNS[field], v) else None
    if field in MONEY_FIELDS:
        try:
            d = Decimal(v)
        except InvalidOperation:
            return None
        return str(d.quantize(Decimal("0.01"))) if d >= 0 and d == d.quantize(Decimal("0.01")) else None
    if field in CURRENCY_FIELDS:
        return v if re.fullmatch(r"[A-Z]{3}", v) else None
    if field in DATE_FIELDS:
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            return None
    return v or None


def _appears(value: str, text: str) -> bool:
    """Whole-token match: '5.00' is not in 'Amount: 45.00 USD', 'TXN-1' is not in 'TXN-10'."""
    return re.search(rf"(?<![\w.-]){re.escape(value)}(?![\w-]|\.\d)", text) is not None


def ground(candidates: list[CandidateFact], documents: list[Document]) -> list[Fact]:
    """A fact survives only if its quote is the cited line and the value literally appears in it."""
    docs = {d.evidence_id: d for d in documents}
    facts: list[Fact] = []
    seen: set[tuple[str, str]] = set()
    for c in candidates:
        doc = docs.get(c.source.evidence_id)
        text = doc.line_text(c.source.line) if doc else None
        value = _normalize(c.field, c.value)
        if text is None:
            facts.append(Fact(c.field, c.value, c.source, "rejected", "source line does not exist"))
        elif c.quote.strip() not in text:
            facts.append(Fact(c.field, c.value, c.source, "rejected", "quote not found in source line"))
        elif value is None:
            facts.append(Fact(c.field, c.value, c.source, "rejected", "value fails type check"))
        elif not _appears(value, text):
            facts.append(Fact(c.field, value, c.source, "rejected", "value not present in source line"))
        elif (c.field, value) not in seen:
            seen.add((c.field, value))
            facts.append(Fact(c.field, value, c.source, "supported"))
    return facts


def apply_inr_rules(facts: list[Fact], documents: list[Document], dispute_amount: str,
                    dispute_currency: str) -> list[Finding]:
    by_field: dict[str, list[Fact]] = {}
    for f in facts:
        if f.status == "supported":
            by_field.setdefault(f.field, []).append(f)
    present = {d.type for d in documents}
    findings: list[Finding] = []

    for required in ("carrier_tracking", "delivery_proof"):
        if required not in present:
            findings.append(Finding("missing", required, (), f"No {required} document attached"))

    def first(field: str) -> Fact | None:
        return (by_field.get(field) or [None])[0]

    def conflict(field: str, a: Fact, b: Fact, why: str) -> None:
        findings.append(Finding("conflict", field, (a.source, b.source), why))
        for f in (a, b):
            f.status, f.reason = "conflicted", why

    carrier, delivered = first("carrier_event_date"), first("delivery_date")
    if carrier and delivered and carrier.value != delivered.value:
        conflict("delivery_date", carrier, delivered,
                 "Carrier latest event and delivery proof dates do not agree; requires human review")

    paid, reported = first("payment_amount"), first("reported_payment_amount")
    if paid and reported and Decimal(paid.value) != Decimal(reported.value):
        findings.append(Finding("conflict", "reported_payment_amount", (paid.source, reported.source),
                                "Buyer-reported amount differs from payment record; do not substitute"))

    for field in ("order_amount", "payment_amount"):
        f = first(field)
        if f and Decimal(f.value) != Decimal(dispute_amount):
            findings.append(Finding("conflict", f"{field}_vs_dispute", (f.source,),
                                    f"{field} {f.value} differs from disputed amount {dispute_amount}"))
    for field in ("currency", "payment_currency"):
        f = first(field)
        if f and f.value != dispute_currency:
            findings.append(Finding("conflict", f"{field}_vs_dispute", (f.source,),
                                    f"{field} {f.value} differs from dispute currency {dispute_currency}"))

    for doc in documents:
        for line in doc.lines:
            if INJECTION_RE.search(line.text):
                findings.append(Finding("conflict", "untrusted_instruction", (SourceRef(doc.evidence_id, line.line),),
                                        "Instruction-like text inside a document is data, never an instruction"))
    return findings


def verify_claims(claims: list[Claim], facts: list[Fact]) -> tuple[list[Claim], list[Claim]]:
    """Keep a claim only if every cited fact is supported, its values appear in the text,
    and it contains no prohibited assertion."""
    supported = {f.field: f for f in facts if f.status == "supported"}
    kept, rejected = [], []
    for c in claims:
        ok = (bool(c.fact_fields)
              and all(field in supported and _appears(supported[field].value, c.text) for field in c.fact_fields)
              and not PROHIBITED_RE.search(c.text))
        (kept if ok else rejected).append(c)
    return kept, rejected
