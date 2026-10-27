"""ASSESS stage (ADR-005): what the evidence proves for an Item-Not-Received dispute, and what to do next.

Deterministic, like grounding and the rules: it reads validated facts and findings, never raw model output.
No win/loss prediction and no numeric score; four readiness states with one next action.
"""
from __future__ import annotations

from decimal import Decimal

from app.agent.models import Assessment, Document, Fact, Finding, Proposition, SourceRef

PROPOSITIONS = ("payment_matches", "shipped", "delivered", "delivery_date_consistent", "buyer_messages_clean",
                "paypal_request_covered")
SUPPORTED_REASONS = {"ITEM_NOT_RECEIVED"}
# What PayPal's own evidence requests need, in terms of propositions (ADR-001: PayPal's list is authoritative).
REQUEST_NEEDS = {"PROOF_OF_FULFILLMENT": ("shipped", "delivered"), "PROOF_OF_SHIPMENT": ("shipped",),
                 "PROOF_OF_DELIVERY": ("delivered",)}

# Which proposition a fact or a finding belongs to.
FIELD_PROPOSITION = {
    "order_amount": "payment_matches", "payment_amount": "payment_matches", "currency": "payment_matches",
    "payment_currency": "payment_matches", "transaction_id": "payment_matches",
    "order_amount_vs_dispute": "payment_matches", "payment_amount_vs_dispute": "payment_matches",
    "currency_vs_dispute": "payment_matches", "payment_currency_vs_dispute": "payment_matches",
    "tracking_id": "shipped", "tracking_order_id": "shipped", "ship_date": "shipped",
    "carrier_status": "delivered", "carrier_event_date": "delivered", "delivery_tracking_id": "delivered",
    "delivery_status": "delivered",
    "delivery_date": "delivery_date_consistent",
    "untrusted_instruction": "buyer_messages_clean", "reported_payment_amount": "buyer_messages_clean",
}
# Payment can only be proven by PayPal's own record (or a seeded practice record standing in for it).
TRUSTED_PAYMENT_ORIGINS = {"PAYPAL_API", "SEED"}
MOVING = {"SHIPPED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"}


class _Case:
    """What the proposition checks read: supported facts by field, conflicts by proposition, documents present."""

    def __init__(self, facts: list[Fact], findings: list[Finding],
                 documents: list[Document] | tuple[Document, ...]) -> None:
        self.docs = {d.evidence_id: d for d in documents}
        self.present = {d.type for d in documents}
        self.supported: dict[str, list[Fact]] = {}
        for f in facts:
            if f.status == "supported":
                self.supported.setdefault(f.field, []).append(f)
        self.trouble: dict[str, list[Finding]] = {}
        for finding in findings:
            if finding.kind == "conflict":
                self.trouble.setdefault(FIELD_PROPOSITION.get(finding.field, "payment_matches"), []).append(finding)

    def first(self, field: str) -> Fact | None:
        return (self.supported.get(field) or [None])[0]

    def conflicted(self, pid: str, status: str) -> Proposition | None:
        """The proposition as the rules' conflict states it, or None when the rules found no conflict."""
        found = self.trouble.get(pid)
        if not found:
            return None
        return Proposition(pid, status, found[0].description, tuple(r for f in found for r in f.source_refs))


def _refs(*facts: Fact | None) -> tuple[SourceRef, ...]:
    return tuple(f.source for f in facts if f is not None)


def _payment_matches(case: _Case, amount: str, currency: str) -> Proposition:
    """1. The payment PayPal recorded matches the dispute."""
    if conflict := case.conflicted("payment_matches", "contradicted"):
        return conflict
    paid = next((f for f in case.supported.get("payment_amount", [])
                 if (doc := case.docs.get(f.source.evidence_id)) and doc.origin in TRUSTED_PAYMENT_ORIGINS), None)
    if paid is None:
        if "payment_record" in case.present:
            return Proposition("payment_matches", "missing",
                               "The payment document is not a PayPal record, so it cannot prove payment")
        return Proposition("payment_matches", "missing", "No PayPal transaction record yet")
    cur = case.first("payment_currency")
    if cur is not None and cur.value != currency:
        return Proposition("payment_matches", "contradicted",
                           f"PayPal recorded {cur.value}, the dispute is in {currency}", _refs(paid, cur))
    if Decimal(paid.value) == Decimal(amount):
        return Proposition("payment_matches", "proven",
                           f"PayPal recorded {paid.value} {currency}, the disputed amount", _refs(paid, cur))
    if Decimal(paid.value) > Decimal(amount):  # a partial dispute, e.g. one item of two
        return Proposition("payment_matches", "proven",
                           f"PayPal recorded {paid.value} {currency}; the buyer disputes {amount} of it",
                           _refs(paid, cur))
    return Proposition("payment_matches", "contradicted",
                       f"PayPal recorded only {paid.value}, less than the disputed {amount}", _refs(paid))


def _shipped(case: _Case) -> Proposition:
    """2. The parcel was shipped: a tracking number plus a date or a carrier status that implies it moved."""
    if conflict := case.conflicted("shipped", "contradicted"):
        return conflict
    tracking = case.first("tracking_id")
    moved = case.first("ship_date") or case.first("carrier_event_date") or next(
        (f for f in case.supported.get("carrier_status", []) if f.value in MOVING), None)
    if tracking and moved:
        return Proposition("shipped", "proven", f"Tracking {tracking.value} shows the parcel moving",
                           _refs(tracking, moved))
    if "carrier_tracking" not in case.present:
        return Proposition("shipped", "missing", "No courier tracking attached")
    return Proposition("shipped", "missing", "The tracking document shows no tracking number or movement",
                       _refs(tracking))


def _delivered(case: _Case) -> Proposition:
    """3. It was delivered: the carrier says DELIVERED, or a proof of delivery carries a date."""
    if conflict := case.conflicted("delivered", "contradicted"):
        return conflict
    status, delivered_on = case.first("carrier_status"), case.first("delivery_date")
    if status is not None and status.value == "DELIVERED":
        return Proposition("delivered", "proven", "The courier marked the parcel DELIVERED", _refs(status))
    if delivered_on is not None:
        return Proposition("delivered", "proven", f"Proof of delivery dated {delivered_on.value}", _refs(delivered_on))
    if status is not None:
        return Proposition("delivered", "missing", f"The courier's latest status is {status.value}", _refs(status))
    if "delivery_proof" not in case.present:
        return Proposition("delivered", "missing", "No proof of delivery attached")
    return Proposition("delivered", "missing", "The delivery document shows no date or status")


def _delivery_dates_agree(case: _Case) -> Proposition:
    """4. The delivery dates agree (only when two sources give one)."""
    if conflict := case.conflicted("delivery_date_consistent", "contradicted"):
        return conflict
    carrier_date, delivered_on = case.first("carrier_event_date"), case.first("delivery_date")
    if carrier_date and delivered_on:
        return Proposition("delivery_date_consistent", "proven", f"Courier and proof agree on {delivered_on.value}",
                           _refs(carrier_date, delivered_on))
    return Proposition("delivery_date_consistent", "not_applicable", "Only one delivery date to compare")


def _buyer_messages_clean(case: _Case) -> Proposition:
    """5. Buyer messages hold no hidden instructions and no contradicting figures."""
    if conflict := case.conflicted("buyer_messages_clean", "flagged"):
        return conflict
    if "support_message" in case.present:
        return Proposition("buyer_messages_clean", "proven", "No hidden instructions or conflicting figures")
    return Proposition("buyer_messages_clean", "not_applicable", "No buyer messages attached")


def _paypal_request_covered(requested: tuple[str, ...], props: list[Proposition]) -> Proposition:
    """6. PayPal's own request for evidence is covered by the propositions above."""
    needs = [(r, REQUEST_NEEDS.get(r)) for r in requested]
    if not needs:
        return Proposition("paypal_request_covered", "not_applicable", "PayPal has not asked for specific evidence")
    by_id = {p.id: p for p in props}
    unknown = [r for r, n in needs if n is None]
    gaps = [r for r, n in needs if n and any(by_id[x].status != "proven" for x in n)]
    asked = ", ".join(r.replace("_", " ").lower() for r in requested)
    if gaps:
        return Proposition("paypal_request_covered", "missing", f"PayPal asked for {asked}; not proven yet")
    if unknown:
        return Proposition("paypal_request_covered", "flagged",
                           f"PayPal asked for {asked}; check you have it, SAL can't verify that type")
    return Proposition("paypal_request_covered", "proven", f"PayPal asked for {asked}; your documents cover it")


def assess(facts: list[Fact], findings: list[Finding], documents: list[Document] | tuple[Document, ...],
           dispute_amount: str, dispute_currency: str, reason: str = "ITEM_NOT_RECEIVED",
           requested: tuple[str, ...] = ()) -> Assessment:
    if reason not in SUPPORTED_REASONS:  # never judge e.g. "not as described" by shipping rules
        return Assessment((), "NEEDS_CHECK",
                          "SAL's evidence check covers 'item not received' disputes only. Review this case in PayPal.")
    case = _Case(facts, findings, documents)
    props = [_payment_matches(case, dispute_amount, dispute_currency), _shipped(case), _delivered(case),
             _delivery_dates_agree(case), _buyer_messages_clean(case)]
    props.append(_paypal_request_covered(requested, props))
    return Assessment(tuple(props), *_readiness(props))


def _readiness(props: list[Proposition]) -> tuple[str, str]:
    by_id = {p.id: p for p in props}
    open_check = [p for p in props if p.status in ("contradicted", "flagged")]
    if open_check:
        return "NEEDS_CHECK", f"Check this first: {open_check[0].reason}."
    shipped, delivered = by_id["shipped"], by_id["delivered"]
    if shipped.status == "missing" and delivered.status == "missing" and \
            shipped.reason.startswith("No courier") and delivered.reason.startswith("No proof"):
        return "WEAK", ("There is no courier evidence at all. Add tracking or proof of delivery if you have it; "
                        "if you can't prove shipping, consider refunding the buyer in PayPal.")
    missing = [p for p in props if p.status == "missing"]
    if missing:
        return "NEEDS_DOCUMENTS", f"Add what's missing: {missing[0].reason}."
    return "READY", "Your documents back the reply. Read it and approve."


def claimable(facts: list[Fact], assessment: Assessment) -> list[Fact]:
    """The facts a reply may state: supported, and belonging to a proven proposition (or to none)."""
    proven = {p.id for p in assessment.propositions if p.status == "proven"}

    def owner(field: str) -> str | None:
        # A delivery date may be stated once delivery is proven; a contradicted date is never "supported".
        return "delivered" if field == "delivery_date" else FIELD_PROPOSITION.get(field)

    return [f for f in facts if f.status == "supported" and (owner(f.field) is None or owner(f.field) in proven)]
