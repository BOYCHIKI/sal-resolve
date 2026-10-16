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


def assess(facts: list[Fact], findings: list[Finding], documents: list[Document] | tuple[Document, ...],
           dispute_amount: str, dispute_currency: str, reason: str = "ITEM_NOT_RECEIVED",
           requested: tuple[str, ...] = ()) -> Assessment:
    if reason not in SUPPORTED_REASONS:  # never judge e.g. "not as described" by shipping rules
        return Assessment((), "NEEDS_CHECK",
                          "SAL's evidence check covers 'item not received' disputes only. Review this case in PayPal.")
    docs = {d.evidence_id: d for d in documents}
    present = {d.type for d in documents}
    supported: dict[str, list[Fact]] = {}
    for f in facts:
        if f.status == "supported":
            supported.setdefault(f.field, []).append(f)

    def first(field: str) -> Fact | None:
        return (supported.get(field) or [None])[0]

    # Conflicts and flags from the rules, grouped by proposition.
    trouble: dict[str, list[Finding]] = {}
    for fi in findings:
        if fi.kind == "conflict":
            trouble.setdefault(FIELD_PROPOSITION.get(fi.field, "payment_matches"), []).append(fi)

    def refs(*fs: Fact | None) -> tuple[SourceRef, ...]:
        return tuple(f.source for f in fs if f is not None)

    def from_trouble(pid: str, status: str) -> Proposition:
        found = trouble[pid]
        return Proposition(pid, status, found[0].description, tuple(r for fi in found for r in fi.source_refs))

    props: list[Proposition] = []

    # 1. The payment PayPal recorded matches the dispute.
    paid = next((f for f in supported.get("payment_amount", [])
                 if docs.get(f.source.evidence_id) and docs[f.source.evidence_id].origin in TRUSTED_PAYMENT_ORIGINS),
                None)
    if "payment_matches" in trouble:
        props.append(from_trouble("payment_matches", "contradicted"))
    elif paid is not None:
        cur = first("payment_currency")
        if cur is not None and cur.value != dispute_currency:
            props.append(Proposition("payment_matches", "contradicted",
                                     f"PayPal recorded {cur.value}, the dispute is in {dispute_currency}", refs(paid, cur)))
        elif Decimal(paid.value) == Decimal(dispute_amount):
            props.append(Proposition("payment_matches", "proven",
                                     f"PayPal recorded {paid.value} {dispute_currency}, the disputed amount",
                                     refs(paid, cur)))
        elif Decimal(paid.value) > Decimal(dispute_amount):  # a partial dispute, e.g. one item of two
            props.append(Proposition("payment_matches", "proven",
                                     f"PayPal recorded {paid.value} {dispute_currency}; the buyer disputes "
                                     f"{dispute_amount} of it", refs(paid, cur)))
        else:
            props.append(Proposition("payment_matches", "contradicted",
                                     f"PayPal recorded only {paid.value}, less than the disputed {dispute_amount}",
                                     refs(paid)))
    elif any(d.type == "payment_record" for d in documents):
        props.append(Proposition("payment_matches", "missing",
                                 "The payment document is not a PayPal record, so it cannot prove payment"))
    else:
        props.append(Proposition("payment_matches", "missing", "No PayPal transaction record yet"))

    # 2. The parcel was shipped: a tracking number plus a date or a carrier status that implies it moved.
    tracking = first("tracking_id")
    moved = first("ship_date") or first("carrier_event_date") or next(
        (f for f in supported.get("carrier_status", []) if f.value in MOVING), None)
    if "shipped" in trouble:
        props.append(from_trouble("shipped", "contradicted"))
    elif tracking and moved:
        props.append(Proposition("shipped", "proven", f"Tracking {tracking.value} shows the parcel moving",
                                 refs(tracking, moved)))
    elif "carrier_tracking" not in present:
        props.append(Proposition("shipped", "missing", "No courier tracking attached"))
    else:
        props.append(Proposition("shipped", "missing", "The tracking document shows no tracking number or movement",
                                 refs(tracking)))

    # 3. It was delivered: the carrier says DELIVERED, or a proof of delivery carries a date.
    status = first("carrier_status")
    delivered_on = first("delivery_date")
    if "delivered" in trouble:
        props.append(from_trouble("delivered", "contradicted"))
    elif status is not None and status.value == "DELIVERED":
        props.append(Proposition("delivered", "proven", "The courier marked the parcel DELIVERED", refs(status)))
    elif delivered_on is not None:
        props.append(Proposition("delivered", "proven", f"Proof of delivery dated {delivered_on.value}",
                                 refs(delivered_on)))
    elif status is not None:
        props.append(Proposition("delivered", "missing", f"The courier's latest status is {status.value}", refs(status)))
    elif "delivery_proof" not in present:
        props.append(Proposition("delivered", "missing", "No proof of delivery attached"))
    else:
        props.append(Proposition("delivered", "missing", "The delivery document shows no date or status"))

    # 4. The delivery dates agree (only when two sources give one).
    carrier_date = first("carrier_event_date")
    if "delivery_date_consistent" in trouble:
        props.append(from_trouble("delivery_date_consistent", "contradicted"))
    elif carrier_date and delivered_on:
        props.append(Proposition("delivery_date_consistent", "proven", f"Courier and proof agree on {delivered_on.value}",
                                 refs(carrier_date, delivered_on)))
    else:
        props.append(Proposition("delivery_date_consistent", "not_applicable", "Only one delivery date to compare"))

    # 5. Buyer messages hold no hidden instructions and no contradicting figures.
    if "buyer_messages_clean" in trouble:
        props.append(from_trouble("buyer_messages_clean", "flagged"))
    elif "support_message" in present:
        props.append(Proposition("buyer_messages_clean", "proven", "No hidden instructions or conflicting figures"))
    else:
        props.append(Proposition("buyer_messages_clean", "not_applicable", "No buyer messages attached"))

    # 6. PayPal's own request for evidence is covered.
    needs = [(r, REQUEST_NEEDS.get(r)) for r in requested]
    if not needs:
        props.append(Proposition("paypal_request_covered", "not_applicable", "PayPal has not asked for specific evidence"))
    else:
        by_id = {p.id: p for p in props}
        unknown = [r for r, n in needs if n is None]
        gaps = [r for r, n in needs if n and any(by_id[x].status != "proven" for x in n)]
        asked = ", ".join(r.replace("_", " ").lower() for r in requested)
        if gaps:
            props.append(Proposition("paypal_request_covered", "missing", f"PayPal asked for {asked}; not proven yet"))
        elif unknown:
            props.append(Proposition("paypal_request_covered", "flagged",
                                     f"PayPal asked for {asked}; check you have it, SAL can't verify that type"))
        else:
            props.append(Proposition("paypal_request_covered", "proven", f"PayPal asked for {asked}; your documents cover it"))
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
