"""Agent action proposals (ADR-006): what SAL suggests the merchant does next, one card per step.

Cards come from deterministic rules over the latest assessment, the dispute's PayPal state and the merchant's
Transaction Search history, never from free model output, so each card can be explained and tested. Two cards
lead to a PayPal write, and only after the merchant approves them: SEND_EVIDENCE through submission.submit(), and
OFFER_REFUND through make-offer with the amount the merchant typed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from app.agent.assess import SUPPORTED_REASONS as ARGUED_REASONS
from app.db import tenant_session

DEADLINE_WINDOW = timedelta(hours=72)
SENDABLE_DRAFT = {"DRAFT", "APPROVED", "SUBMIT_FAILED"}
SENT = {"SUBMITTING", "SUBMITTED"}

# The document that proves each proposition, in the merchant's words.
PROOF_DOCUMENT = {
    "payment_matches": "the PayPal payment record",
    "shipped": "courier tracking",
    "delivered": "proof of delivery",
    "delivered_to_paypal_address": "a proof of delivery that shows the delivery address",
}
PROVEN_WORDS = {"payment_matches": "payment", "shipped": "shipping", "delivered": "delivery",
                "delivery_date_consistent": "the delivery date", "buyer_messages_clean": "clean buyer messages",
                "paypal_request_covered": "what PayPal asked for",
                "delivered_to_paypal_address": "the delivery address"}

# Transaction Search hold codes and the code that releases each (PayPal event code reference).
HOLDS = {"T1110": "dispute", "T2107": "payment", "T2103": "reserve", "T2105": "review"}
RELEASES = {"T1111": "T1110", "T2108": "T2107", "T2104": "T2103", "T2106": "T2105"}
HOLD_REASON = {
    "dispute": "PayPal holds this money while the buyer's dispute is open. It is released when the dispute "
               "closes in your favour.",
    "payment": "PayPal is holding this payment, as it does for newer sellers or unusual sales. Adding tracking "
               "and delivery helps it release sooner; holds usually last up to 21â€“30 days depending on your country.",
    "reserve": "PayPal keeps this part of your sales as a reserve and releases it on its own schedule.",
    "review": "PayPal is reviewing this payment before releasing it.",
}


@dataclass(frozen=True)
class DisputeState:
    id: UUID
    origin: str
    provider_status: str
    deadline_at: datetime | None
    allowed_actions: tuple[str, ...]
    amount: str
    currency: str
    reason: str = "ITEM_NOT_RECEIVED"
    lifecycle_stage: str | None = None   # PayPal's stage: INQUIRY, CHARGEBACK, ...
    packing_photos: int = 0              # photos from a packing record attached to the case (ADR-007)
    offer_types: tuple[str, ...] = ()    # PayPal's allowed_response_options.make_offer.offer_types
    channel: str | None = None           # EXTERNAL: the buyer went to their bank (a real chargeback)

    @property
    def bank_chargeback(self) -> bool:
        # PayPal's CHARGEBACK *stage* is a claim PayPal itself decides; only the EXTERNAL channel is the bank.
        return self.channel == "EXTERNAL"


@dataclass(frozen=True)
class AnalysisState:
    readiness: str
    snapshot_hash: str
    propositions: list[dict[str, Any]]


@dataclass(frozen=True)
class DraftState:
    id: UUID
    revision: int
    status: str


@dataclass(frozen=True)
class Proposal:
    kind: str
    subject_key: str
    title: str
    rationale: str
    payload: dict[str, Any]
    sources: list[dict[str, Any]] = field(default_factory=list)
    due_at: datetime | None = None

    @property
    def payload_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.payload, sort_keys=True).encode()).hexdigest()


def _hours_left(deadline: datetime, now: datetime) -> int:
    return max(1, int((deadline - now).total_seconds() // 3600))


def propose_for_dispute(d: DisputeState, analysis: AnalysisState | None, draft: DraftState | None,
                        now: datetime) -> list[Proposal]:
    """Cards for one dispute, most urgent first. Nothing once PayPal resolved it or the reply was sent."""
    if d.provider_status == "RESOLVED" or (draft is not None and draft.status in SENT):
        return []
    subject = f"dispute:{d.id}"
    cards: list[Proposal] = []
    if d.deadline_at is not None and now < d.deadline_at <= now + DEADLINE_WINDOW:
        hours = _hours_left(d.deadline_at, now)
        cards.append(Proposal(
            "REPLY_BEFORE_DEADLINE", subject, f"Reply to PayPal within {hours} hours",
            f"PayPal needs your reply by {d.deadline_at:%d %b %Y, %H:%M} UTC. Without it, the case can be "
            "decided without your evidence.",
            payload={"deadline_at": d.deadline_at.isoformat()}, due_at=d.deadline_at))
    if d.reason not in ARGUED_REASONS:  # SAL argues with shipping evidence only; for the rest it explains
        cards.append(_explain_dispute(d, subject))
        if _can_offer_refund(d):
            cap = f"{Decimal(d.amount):.2f}"   # the column keeps 4 decimals; offers are in cents
            cards.append(Proposal(
                "OFFER_REFUND", subject, "Offer the buyer a refund",
                f"You choose the amount, up to {cap} {d.currency}; the buyer keeps the item. PayPal shows the "
                "offer to the buyer, who can accept or decline. If they accept, PayPal refunds that amount and the "
                "case closes. SAL sends the offer only after you approve. For a refund after a return, use PayPal.",
                payload={"offer_type": "REFUND", "max_amount": cap, "currency": d.currency},
                due_at=d.deadline_at))
        return cards
    if analysis is None:
        return cards
    if d.origin == "PAYPAL_SANDBOX" and "provide_evidence" not in d.allowed_actions:
        # PayPal is not taking documents now (e.g. under review), so asking for an upload would be a dead end.
        stage = "chargeback" if d.bank_chargeback else "claim" if d.lifecycle_stage == "CHARGEBACK" else "case"
        cards.append(Proposal(
            "EXPLAIN_DISPUTE", subject, "PayPal is reviewing this case",
            f"PayPal is not accepting documents on this {stage} right now. SAL keeps checking and adds a suggestion "
            "as soon as PayPal asks for something.",
            payload={"waiting": "provide_evidence", "status": d.provider_status, "stage": d.lifecycle_stage},
            due_at=d.deadline_at))
        return cards

    by_id = {p["id"]: p for p in analysis.propositions}
    if d.bank_chargeback:
        return cards + _chargeback_cards(d, analysis, draft, subject, by_id)
    if analysis.readiness in ("NEEDS_DOCUMENTS", "WEAK"):
        missing = [p["id"] for p in analysis.propositions
                   if p["status"] == "missing" and p["id"] in PROOF_DOCUMENT]
        if missing:
            cards.append(Proposal(
                "ADD_DOCUMENT", subject, f"Add {PROOF_DOCUMENT[missing[0]]}",
                f"{by_id[missing[0]]['reason']}. Upload it and SAL checks the case again.",
                payload={"missing": missing}, due_at=d.deadline_at))
    elif (analysis.readiness == "READY" and draft is not None and draft.status in SENDABLE_DRAFT
          and "provide_evidence" in d.allowed_actions and d.origin == "PAYPAL_SANDBOX"):
        proven = [p for p in analysis.propositions if p["status"] == "proven"]
        cards.append(Proposal(
            "SEND_EVIDENCE", subject, "Send your evidence to PayPal",
            "Your documents prove " + ", ".join(PROVEN_WORDS.get(p["id"], p["id"]) for p in proven)
            + "." + _packing_note(d) + " SAL sends them only after you approve.",
            payload={"draft_id": str(draft.id), "revision": draft.revision, "snapshot_hash": analysis.snapshot_hash},
            sources=[s for p in proven for s in p.get("sources", [])], due_at=d.deadline_at))
    return cards


# PayPal's Seller Protection still covers some chargebacks (unauthorized ones with proof of delivery) and not
# others ("not received" chargebacks since 16 Jan 2024 in the US), and the terms differ by country.
CHARGEBACK_NOTE = ("This case is now a chargeback: the buyer's bank decides, not PayPal, and PayPal Seller "
                   "Protection may not cover it, depending on the reason and your country.")


def _chargeback_cards(d: DisputeState, analysis: AnalysisState, draft: DraftState | None, subject: str,
                      by_id: dict[str, dict[str, Any]]) -> list[Proposal]:
    """A chargeback is argued with the same evidence, but a bank weighs it, so SAL asks for more before sending:
    the courier's delivery date and a proof of delivery that agree (delivery_date_consistent proven), not only a
    DELIVERED status."""
    missing = [pid for pid, p in by_id.items() if p["status"] == "missing" and pid in PROOF_DOCUMENT]
    if analysis.readiness in ("NEEDS_DOCUMENTS", "WEAK") and missing:
        why = by_id[missing[0]]["reason"]
        return [Proposal("ADD_DOCUMENT", subject, f"Add {PROOF_DOCUMENT[missing[0]]} for the chargeback",
                         f"{CHARGEBACK_NOTE} {why}. Upload it and SAL checks the case again.",
                         payload={"missing": missing, "stage": "CHARGEBACK"}, due_at=d.deadline_at)]
    pod_checked = by_id.get("delivery_date_consistent", {}).get("status") == "proven"
    if analysis.readiness == "READY" and not pod_checked:   # READY for PayPal, not yet for a bank
        return [Proposal("ADD_DOCUMENT", subject, "Add proof of delivery for the chargeback",
                         f"{CHARGEBACK_NOTE} A courier status alone is weaker in front of a bank: add the proof of "
                         "delivery with its date, so SAL can check it against the courier's. Upload it and SAL checks "
                         "the case again.",
                         payload={"missing": ["delivered"], "stage": "CHARGEBACK"}, due_at=d.deadline_at)]
    if (analysis.readiness == "READY" and draft is not None and draft.status in SENDABLE_DRAFT
            and "provide_evidence" in d.allowed_actions and d.origin == "PAYPAL_SANDBOX"):
        proven = [p for p in by_id.values() if p["status"] == "proven"]
        return [Proposal(
            "SEND_EVIDENCE", subject, "Send your chargeback evidence to PayPal",
            f"{CHARGEBACK_NOTE} Your documents prove "
            + ", ".join(PROVEN_WORDS.get(p["id"], p["id"]) for p in proven)
            + "." + _packing_note(d) + " PayPal passes them to the bank; SAL sends them only after you approve.",
            payload={"draft_id": str(draft.id), "revision": draft.revision, "snapshot_hash": analysis.snapshot_hash,
                     "stage": "CHARGEBACK"},
            sources=[s for p in proven for s in p.get("sources", [])], due_at=d.deadline_at)]
    return []


def _packing_note(d: DisputeState) -> str:
    return f" Your {d.packing_photos} packing photo(s) go with them." if d.packing_photos else ""


def _can_offer_refund(d: DisputeState) -> bool:
    """PayPal takes offers only in the inquiry stage; a plain REFUND needs no return address from the seller."""
    return ("NOT_AS_DESCRIBED" in d.reason and d.origin == "PAYPAL_SANDBOX" and d.lifecycle_stage == "INQUIRY"
            and "make_offer" in d.allowed_actions and "REFUND" in d.offer_types)


def _explain_dispute(d: DisputeState, subject: str) -> Proposal:
    if "NOT_AS_DESCRIBED" in d.reason:
        title = "The buyer says the item is not as described"
        why = ("SAL only builds replies for parcels that did not arrive, and PayPal Seller Protection does not cover "
               "'not as described' claims. Realistic choices in PayPal: offer a partial refund, a full refund, or "
               "a refund after the buyer returns the item. SAL will not argue this case for you.")
        why += (f" Your packing record ({d.packing_photos} photo(s), recorded before shipping) is on the case: it "
                "shows what you packed, which helps your answer in PayPal, but PayPal decides."
                if d.packing_photos else
                " Next time, record the parcel in SAL before shipping (Packing proof) so you have photos to show.")
    else:
        title = "SAL can't prepare a reply for this kind of dispute"
        why = ("SAL only builds replies for parcels that did not arrive. Read the buyer's claim in PayPal and answer "
               "it there.")
    return Proposal("EXPLAIN_DISPUTE", subject, title, why, payload={"reason": d.reason}, due_at=d.deadline_at)


def holds_from_transactions(details: list[dict[str, Any]], now: datetime) -> list[Proposal]:
    """Money PayPal is still holding, from Transaction Search rows: a hold code with no matching release for the
    same original payment. One card per payment and hold type, whatever duplicates the search returns."""
    held: dict[tuple[str, str], dict[str, Any]] = {}
    released: set[tuple[str, str]] = set()
    for row in details:
        info = row.get("transaction_info") or {}
        code = info.get("transaction_event_code")
        ref = info.get("paypal_reference_id") or info.get("transaction_id")
        if code in HOLDS:
            held.setdefault((ref, code), info)
        elif code in RELEASES:
            released.add((ref, RELEASES[code]))
    cards = []
    for (ref, code), info in sorted(held.items()):
        if (ref, code) in released:
            continue
        amount = info.get("transaction_amount") or {}
        value = str(abs(Decimal(amount.get("value", "0"))).quantize(Decimal("0.01")))
        currency = amount.get("currency_code", "")
        kind = HOLDS[code]
        cards.append(Proposal(
            "EXPLAIN_HELD_FUNDS", f"hold:{ref}:{code}", f"{value} {currency} is on hold",
            f"{HOLD_REASON[kind]} PayPal's records as of {now:%d %b %Y, %H:%M} UTC.",
            payload={"payment_id": ref, "hold_transaction_id": info.get("transaction_id"), "event_code": code,
                     "hold": kind, "amount": value, "currency": currency},
            sources=[{"transaction_id": info.get("transaction_id"), "event_code": code}]))
    return cards


def save(merchant_id: UUID, subject_key: str, dispute_id: UUID | None, proposals: list[Proposal],
         engine: Engine | None = None) -> dict[str, int]:
    """Make the open cards for one subject match `proposals`. An identical card stays as it is (its id and
    timestamp too); a changed or no-longer-proposed one is SUPERSEDED; a new one is inserted. Worker only."""
    wanted = {p.kind: p for p in proposals}
    kept = superseded = inserted = 0
    with tenant_session(merchant_id, engine) as s:
        open_rows = s.execute(text("""SELECT id, kind, payload_hash FROM agent_actions
                                      WHERE subject_key = :k AND status = 'PROPOSED' FOR UPDATE"""),
                              {"k": subject_key}).all()
        for row in open_rows:
            new = wanted.get(row.kind)
            if new is not None and new.payload_hash == row.payload_hash:
                # Same decision, so the card (and an approval bound to its hash) stays; only the wording may improve.
                s.execute(text("UPDATE agent_actions SET title = :t, rationale = :r WHERE id = :id"),
                          {"t": new.title, "r": new.rationale, "id": row.id})
                wanted.pop(row.kind)
                kept += 1
                continue
            s.execute(text("UPDATE agent_actions SET status = 'SUPERSEDED', decided_at = now() WHERE id = :id"),
                      {"id": row.id})
            superseded += 1
        decided = set(s.execute(text("""SELECT kind, payload_hash FROM agent_actions
                                        WHERE subject_key = :k AND status IN ('DONE', 'DISMISSED')"""),
                                {"k": subject_key}).all())
        for p in wanted.values():
            if (p.kind, p.payload_hash) in decided:  # the merchant already answered this exact card
                kept += 1
                continue
            s.execute(text("""
                INSERT INTO agent_actions (merchant_id, dispute_id, kind, subject_key, title, rationale, sources,
                                           payload, payload_hash, due_at)
                VALUES (:m, :d, :kind, :k, :title, :why, CAST(:sources AS jsonb), CAST(:payload AS jsonb),
                        :h, :due)"""),
                {"m": merchant_id, "d": dispute_id, "kind": p.kind, "k": p.subject_key, "title": p.title,
                 "why": p.rationale, "sources": json.dumps(p.sources), "payload": json.dumps(p.payload),
                 "h": p.payload_hash, "due": p.due_at})
            inserted += 1
    return {"kept": kept, "superseded": superseded, "inserted": inserted}


# ---------------------------------------------------------------- worker: proposing for a dispute
def refresh_dispute(merchant_id: UUID, dispute_id: UUID, now: datetime, engine: Engine | None = None) -> dict[str, Any]:
    """Recompute the open cards for one dispute from its current PayPal state, analysis and draft. Worker only."""
    with tenant_session(merchant_id, engine) as s:
        d = s.execute(text("""SELECT id, origin, provider_status, deadline_at, allowed_actions, amount, currency,
                                     reason, lifecycle_stage,
                                     provider_payload #> '{allowed_response_options,make_offer,offer_types}' AS offers,
                                     provider_payload ->> 'dispute_channel' AS channel
                              FROM disputes WHERE id = :d"""), {"d": dispute_id}).first()
        if d is None:
            return {"skipped": "dispute not found"}
        a = s.execute(text("""SELECT id, assessment, snapshot_hash FROM analyses WHERE dispute_id = :d
                              ORDER BY created_at DESC LIMIT 1"""), {"d": dispute_id}).first()
        # A sync after the send re-analyses and adds a fresh DRAFT revision; while PayPal is not asking for
        # evidence again, the sent revision is the one that counts, so the case stays "sent" with no new card.
        dr = s.execute(text("""SELECT id, revision, status FROM drafts WHERE dispute_id = :d
                               ORDER BY (status IN ('SUBMITTING', 'SUBMITTED') AND NOT :asks) DESC, revision DESC
                               LIMIT 1"""),
                       {"d": dispute_id, "asks": "provide_evidence" in (d.allowed_actions or ())}).first()
        photos = s.execute(text("""SELECT count(*) FROM evidence WHERE dispute_id = :d AND doc_type = 'packing_proof'
                                   AND mime LIKE 'image/%'"""), {"d": dispute_id}).scalar()
    state = DisputeState(d.id, d.origin, d.provider_status, d.deadline_at, tuple(d.allowed_actions or ()),
                         str(d.amount), d.currency, d.reason, d.lifecycle_stage, photos, tuple(d.offers or ()),
                         d.channel)
    analysis = (AnalysisState(a.assessment["readiness"], a.snapshot_hash, a.assessment.get("propositions", []))
                if a is not None and a.assessment else None)
    draft = DraftState(dr.id, dr.revision, dr.status) if dr is not None else None
    proposals = propose_for_dispute(state, analysis, draft, now)
    return save(merchant_id, f"dispute:{dispute_id}", dispute_id, proposals, engine)


def scan_holds(merchant_id: UUID, details: list[dict[str, Any]], now: datetime,
               engine: Engine | None = None) -> dict[str, int]:
    """Make the open held-funds cards match PayPal's Transaction Search rows: a card per payment still held,
    and the card of a hold PayPal has since released is superseded. Worker only."""
    cards = holds_from_transactions(details, now)
    with tenant_session(merchant_id, engine) as s:
        open_subjects = set(s.execute(text("""SELECT DISTINCT subject_key FROM agent_actions
                                              WHERE kind = 'EXPLAIN_HELD_FUNDS' AND status = 'PROPOSED'""")
                                      ).scalars())
    totals = {"holds": len(cards), "kept": 0, "superseded": 0, "inserted": 0}
    by_subject = {c.subject_key: [c] for c in cards}
    for subject in sorted(open_subjects | set(by_subject)):
        for key, n in save(merchant_id, subject, None, by_subject.get(subject, []), engine).items():
            totals[key] += n
    return totals


def refresh_open_disputes(merchant_id: UUID, now: datetime, engine: Engine | None = None) -> dict[str, int]:
    """Re-propose for every open dispute. Cards change with time as well as with events: a deadline that comes
    within 72 hours needs a reply card even if nothing else happened. Worker only."""
    with tenant_session(merchant_id, engine) as s:
        ids = s.execute(text("""SELECT id FROM disputes WHERE provider_status IS DISTINCT FROM 'RESOLVED'
                                ORDER BY deadline_at NULLS LAST""")).scalars().all()
    totals = {"disputes": len(ids), "kept": 0, "superseded": 0, "inserted": 0}
    for dispute_id in ids:
        for key, n in refresh_dispute(merchant_id, dispute_id, now, engine).items():
            if key in totals:
                totals[key] += n
    return totals


def queue_refresh(session, merchant_id: UUID, dispute_id: UUID, reason: str) -> None:
    """Ask the worker to re-propose cards for a dispute; `reason` keeps the job key unique per cause."""
    from app import repositories as repo
    repo.enqueue_job(session, merchant_id, "propose_actions", f"actions:{dispute_id}:{reason}", dispute_id)


# ---------------------------------------------------------------- API: the merchant decides
class ActionError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code = status, code


ACTION_COLUMNS = """id, dispute_id, kind, status, title, rationale, sources, payload, payload_hash, due_at,
                    created_at, decided_at, result"""


def list_actions(merchant_id: UUID, status: str = "PROPOSED", dispute_id: UUID | None = None,
                 engine: Engine | None = None) -> list[dict[str, Any]]:
    with tenant_session(merchant_id, engine) as s:
        rows = s.execute(text(f"""SELECT {ACTION_COLUMNS} FROM agent_actions
                                  WHERE status = :st AND (CAST(:d AS uuid) IS NULL OR dispute_id = :d)
                                  ORDER BY due_at ASC NULLS LAST, created_at DESC LIMIT 100"""),
                         {"st": status, "d": dispute_id}).all()
    return [dict(r._mapping) for r in rows]


def _claim(merchant_id: UUID, action_id: UUID, payload_hash: str | None, to: str, actor: str,
           engine: Engine | None, check: Any = None) -> Any:
    """Atomically move one PROPOSED card to `to`. Only the first of two simultaneous decisions wins.
    `check(row)` may raise ActionError to refuse the decision while the card stays open (e.g. a bad amount)."""
    from app import repositories as repo
    with tenant_session(merchant_id, engine) as s:
        row = s.execute(text(f"SELECT {ACTION_COLUMNS} FROM agent_actions WHERE id = :id FOR UPDATE"),
                        {"id": action_id}).first()
        if row is None:
            raise ActionError(404, "ACTION_NOT_FOUND", "Action not found")
        if row.status != "PROPOSED":
            raise ActionError(409, "ACTION_NOT_OPEN", f"This suggestion is already {row.status.lower()}")
        if payload_hash is not None and payload_hash != row.payload_hash:
            raise ActionError(409, "STALE_ACTION", "The suggestion changed since you opened it; review it again")
        if check is not None:
            check(row)
        s.execute(text("""UPDATE agent_actions SET status = :to, decided_by = :actor, decided_at = now()
                          WHERE id = :id"""), {"to": to, "actor": actor, "id": action_id})
        repo.write_audit(s, merchant_id, actor, f"action.{to.lower()}", target=str(action_id),
                         summary={"kind": row.kind, "payload_hash": row.payload_hash})
    return row


def _finish(merchant_id: UUID, action_id: UUID, status: str, result: dict[str, Any],
            engine: Engine | None) -> None:
    with tenant_session(merchant_id, engine) as s:
        s.execute(text("UPDATE agent_actions SET status = :st, result = CAST(:r AS jsonb) WHERE id = :id"),
                  {"st": status, "r": json.dumps(result), "id": action_id})


def dismiss(merchant_id: UUID, action_id: UUID, actor: str, engine: Engine | None = None) -> dict[str, Any]:
    _claim(merchant_id, action_id, None, "DISMISSED", actor, engine)
    return {"id": str(action_id), "status": "DISMISSED"}


def approve(merchant_id: UUID, action_id: UUID, payload_hash: str, actor: str, paypal: Any,
            engine: Engine | None = None, offer_amount: str | None = None) -> dict[str, Any]:
    """The merchant approves one card. Guidance cards just close; SEND_EVIDENCE approves the exact draft revision
    the card names and sends it through submission (ADR-003: bound to the evidence, at most once); OFFER_REFUND
    sends one refund offer of the amount the merchant typed."""
    from app import submission
    row = _claim(merchant_id, action_id, payload_hash, "APPROVED", actor, engine,
                 check=lambda r: _offer_amount(r, offer_amount) if r.kind == "OFFER_REFUND" else None)
    if row.kind == "OFFER_REFUND":
        return _send_offer(merchant_id, row, _offer_amount(row, offer_amount), actor, paypal, engine)
    if row.kind != "SEND_EVIDENCE":
        _finish(merchant_id, action_id, "DONE", {"outcome": "acknowledged"}, engine)
        return {"id": str(action_id), "status": "DONE", "kind": row.kind}
    draft_id = UUID(row.payload["draft_id"])
    try:
        with tenant_session(merchant_id, engine) as s:
            draft_status = s.execute(text("SELECT status FROM drafts WHERE id = :id"), {"id": draft_id}).scalar()
        if draft_status == "DRAFT":
            submission.approve(merchant_id, draft_id, row.payload["revision"], row.payload["snapshot_hash"], actor,
                               engine)
        sent = submission.submit(merchant_id, draft_id, actor, paypal, engine)
    except submission.SubmissionError as exc:
        if exc.code == "SUBMIT_UNCONFIRMED":  # may have reached PayPal; reconcile settles it, never resend
            _finish(merchant_id, action_id, "DONE", {"outcome": "unconfirmed", "code": exc.code}, engine)
        else:
            _finish(merchant_id, action_id, "FAILED", {"outcome": "failed", "code": exc.code, "message": str(exc)},
                    engine)
        raise ActionError(exc.status, exc.code, str(exc)) from None
    _finish(merchant_id, action_id, "DONE", {"outcome": "sent", "files": sent.get("files")}, engine)
    return {"id": str(action_id), "status": "DONE", "kind": row.kind, "sent": sent}


# ---------------------------------------------------------------- OFFER_REFUND: the one offer the merchant typed
OFFER_NOTE = "The seller offers a refund of {amount} {currency} to resolve this case. You keep the item."


def _offer_amount(row: Any, typed: str | None) -> Decimal:
    """The merchant's amount: 0.01 up to the disputed amount the card showed, in cents."""
    cap, currency = Decimal(row.payload["max_amount"]), row.payload["currency"]
    refuse = ActionError(422, "BAD_OFFER_AMOUNT", f"Enter an amount between 0.01 and {cap} {currency}.")
    try:
        amount = Decimal((typed or "").strip().replace(",", "."))
    except InvalidOperation:
        raise refuse from None
    if not amount.is_finite() or amount <= 0 or amount > cap or amount != amount.quantize(Decimal("0.01")):
        raise refuse
    return amount.quantize(Decimal("0.01"))


def _send_offer(merchant_id: UUID, row: Any, amount: Decimal, actor: str, paypal: Any,
                engine: Engine | None) -> dict[str, Any]:
    """Re-read the live dispute (PayPal may have moved on since the card), then send one make-offer. A timeout
    after sending is recorded as unconfirmed, never retried: the next sync shows whether the offer arrived."""
    import httpx

    from app import repositories as repo
    currency = row.payload["currency"]
    with tenant_session(merchant_id, engine) as s:
        provider_id = s.execute(text("SELECT provider_dispute_id FROM disputes WHERE id = :d"),
                                {"d": row.dispute_id}).scalar()

    def fail(status: int, code: str, message: str, outcome: str = "failed") -> ActionError:
        _finish(merchant_id, row.id, "DONE" if outcome == "unconfirmed" else "FAILED",
                {"outcome": outcome, "code": code, "message": message}, engine)
        return ActionError(status, code, message)

    try:
        live = paypal.get(provider_id)
    except Exception:
        raise fail(502, "PAYPAL_UNREACHABLE", "PayPal could not be reached. Nothing was sent.") from None
    offers = ((live.get("allowed_response_options") or {}).get("make_offer") or {}).get("offer_types") or []
    if ("make_offer" not in {link.get("rel") for link in live.get("links", [])} or "REFUND" not in offers
            or live.get("dispute_life_cycle_stage") != "INQUIRY"):
        raise fail(409, "OFFER_NOT_AVAILABLE", "PayPal no longer takes a refund offer on this case. Nothing was sent.")
    payload = {"note": OFFER_NOTE.format(amount=amount, currency=currency), "offer_type": "REFUND",
               "offer_amount": {"currency_code": currency, "value": str(amount)}}
    try:
        paypal.make_offer(provider_id, payload)
    except httpx.HTTPStatusError as exc:
        raise fail(502, "PAYPAL_REJECTED", f"PayPal refused the offer ({exc.response.status_code}).") from None
    except Exception:
        raise fail(502, "OFFER_UNCONFIRMED", "PayPal did not answer in time; SAL will check whether the offer arrived.",
                   "unconfirmed") from None
    with tenant_session(merchant_id, engine) as s:
        repo.write_audit(s, merchant_id, actor, "paypal.make_offer", target=str(row.dispute_id),
                         summary={"action_id": str(row.id), "offer_type": "REFUND", "amount": str(amount),
                                  "currency": currency})
    _finish(merchant_id, row.id, "DONE", {"outcome": "offer_sent", "amount": str(amount), "currency": currency},
            engine)
    return {"id": str(row.id), "status": "DONE", "kind": row.kind, "offer": {"amount": str(amount), "currency": currency}}