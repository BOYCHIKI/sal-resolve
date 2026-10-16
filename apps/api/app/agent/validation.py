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


STATUS_FIELDS = {"carrier_status", "delivery_status"}
# Real documents use their own references (#100245, 1Z999AA10123456784, 2X920845424009805): letters, digits
# and dashes with at least one digit. The golden TXN-/ORD-/TRK- ids are a subset.
GENERIC_ID = r"(?=[A-Za-z0-9-]*\d)[A-Za-z0-9][A-Za-z0-9-]{3,39}"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
# Only unambiguous formats. 08/07/2026 could be 8 July or 7 August, so numeric day/month dates never count.
_DATE_FORMS = [
    (re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"), ("y", "m", "d")),
    (re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I), ("mon", "d", "y")),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH},?\s+(\d{{4}})\b", re.I), ("d", "mon", "y")),
]
_AMOUNT = re.compile(r"(?<![\w.,-])(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?(?![\w-]|[.,]\d)")
# Symbols and ISO codes only. "QTY 2 PCS" or "ORD 45" must not turn a bare number into money.
CURRENCY_CODES = ("USD", "EUR", "GBP", "AUD", "CAD", "JPY", "SGD", "IDR", "MYR", "THB", "PHP", "HKD", "CHF",
                  "CNY", "INR", "NZD", "SEK", "NOK", "DKK", "PLN", "MXN", "BRL")
_CURRENCY_MARK = re.compile(r"[$€£¥]|\b(?:" + "|".join(CURRENCY_CODES) + r")\b")


def dates_in(text: str) -> set[str]:
    """ISO dates written in a line in any unambiguous format."""
    found: set[str] = set()
    for pattern, order in _DATE_FORMS:
        for m in pattern.finditer(text):
            parts = dict(zip(order, m.groups()))
            month = MONTHS[parts["mon"][:3].lower()] if "mon" in parts else int(parts["m"])
            try:
                found.add(date(int(parts["y"]), month, int(parts["d"])).isoformat())
            except ValueError:
                pass
    return found


def amounts_in(text: str) -> set[Decimal]:
    """Money amounts in a line: with cents (45.00, 1,045.50) or next to a currency mark ($45, 45 USD)."""
    found: set[Decimal] = set()
    for m in _AMOUNT.finditer(text):
        near = text[max(0, m.start() - 4):m.end() + 4]
        if m.group(2) or _CURRENCY_MARK.search(near):
            found.add(Decimal(m.group(1).replace(",", "") + (m.group(2) or "")))
    return found


def value_in_line(field: str, value: str, text: str) -> bool:
    """Is this normalized value really written in the line? Literal match, or the same date, amount or
    status in another common format. Nothing is inferred: the thing itself must be on the line."""
    if _appears(value, text):
        return True
    if field in DATE_FIELDS:
        return value in dates_in(text)
    if field in MONEY_FIELDS:
        return Decimal(value) in amounts_in(text)
    if field in STATUS_FIELDS:
        return re.search(rf"(?<!\w){re.escape(value.replace('_', ' '))}(?!\w)", text.replace("_", " "), re.I) is not None
    return False


def _normalize(field: str, value: str) -> str | None:
    v = value.strip()
    if field in ID_PATTERNS:
        return v if re.fullmatch(ID_PATTERNS[field], v) or re.fullmatch(GENERIC_ID, v) else None
    if field in STATUS_FIELDS:
        # Carriers add detail ("Delivered, In/At Mailbox"); keep the status itself when it leads the text.
        lead = re.match(r"\s*(out for delivery|in transit|delivered|returned|exception|shipped)\b", v, re.I)
        if lead:
            return re.sub(r"\s+", "_", lead.group(1).upper())
        return re.sub(r"[\s-]+", "_", v.upper()) if re.fullmatch(r"[A-Za-z][A-Za-z _-]{1,30}", v) else None
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
    """A fact survives only if its quote is the cited line and the value is written in it (literally, or the
    same date/amount/status in another common format)."""
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
        elif not value_in_line(c.field, value, text):
            facts.append(Fact(c.field, value, c.source, "rejected", "value not present in source line"))
        elif (c.field, value) not in seen:
            seen.add((c.field, value))
            facts.append(Fact(c.field, value, c.source, "supported"))
    return facts


def apply_inr_rules(facts: list[Fact], documents: list[Document], dispute_amount: str,
                    dispute_currency: str, inr: bool = True) -> list[Finding]:
    """Generic checks for every dispute (one field/two values, amounts, currencies, hidden instructions);
    the Item-Not-Received checks (courier documents, delivery dates) only when inr is True."""
    findings: list[Finding] = []
    # One field, two different values (e.g. a subtotal and a total both proposed as order_amount): SAL never
    # picks one silently. Every value becomes conflicted and the operator decides.
    values: dict[str, list[Fact]] = {}
    for f in facts:
        if f.status == "supported":
            values.setdefault(f.field, []).append(f)
    for field, group in values.items():
        if len({f.value for f in group}) > 1:
            why = "Documents give different values for this; requires human review"
            findings.append(Finding("conflict", field, tuple(f.source for f in group), why))
            for f in group:
                f.status, f.reason = "conflicted", why

    by_field: dict[str, list[Fact]] = {}
    for f in facts:
        if f.status == "supported":
            by_field.setdefault(f.field, []).append(f)
    present = {d.type for d in documents}

    for required in ("carrier_tracking", "delivery_proof") if inr else ():
        if required not in present:
            findings.append(Finding("missing", required, (), f"No {required} document attached"))

    def first(field: str) -> Fact | None:
        return (by_field.get(field) or [None])[0]

    def conflict(field: str, a: Fact, b: Fact, why: str) -> None:
        findings.append(Finding("conflict", field, (a.source, b.source), why))
        for f in (a, b):
            f.status, f.reason = "conflicted", why

    carrier, delivered = first("carrier_event_date"), first("delivery_date")
    if inr and carrier and delivered and carrier.value != delivered.value:
        conflict("delivery_date", carrier, delivered,
                 "Carrier latest event and delivery proof dates do not agree; requires human review")

    paid, reported = first("payment_amount"), first("reported_payment_amount")
    if paid and reported and Decimal(paid.value) != Decimal(reported.value):
        findings.append(Finding("conflict", "reported_payment_amount", (paid.source, reported.source),
                                "Buyer-reported amount differs from payment record; do not substitute"))
        # Only the buyer's figure is in doubt; the settled payment record stays supported.
        reported.status, reported.reason = "conflicted", "buyer-reported amount differs from payment record"

    # A buyer may dispute part of a payment (one item of two), so a larger order or payment is normal.
    # Only an amount BELOW the disputed amount cannot be right.
    for field in ("order_amount", "payment_amount"):
        f = first(field)
        if f and Decimal(f.value) < Decimal(dispute_amount):
            findings.append(Finding("conflict", f"{field}_vs_dispute", (f.source,),
                                    f"{field} {f.value} is less than the disputed amount {dispute_amount}"))
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


MAX_CLAIM_CHARS = 300
# A reply sentence goes to PayPal verbatim. It may state facts; it may not carry links, addresses, markup,
# control characters or instruction-like text that a document (or a model) tried to slip in.
UNSAFE_CLAIM_RE = re.compile(r"(https?://|www\.|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|<\s*[a-zA-Z/!]|"
                             r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f])")


def safe_claim_text(text: str) -> bool:
    return (0 < len(text) <= MAX_CLAIM_CHARS and not UNSAFE_CLAIM_RE.search(text)
            and not INJECTION_RE.search(text) and not PROHIBITED_RE.search(text))


def verify_claims(claims: list[Claim], facts: list[Fact]) -> tuple[list[Claim], list[Claim]]:
    """Keep a claim only if every cited fact is supported, its values appear in the text,
    and the text is safe to send (no prohibited assertion, link, address, markup or instruction)."""
    supported = {f.field: f for f in facts if f.status == "supported"}
    kept, rejected = [], []
    for c in claims:
        ok = (bool(c.fact_fields)
              and all(field in supported and _appears(supported[field].value, c.text) for field in c.fact_fields)
              and safe_claim_text(c.text))
        (kept if ok else rejected).append(c)
    return kept, rejected
