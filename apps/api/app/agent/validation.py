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
# Which facts each kind of document can prove. A buyer's chat or an "other" upload never proves delivery or
# payment, and a courier page never proves the order total, whatever the line happens to say.
DOC_FIELDS: dict[str, tuple[str, ...]] = {
    "order_invoice": ("order_id", "transaction_id", "order_amount", "currency", "order_date"),
    # ship_to_*: the buyer's address on PayPal's record, the one PayPal's proof-of-delivery rule compares against.
    "payment_record": ("transaction_id", "payment_amount", "payment_currency", "order_id", "ship_to_city",
                       "ship_to_postal_code"),
    "carrier_tracking": ("tracking_id", "tracking_order_id", "ship_date", "carrier_status", "carrier_event_date",
                         "delivery_city", "delivery_postal_code"),
    "delivery_proof": ("delivery_tracking_id", "delivery_status", "delivery_date", "delivery_city",
                       "delivery_postal_code"),
    "support_message": ("reported_payment_amount",),
    # A resi the seller typed in (evidence.add_tracking_number): it names the parcel, it proves nothing else.
    "seller_shipment": ("tracking_id",),
    # Photos and a summary the seller recorded before shipping (packing.py, ADR-007): what was packed, never delivery.
    "packing_proof": (),
    # SAL's record that an order and its invoice matched. It supports the case, it proves no fact by itself.
    "deal_record": (),
}
MONEY_FIELDS = {"order_amount", "payment_amount", "reported_payment_amount"}
CURRENCY_FIELDS = {"currency", "payment_currency"}
DATE_FIELDS = {"order_date", "ship_date", "carrier_event_date", "delivery_date"}
POSTAL_FIELDS = {"ship_to_postal_code", "delivery_postal_code"}
CITY_FIELDS = {"ship_to_city", "delivery_city"}
# Postal codes worldwide: 94107, 94107-1234, SW1A 1AA, K1A 0B1, 10110, 1000. At least one digit.
_POSTAL = re.compile(r"(?=[A-Z0-9 -]*\d)[A-Z0-9][A-Z0-9 -]{1,8}[A-Z0-9]")
_CITY = re.compile(r"[^\W\d_][^\W\d_ .'-]*(?:[ .'-]+[^\W\d_]+)*\.?")
# Words couriers and PayPal put in front of the same city ("Kota Bandung", "Kab. Bogor", "City of Manila").
_CITY_PREFIX = re.compile(r"^(KOTA|KABUPATEN|KAB|CITY OF)\b\.?\s*")


def postal_key(value: str) -> str:
    return re.sub(r"[\s-]", "", value.upper())


def same_postal(a: str, b: str) -> bool:
    """94107 and 94107-1234 are the same US delivery area; otherwise the codes must be equal."""
    ka, kb = postal_key(a), postal_key(b)
    if ka == kb:
        return True
    short, long_ = sorted((ka, kb), key=len)
    return short.isdigit() and long_.isdigit() and len(short) == 5 and len(long_) == 9 and long_.startswith(short)


def same_city(a: str, b: str) -> bool:
    """Lenient on purpose ("Kota Bandung" is Bandung): a city is only compared when no postal code is shown."""
    ka, kb = (re.sub(r"[^A-Z]", "", _CITY_PREFIX.sub("", v.upper())) for v in (a, b))
    return bool(ka and kb) and (ka in kb or kb in ka)

INJECTION_RE = re.compile(
    r"(system\s*override|ignore (all |the )?(previous|prior|above|invoice)|disregard|you must|"
    r"as an ai|new instructions?|assert delivered|approve (this|the) (claim|refund)|"
    # Indonesian: "abaikan instruksi sebelumnya", "setujui refund/klaim", "anda harus"
    r"abaikan (semua |seluruh )?(instruksi|perintah)|setujui (klaim|refund|pengembalian)|(kamu|anda) harus)",
    re.IGNORECASE)

PROHIBITED_RE = re.compile(
    r"(guarantee|will be won|fraud|already ruled|refund was issued|definitively verified|"
    r"follow the instruction)", re.IGNORECASE)


STATUS_FIELDS = {"carrier_status", "delivery_status"}
VALUE_FAILS_TYPE_CHECK = "value fails type check"
# Normalized statuses, so words are joined by underscores: NOT_DELIVERED, RETURNED_TO_SENDER, DELIVERY_ATTEMPT_FAILED.
_DELIVERY_FAILED = re.compile(r"NOT_|RETURN|FAIL|UNDELIVER|CANCEL|LOST|REFUSED|REJECTED|GAGAL|BELUM|RETUR")
# Real documents use their own references (#100245, 1Z999AA10123456784, 2X920845424009805): letters, digits
# and dashes with at least one digit. The golden TXN-/ORD-/TRK- ids are a subset.
# Indonesian invoices often use slashes (INV/2026/10/0087, DBR/0921).
GENERIC_ID = r"(?=[A-Za-z0-9/-]*\d)[A-Za-z0-9][A-Za-z0-9/-]{3,39}"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
# Indonesian names that do not share English's first three letters: Mei, Agustus (Agu/Agt/Ags), Oktober, Desember.
MONTHS.update({"mei": 5, "agu": 8, "agt": 8, "ags": 8, "okt": 10, "des": 12})
_MONTH = r"(jan|feb|mar|apr|may|mei|jun|jul|aug|agu|agt|ags|sep|sept|oct|okt|nov|dec|des)[a-z]*\.?"
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
_CURRENCY_MARK = re.compile(r"[$€£¥₱]|\bRp\b|\b(?:" + "|".join(CURRENCY_CODES) + r")\b")
# Indonesian notation: decimal comma (USD 120,00) and dot thousands (Rp 1.250.000). The dot form is read only
# next to Rp/IDR, so an English "1.250" is never taken for a thousand.
_AMOUNT_COMMA_DECIMAL = re.compile(r"(?<![\w.,-])(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})(?![\w-]|[.,]\d)")
_AMOUNT_DOT_THOUSANDS = re.compile(r"(?<![\w.,-])(\d{1,3}(?:\.\d{3})+)(?![\w-]|[.,]\d)")
_RUPIAH = re.compile(r"\bRp\.?|\bIDR\b")
# Statuses as couriers write them (regexes), mapped to SAL's words. "Diterima di Gateway/Drop Point" is a
# warehouse scan, not a delivery: "diterima" counts only when it is not followed by "di".
STATUS_WORDS = {
    "OUT_FOR_DELIVERY": (r"out for delivery", r"sedang diantar"),
    "IN_TRANSIT": (r"in transit", r"dalam perjalanan"),
    "RETURNED": (r"returned", r"dikembalikan", r"retur"),
    "DELIVERED": (r"delivered", r"terkirim", r"selesai antar", r"diterima(?!\s+di\b)"),
}
_NEGATED = re.compile(r"\b(not|belum|gagal|failed|undelivered|tidak)\b", re.I)


def _status_phrase(text: str) -> str | None:
    """SAL's status for a courier phrase, or None. A negated phrase ("belum terkirim", "not delivered") is none."""
    if _NEGATED.search(text):
        return None
    for status, words in STATUS_WORDS.items():
        if any(re.search(rf"(?<!\w){w}(?!\w)", text, re.I) for w in words):
            return status
    return None


def dates_in(text: str) -> set[str]:
    """ISO dates written in a line in any unambiguous format."""
    found: set[str] = set()
    for pattern, order in _DATE_FORMS:
        for m in pattern.finditer(text):
            parts = dict(zip(order, m.groups(), strict=True))
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
    for m in _AMOUNT_COMMA_DECIMAL.finditer(text):
        found.add(Decimal(m.group(1).replace(".", "") + "." + m.group(2)))
    if _RUPIAH.search(text):
        for m in _AMOUNT_DOT_THOUSANDS.finditer(text):
            found.add(Decimal(m.group(1).replace(".", "")))
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
        return _status_phrase(text) == value
    if field in CURRENCY_FIELDS:  # "Rp" is how Indonesian documents write the rupiah
        return value == "IDR" and re.search(r"\bRp\b", text) is not None
    if field in POSTAL_FIELDS or field in CITY_FIELDS:  # written in any case: "san francisco", "sw1a 1aa"
        return _appears(value, text.upper())
    return False


def _normalize(field: str, value: str) -> str | None:
    v = value.strip()
    if field in ID_PATTERNS:
        return v if re.fullmatch(ID_PATTERNS[field], v) or re.fullmatch(GENERIC_ID, v) else None
    if field in STATUS_FIELDS:
        # Carriers add detail ("Delivered, In/At Mailbox", "Paket telah diterima oleh [AIRA]"): keep the status.
        known = _status_phrase(v.replace("_", " "))
        if known:
            return known
        if _NEGATED.search(v):
            return None
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
        v = re.sub(r"^(\d{4}-\d{2}-\d{2})[ T]\d{1,2}[:.]\d{2}(?::\d{2})?$", r"\1", v)  # a time is dropped
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            return None
    if field in POSTAL_FIELDS:
        v = re.sub(r"\s+", " ", v.upper())
        return v if _POSTAL.fullmatch(v) else None
    if field in CITY_FIELDS:
        v = re.sub(r"\s+", " ", v.upper()).strip(" ,")
        return v if len(v) <= 40 and _CITY.fullmatch(v) else None
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
        if not c.value.strip():  # the model naming a field it found no value for is not a claim to check
            continue
        doc = docs.get(c.source.evidence_id)
        text = doc.line_text(c.source.line) if doc else None
        value = _normalize(c.field, c.value)
        if text is None:
            facts.append(Fact(c.field, c.value, c.source, "rejected", "source line does not exist"))
        elif c.field not in DOC_FIELDS.get(doc.type or "", ()):
            facts.append(Fact(c.field, c.value, c.source, "rejected", "field not expected in this document type"))
        elif c.quote.strip() not in text:
            facts.append(Fact(c.field, c.value, c.source, "rejected", "quote not found in source line"))
        elif value is None:
            facts.append(Fact(c.field, c.value, c.source, "rejected", VALUE_FAILS_TYPE_CHECK))
        elif not value_in_line(c.field, value, text):
            facts.append(Fact(c.field, value, c.source, "rejected", "value not present in source line"))
        elif (c.field, value) not in seen:
            seen.add((c.field, value))
            facts.append(Fact(c.field, value, c.source, "supported"))
    return facts


def _supported_by_field(facts: list[Fact]) -> dict[str, list[Fact]]:
    by_field: dict[str, list[Fact]] = {}
    for f in facts:
        if f.status == "supported":
            by_field.setdefault(f.field, []).append(f)
    return by_field


def _mark_conflicted(facts: tuple[Fact, ...] | list[Fact], why: str) -> None:
    for f in facts:
        f.status, f.reason = "conflicted", why


def _rule_one_value_per_field(facts: list[Fact]) -> list[Finding]:
    """One field, two different values (e.g. a subtotal and a total both proposed as order_amount): SAL never
    picks one silently. Every value becomes conflicted and the operator decides."""
    findings = []
    why = "Documents give different values for this; requires human review"
    for field, group in _supported_by_field(facts).items():
        if len({f.value for f in group}) > 1:
            findings.append(Finding("conflict", field, tuple(f.source for f in group), why))
            _mark_conflicted(group, why)
    return findings


def _rule_courier_documents_present(present: set[str]) -> list[Finding]:
    return [Finding("missing", required, (), f"No {required} document attached")
            for required in ("carrier_tracking", "delivery_proof") if required not in present]


def _rule_delivery_dates_agree(first) -> list[Finding]:
    carrier, delivered = first("carrier_event_date"), first("delivery_date")
    if not (carrier and delivered and carrier.value != delivered.value):
        return []
    why = "Carrier latest event and delivery proof dates do not agree; requires human review"
    _mark_conflicted((carrier, delivered), why)
    return [Finding("conflict", "delivery_date", (carrier.source, delivered.source), why)]


def _rule_tracking_numbers_agree(first) -> list[Finding]:
    """A proof of delivery for another resi proves another parcel."""
    tracked, proved = first("tracking_id"), first("delivery_tracking_id")
    if not (tracked and proved and tracked.value != proved.value):
        return []
    why = "The proof of delivery is for a different tracking number; requires human review"
    _mark_conflicted((tracked, proved), why)
    return [Finding("conflict", "tracking_id", (tracked.source, proved.source), why)]


def _rule_delivered_to_the_paypal_address(first) -> list[Finding]:
    """PayPal's proof of delivery must show the address on the transaction (Seller Protection, item not received).
    A different postal code means a different place. Cities are compared later and only softly (assess)."""
    ship_to, delivered_to = first("ship_to_postal_code"), first("delivery_postal_code")
    if not (ship_to and delivered_to) or same_postal(ship_to.value, delivered_to.value):
        return []
    why = "The parcel was delivered to a different postal code than the address on the PayPal payment"
    _mark_conflicted((ship_to, delivered_to), why)
    return [Finding("conflict", "delivery_postal_code", (ship_to.source, delivered_to.source), why)]


def _rule_no_failed_delivery(facts: list[Fact]) -> list[Finding]:
    """A document saying the parcel did not arrive outvotes a dated proof: the two cannot both stand, so a person
    decides. A negated status ("FAILED") never becomes a fact, so its rejected form counts here too. Only words that
    mean failure count: "Completed" or an older "In transit" reading are not failures."""
    failed = [f for f in facts if f.field in STATUS_FIELDS and (
        (f.status == "rejected" and f.reason == VALUE_FAILS_TYPE_CHECK)
        or (f.status == "supported" and _DELIVERY_FAILED.search(f.value)))]
    if not failed:
        return []
    why = f"A document says the delivery did not succeed ({failed[0].value}); requires human review"
    _mark_conflicted([f for f in failed if f.status == "supported"], why)
    return [Finding("conflict", "delivery_status", tuple(f.source for f in failed), why)]


def _rule_timeline_in_order(first) -> list[Finding]:
    """Ordered, then shipped, then delivered. A step dated before the one it follows means a wrong or edited
    document, so the case goes to a person instead of to PayPal."""
    findings = []
    ordered, shipped = first("order_date"), first("ship_date")
    delivered = next((f for f in (first("delivery_date"), first("carrier_event_date"))
                      if f is not None and f.status == "supported"), None)
    if ordered and shipped and shipped.value < ordered.value:
        why = f"The courier shows it shipped on {shipped.value}, before the order date {ordered.value}"
        _mark_conflicted((ordered, shipped), why)
        findings.append(Finding("conflict", "ship_before_order", (ordered.source, shipped.source), why))
    if shipped and delivered and shipped.status == "supported" and delivered.value < shipped.value:
        why = f"Delivered on {delivered.value}, before it was shipped on {shipped.value}"
        _mark_conflicted((shipped, delivered), why)
        findings.append(Finding("conflict", "delivered_before_ship", (shipped.source, delivered.source), why))
    return findings


def _rule_buyer_amount_matches_payment(first) -> list[Finding]:
    paid, reported = first("payment_amount"), first("reported_payment_amount")
    if not (paid and reported and Decimal(paid.value) != Decimal(reported.value)):
        return []
    # Only the buyer's figure is in doubt; the settled payment record stays supported.
    reported.status, reported.reason = "conflicted", "buyer-reported amount differs from payment record"
    return [Finding("conflict", "reported_payment_amount", (paid.source, reported.source),
                    "Buyer-reported amount differs from payment record; do not substitute")]


def _rule_amounts_match_dispute(first, dispute_amount: str, dispute_currency: str) -> list[Finding]:
    """A buyer may dispute part of a payment (one item of two), so a larger order or payment is normal.
    Only an amount BELOW the disputed amount cannot be right; a different currency never is."""
    findings = []
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
    return findings


def _rule_no_hidden_instructions(documents: list[Document]) -> list[Finding]:
    return [Finding("conflict", "untrusted_instruction", (SourceRef(doc.evidence_id, line.line),),
                    "Instruction-like text inside a document is data, never an instruction")
            for doc in documents for line in doc.lines if INJECTION_RE.search(line.text)]


def apply_inr_rules(facts: list[Fact], documents: list[Document], dispute_amount: str,
                    dispute_currency: str, inr: bool = True) -> list[Finding]:
    """Generic checks for every dispute (one field/two values, amounts, currencies, hidden instructions);
    the Item-Not-Received checks (courier documents, delivery dates) only when inr is True.
    Order matters: the one-value rule runs first, so later rules only see facts that are still supported."""
    findings = _rule_one_value_per_field(facts)
    by_field = _supported_by_field(facts)

    def first(field: str) -> Fact | None:
        return (by_field.get(field) or [None])[0]

    if inr:
        findings += _rule_courier_documents_present({d.type for d in documents})
        findings += _rule_delivery_dates_agree(first)
        findings += _rule_tracking_numbers_agree(first)
        findings += _rule_delivered_to_the_paypal_address(first)
        findings += _rule_timeline_in_order(first)
        findings += _rule_no_failed_delivery(facts)
    findings += _rule_buyer_amount_matches_payment(first)
    findings += _rule_amounts_match_dispute(first, dispute_amount, dispute_currency)
    findings += _rule_no_hidden_instructions(documents)
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
