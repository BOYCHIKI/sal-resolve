"""Deal Check: compares what was ordered with what was invoiced, before anything is delivered.

Orders and invoices arrive as exact structured data from a person's tool or an AI agent. Nothing is guessed:
money is a decimal string, dates carry a time zone, an unknown field is refused, and item codes match exactly.
The check is plain code with no model in it, and its result (HOLD or CLEAR) lives only in SAL. Nothing here
calls or writes to PayPal.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import timezone
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import actions
from app import repositories as repo
from app.agent.validation import same_city, same_postal
from app.agent_identity import AgentIdentity, AgentRole
from app.db import app_engine, tenant_session
from app.packing import dispute_refs

RULE_VERSION = "SAL-DEAL-1"
CHECK_DEAL_JOB = "check_deal"
MAX_LINES = 200
_DECIMAL = re.compile(r"[0-9]{1,15}(\.[0-9]{1,4})?")   # NUMERIC(19,4), like every amount SAL stores


class DealCategory(StrEnum):
    GOODS = "GOODS"
    DIGITAL = "DIGITAL"
    SERVICE = "SERVICE"


class DealStatus(StrEnum):
    WAITING_INVOICE = "WAITING_INVOICE"
    CHECKING = "CHECKING"
    HOLD = "HOLD"
    CLEAR = "CLEAR"


class FindingCode(StrEnum):
    CURRENCY_DIFFERS = "CURRENCY_DIFFERS"
    ITEM_NOT_ORDERED = "ITEM_NOT_ORDERED"
    ITEM_NOT_INVOICED = "ITEM_NOT_INVOICED"
    QUANTITY_DIFFERS = "QUANTITY_DIFFERS"
    UNIT_PRICE_DIFFERS = "UNIT_PRICE_DIFFERS"
    TOTAL_DOES_NOT_ADD_UP = "TOTAL_DOES_NOT_ADD_UP"
    OVER_APPROVED_LIMIT = "OVER_APPROVED_LIMIT"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    ADDRESS_DIFFERS = "ADDRESS_DIFFERS"


CORRECTION_TEXT: dict[FindingCode, str] = {
    FindingCode.CURRENCY_DIFFERS: "The currency differs",
    FindingCode.ITEM_NOT_ORDERED: "An item on the invoice was not ordered",
    FindingCode.ITEM_NOT_INVOICED: "An ordered item is not on the invoice",
    FindingCode.QUANTITY_DIFFERS: "The quantity differs",
    FindingCode.UNIT_PRICE_DIFFERS: "The unit price differs",
    FindingCode.TOTAL_DOES_NOT_ADD_UP: "The invoice total does not add up",
    FindingCode.OVER_APPROVED_LIMIT: "The invoice is over the approved limit",
    FindingCode.APPROVAL_EXPIRED: "The approval had ended when the invoice was issued",
    FindingCode.ADDRESS_DIFFERS: "The delivery address differs",
}


class DealError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code, self.status = code, status


def _exact_decimal(value: Any) -> Decimal:
    """Only a plain decimal string. A JSON number may already have lost cents, and "1,200" reads differently by
    country, so neither is accepted."""
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValueError("must be a decimal string such as '1200.00'")
    return Decimal(value)


def _normal_code(value: str) -> str:
    return value.strip().upper()


Amount = Annotated[Decimal, BeforeValidator(_exact_decimal)]
Quantity = Annotated[Decimal, BeforeValidator(_exact_decimal), Field(gt=0)]
ItemCode = Annotated[str, AfterValidator(_normal_code), Field(pattern=r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Reference = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Address(_Strict):
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    city: Annotated[str, Field(min_length=1, max_length=80)]
    postal_code: Annotated[str, Field(min_length=2, max_length=12)] | None = None


class DealLine(_Strict):
    item_code: ItemCode
    description: Annotated[str, Field(min_length=1, max_length=200)]
    quantity: Quantity
    unit_price: Amount


Lines = Annotated[tuple[DealLine, ...], Field(min_length=1, max_length=MAX_LINES)]


def _unique_codes(lines: tuple[DealLine, ...]) -> None:
    if len({line.item_code for line in lines}) != len(lines):
        raise ValueError("each item_code may appear once")


class PurchaseOrder(_Strict):
    deal_ref: Reference
    category: DealCategory
    currency: Currency
    max_total: Amount               # the most the buyer's approver allowed, shipping and tax included
    approved_by: Annotated[str, Field(min_length=1, max_length=120)]
    expires_at: AwareDatetime       # the approval ends here
    ship_to: Address | None = None
    lines: Lines

    @model_validator(mode="after")
    def _consistent(self) -> PurchaseOrder:
        _unique_codes(self.lines)
        if self.category is DealCategory.GOODS and self.ship_to is None:
            raise ValueError("goods need ship_to")
        return self


class Invoice(_Strict):
    invoice_ref: Reference
    issued_at: AwareDatetime
    currency: Currency
    total: Amount
    shipping: Amount = Decimal("0")
    tax: Amount = Decimal("0")
    ship_to: Address | None = None   # the address on the PayPal invoice
    lines: Lines
    # Ties this deal to a later dispute on the same payment.
    paypal_transaction_id: Annotated[str, Field(pattern=r"^[A-Z0-9]{17}$")] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Invoice:
        _unique_codes(self.lines)
        return self


@dataclass(frozen=True)
class DealFinding:
    code: FindingCode
    field: str
    ordered: str | None
    invoiced: str | None


@dataclass(frozen=True)
class DealCheck:
    status: DealStatus
    findings: tuple[DealFinding, ...]


def _address_label(address: Address | None) -> str | None:
    return f"{address.country} {address.postal_code or address.city}" if address else None


def _same_place(ordered: Address, invoiced: Address) -> bool:
    if ordered.country != invoiced.country:
        return False
    if ordered.postal_code and invoiced.postal_code:
        return same_postal(ordered.postal_code, invoiced.postal_code)
    return same_city(ordered.city, invoiced.city)


def _compare_lines(order: PurchaseOrder, invoice: Invoice) -> list[DealFinding]:
    ordered = {line.item_code: line for line in order.lines}
    invoiced = {line.item_code: line for line in invoice.lines}
    out = [DealFinding(FindingCode.ITEM_NOT_ORDERED, code, None, code) for code in invoiced if code not in ordered]
    out += [DealFinding(FindingCode.ITEM_NOT_INVOICED, code, code, None) for code in ordered if code not in invoiced]
    for code in ordered.keys() & invoiced.keys():
        want, got = ordered[code], invoiced[code]
        if want.quantity != got.quantity:
            out.append(DealFinding(FindingCode.QUANTITY_DIFFERS, code, str(want.quantity), str(got.quantity)))
        if want.unit_price != got.unit_price:
            out.append(DealFinding(FindingCode.UNIT_PRICE_DIFFERS, code, str(want.unit_price), str(got.unit_price)))
    return sorted(out, key=lambda f: (f.field, f.code))


def _compare_amounts(order: PurchaseOrder, invoice: Invoice) -> list[DealFinding]:
    if order.currency != invoice.currency:
        return [DealFinding(FindingCode.CURRENCY_DIFFERS, "currency", order.currency, invoice.currency)]
    out = []
    added_up = sum((line.quantity * line.unit_price for line in invoice.lines), invoice.shipping + invoice.tax)
    if added_up != invoice.total:
        out.append(DealFinding(FindingCode.TOTAL_DOES_NOT_ADD_UP, "total", str(added_up), str(invoice.total)))
    if invoice.total > order.max_total:
        out.append(DealFinding(FindingCode.OVER_APPROVED_LIMIT, "total", str(order.max_total), str(invoice.total)))
    return out


def check_deal(order: PurchaseOrder, invoice: Invoice) -> DealCheck:
    """Every difference holds the deal: a person decides, SAL never settles one by itself."""
    findings = _compare_lines(order, invoice) + _compare_amounts(order, invoice)
    if invoice.issued_at > order.expires_at:
        findings.append(DealFinding(FindingCode.APPROVAL_EXPIRED, "issued_at", order.expires_at.isoformat(),
                                    invoice.issued_at.isoformat()))
    goods = order.category is DealCategory.GOODS   # only goods have an address to compare; services may have none
    if goods and order.ship_to is not None and (invoice.ship_to is None
                                                or not _same_place(order.ship_to, invoice.ship_to)):
        findings.append(DealFinding(FindingCode.ADDRESS_DIFFERS, "ship_to", _address_label(order.ship_to),
                                    _address_label(invoice.ship_to)))
    return DealCheck(DealStatus.HOLD if findings else DealStatus.CLEAR, tuple(findings))


# ---------------------------------------------------------------- storage
def _as_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"))


def create_deal(agent: AgentIdentity, order: PurchaseOrder, engine: Engine | None = None) -> dict[str, Any]:
    """`approved_by` must be the verified agent, so an order can never claim someone else's approval."""
    if agent.role is not AgentRole.BUYER_AGENT:
        raise DealError("AGENT_ROLE_NOT_ALLOWED", 403)
    if order.approved_by != agent.name:
        raise DealError("AGENT_NAME_MISMATCH", 403)
    with tenant_session(agent.merchant_id, engine or app_engine()) as s:
        insert_deal(s, agent.merchant_id, order, f"agent:{agent.name}", agent.id)
    return get_deal(agent.merchant_id, order.deal_ref, engine)


def insert_deal(s: Session, merchant_id: UUID, order: PurchaseOrder, actor: str,
                ordered_by: UUID | None = None) -> None:
    """`ordered_by` is the agent's credential; NULL when a person confirmed the order from a document."""
    try:
        s.execute(text("""INSERT INTO deals (merchant_id, deal_ref, category, purchase_order, ordered_by)
                          VALUES (:m, :ref, :category, CAST(:order AS jsonb), :agent)"""),
                  {"m": merchant_id, "ref": order.deal_ref, "category": order.category.value,
                   "order": _as_json(order), "agent": ordered_by})
    except IntegrityError as exc:
        raise DealError("DEAL_EXISTS", 409) from exc
    repo.write_audit(s, merchant_id, actor, "deal.ordered", target=order.deal_ref)


def submit_invoice(agent: AgentIdentity, deal_ref: str, invoice: Invoice,
                   engine: Engine | None = None) -> dict[str, Any]:
    if agent.role is not AgentRole.SELLER_AGENT:
        raise DealError("AGENT_ROLE_NOT_ALLOWED", 403)
    with tenant_session(agent.merchant_id, engine or app_engine()) as s:
        record_invoice(s, agent.merchant_id, deal_ref, invoice, f"agent:{agent.name}", agent.id)
    return get_deal(agent.merchant_id, deal_ref, engine)


def record_invoice(s: Session, merchant_id: UUID, deal_ref: str, invoice: Invoice, actor: str,
                   invoiced_by: UUID | None = None) -> None:
    """A new invoice replaces the last one and drops any earlier verdict at once, so a CLEAR never outlives what it
    was given for. The job then checks it, with no one asking."""
    row = s.execute(text("""UPDATE deals SET invoice = CAST(:invoice AS jsonb), status = :status, updated_at = now(),
                                             invoice_revision = invoice_revision + 1, invoiced_by = :agent
                            WHERE deal_ref = :ref RETURNING id, invoice_revision"""),
                    {"invoice": _as_json(invoice), "status": DealStatus.CHECKING.value, "ref": deal_ref,
                     "agent": invoiced_by}).first()
    if row is None:
        raise DealError("DEAL_NOT_FOUND", 404)
    repo.enqueue_job(s, merchant_id, CHECK_DEAL_JOB, f"{CHECK_DEAL_JOB}:{row.id}:{row.invoice_revision}", row.id)
    repo.write_audit(s, merchant_id, actor, "deal.invoiced", target=deal_ref,
                     summary={"revision": row.invoice_revision})


def run_check(merchant_id: UUID, deal_id: UUID, engine: Engine) -> dict[str, Any]:
    """One transaction with the row locked: a newer invoice waits, then gets its own check. No network inside."""
    with tenant_session(merchant_id, engine) as s:
        row = s.execute(text("""SELECT deal_ref, status, purchase_order, invoice, invoice_revision FROM deals
                                WHERE id = :id FOR UPDATE"""), {"id": deal_id}).first()
        if row is None or row.status != DealStatus.CHECKING:
            return {"skipped": "nothing to check"}
        result = check_deal(PurchaseOrder.model_validate(row.purchase_order), Invoice.model_validate(row.invoice))
        s.execute(text("""INSERT INTO deal_checks (merchant_id, deal_id, invoice_revision, rule_version, status,
                                                   findings)
                          VALUES (:m, :d, :rev, :rule, :status, CAST(:findings AS jsonb))
                          ON CONFLICT (deal_id, invoice_revision, rule_version) DO NOTHING"""),
                  {"m": merchant_id, "d": deal_id, "rev": row.invoice_revision, "rule": RULE_VERSION,
                   "status": result.status.value, "findings": json.dumps([asdict(f) for f in result.findings])})
        s.execute(text("UPDATE deals SET status = :status, updated_at = now() WHERE id = :id"),
                  {"status": result.status.value, "id": deal_id})
        repo.write_audit(s, merchant_id, "agent", "deal.checked", target=row.deal_ref,
                         summary={"status": result.status.value, "findings": len(result.findings)})
    _update_hold_card(merchant_id, row.deal_ref, row.invoice_revision, result, engine)
    return {"status": result.status.value, "findings": len(result.findings)}


def _update_hold_card(merchant_id: UUID, deal_ref: str, revision: int, result: DealCheck, engine: Engine) -> None:
    """A hold shows on the seller's main page; a clear deal removes the card. The card changes nothing by itself."""
    cards = []
    if result.status is DealStatus.HOLD:
        count = len(result.findings)
        cards.append(actions.Proposal(
            "REVIEW_DEAL_HOLD", f"deal:{deal_ref}", f"Hold {deal_ref}: don’t deliver yet",
            f"SAL found {count} difference{'' if count == 1 else 's'} between the order and the invoice. "
            "The hold stays until a corrected invoice matches. Nothing was sent to PayPal.",
            payload={"deal_ref": deal_ref, "invoice_revision": revision,
                     "findings": [f.code.value for f in result.findings]}))
    actions.save(merchant_id, f"deal:{deal_ref}", None, cards, engine)


def attach_to_dispute(merchant_id: UUID, dispute_id: UUID, engine: Engine | None = None) -> int:
    """Add the matched deal for this payment to the dispute (idempotent). Only a CLEAR deal: a held one shows
    an unresolved difference. Returns documents added. Worker only."""
    with tenant_session(merchant_id, engine) as s:
        refs = dispute_refs(s, dispute_id)
        if refs is None or not refs[0]:
            return 0
        deal = s.execute(text("""
            SELECT d.deal_ref, d.purchase_order, d.invoice, c.rule_version, c.checked_at
            FROM deals d JOIN deal_checks c ON c.deal_id = d.id AND c.invoice_revision = d.invoice_revision
            WHERE d.status = :clear AND d.invoice->>'paypal_transaction_id' = :txn
            ORDER BY c.checked_at DESC LIMIT 1"""), {"clear": DealStatus.CLEAR.value, "txn": refs[0]}).first()
        if deal is None:
            return 0
        order, invoice = deal.purchase_order, deal.invoice
        summary = [f"Order {deal.deal_ref}, approved by {order['approved_by']}",
                   f"Invoice {invoice['invoice_ref']}, total {invoice['total']} {invoice['currency']}"]
        summary += [f"{line['item_code']}: {line['description']}, quantity {line['quantity']}, "
                    f"unit price {line['unit_price']}" for line in invoice["lines"]]
        summary.append(f"SAL matched the order and invoice line by line on "
                       f"{deal.checked_at.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC, before delivery "
                       f"({deal.rule_version}).")
        body = "\n".join(summary)
        added = len(s.execute(text("""
            INSERT INTO evidence (merchant_id, dispute_id, checksum, mime, size_bytes, uploaded_by, doc_type,
                                  content_lines, source_ref, origin)
            VALUES (:m, :d, :c, 'text/plain', :n, 'sal:deal', 'deal_record', CAST(:l AS jsonb), :ref, 'SELLER_INPUT')
            ON CONFLICT (dispute_id, checksum) DO NOTHING RETURNING 1"""),
            {"m": merchant_id, "d": dispute_id, "c": hashlib.sha256(body.encode()).hexdigest(),
             "n": len(body.encode()), "ref": f"Deal {deal.deal_ref}",
             "l": json.dumps([{"line": i, "text": t} for i, t in enumerate(summary, 1)])}).all())
        if added:
            repo.write_audit(s, merchant_id, "sal:deal", "deal.attached", target=str(dispute_id),
                             summary={"deal_ref": deal.deal_ref})
    return added


def check_open_deals(merchant_id: UUID, engine: Engine) -> int:
    """Part of the watch round: finishes any check whose job failed or was lost."""
    with tenant_session(merchant_id, engine) as s:
        ids = s.execute(text("SELECT id FROM deals WHERE status = :status"),
                        {"status": DealStatus.CHECKING.value}).scalars().all()
    for deal_id in ids:
        run_check(merchant_id, deal_id, engine)
    return len(ids)


def correction_message(deal_ref: str, invoice_ref: str, findings: list[dict[str, Any]]) -> str:
    """Written by code from the findings, so it states only what the check found."""
    rows = [f"- {CORRECTION_TEXT[FindingCode(f['code'])]} ({f['field']}): ordered {f['ordered'] or 'nothing'}, "
            f"invoiced {f['invoiced'] or 'nothing'}" for f in findings]
    return "\n".join([f"Order {deal_ref} and invoice {invoice_ref} do not match:", *rows,
                      "Please confirm which is right and send a corrected document. "
                      "Delivery is on hold until they match."])


def request_correction(merchant_id: UUID, deal_ref: str, actor: str, engine: Engine | None = None) -> dict[str, Any]:
    """Record one request for the current invoice. Sends nothing: the seller passes it on and agents read it."""
    with tenant_session(merchant_id, engine or app_engine()) as s:
        row = s.execute(text(_DEAL_SELECT + " WHERE d.deal_ref = :ref FOR UPDATE OF d"),
                        {"rule": RULE_VERSION, "ref": deal_ref}).first()
        if row is None:
            raise DealError("DEAL_NOT_FOUND", 404)
        if row.status != DealStatus.HOLD:
            raise DealError("DEAL_NOT_ON_HOLD", 409)
        if row.correction_message is None:
            s.execute(text("""INSERT INTO deal_corrections (merchant_id, deal_id, invoice_revision, message,
                                                            requested_by)
                              VALUES (:m, :d, :rev, :message, :actor)"""),
                      {"m": merchant_id, "d": row.id, "rev": row.invoice_revision, "actor": actor,
                       "message": correction_message(deal_ref, row.invoice["invoice_ref"], row.findings)})
            repo.write_audit(s, merchant_id, actor, "deal.correction_requested", target=deal_ref,
                             summary={"revision": row.invoice_revision})
    return get_deal(merchant_id, deal_ref, engine)


def _deal_view(row: Any, findings: list[dict[str, Any]]) -> dict[str, Any]:
    correction = None
    if row.correction_message is not None:
        correction = {"message": row.correction_message, "requested_at": row.correction_requested_at.isoformat()}
    return {"deal_ref": row.deal_ref, "category": row.category, "status": row.status,
            "purchase_order": row.purchase_order, "invoice": row.invoice, "findings": findings,
            "correction": correction, "updated_at": row.updated_at.isoformat()}


# Findings and request of the current invoice only, so an old revision's are never shown beside a new invoice.
_DEAL_SELECT = """
    SELECT d.id, d.deal_ref, d.category, d.status, d.purchase_order, d.invoice, d.invoice_revision, d.updated_at,
           coalesce(c.findings, '[]'::jsonb) AS findings,
           r.message AS correction_message, r.requested_at AS correction_requested_at
    FROM deals d
    LEFT JOIN deal_checks c ON c.deal_id = d.id AND c.invoice_revision = d.invoice_revision
                               AND c.rule_version = :rule AND d.status IN ('HOLD', 'CLEAR')
    LEFT JOIN deal_corrections r ON r.deal_id = d.id AND r.invoice_revision = d.invoice_revision
"""


def get_deal(merchant_id: UUID, deal_ref: str, engine: Engine | None = None,
             ordered_by: UUID | None = None) -> dict[str, Any]:
    """`ordered_by` limits the answer to that agent's own orders."""
    with tenant_session(merchant_id, engine or app_engine()) as s:
        where = " WHERE d.deal_ref = :ref AND (CAST(:by AS uuid) IS NULL OR d.ordered_by = :by)"
        row = s.execute(text(_DEAL_SELECT + where), {"rule": RULE_VERSION, "ref": deal_ref, "by": ordered_by}).first()
    if row is None:
        raise DealError("DEAL_NOT_FOUND", 404)
    return _deal_view(row, row.findings)


def get_deal_as(agent: AgentIdentity, deal_ref: str, engine: Engine | None = None) -> dict[str, Any]:
    """A seller's agent sees the merchant's deals; a buyer's agent sees only what it ordered."""
    ordered_by = agent.id if agent.role is AgentRole.BUYER_AGENT else None
    return get_deal(agent.merchant_id, deal_ref, engine, ordered_by)


def list_deals(merchant_id: UUID, engine: Engine | None = None) -> list[dict[str, Any]]:
    with tenant_session(merchant_id, engine or app_engine()) as s:
        rows = s.execute(text(_DEAL_SELECT + " ORDER BY d.updated_at DESC LIMIT 200"), {"rule": RULE_VERSION}).all()
    return [_deal_view(r, r.findings) for r in rows]
