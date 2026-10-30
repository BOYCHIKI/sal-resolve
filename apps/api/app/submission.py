"""Human approval and submission of a draft to PayPal (SAL v1.0 §8, v1.1 D4, ADR-003).

approve():   one transaction — lock the draft, check it is the latest DRAFT revision of the current
             analysis and that the operator saw the same snapshot hash, record the approval together
             with the exact set of documents on the case.
submit():    PayPal Sandbox disputes only. Refuses if documents changed since approval, claims the draft
             atomically (APPROVED -> SUBMITTING) so it can never be sent twice, checks PayPal still offers
             provide_evidence, sends one evidence entry with the documents, then records SUBMITTED,
             SUBMIT_FAILED (PayPal said no), or leaves SUBMITTING when the outcome is unknown (timeout).
reconcile(): run by the worker shortly after every send. Asks PayPal whether seller evidence arrived and
             settles a draft still in SUBMITTING. It never sends anything.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import httpx
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app import carriers
from app.actions import queue_refresh
from app import repositories as repo
from app.db import tenant_session
from app.config import get_settings
from app.evidence import read_file
from app.evidence_pdf import render_text_pdf

RECONCILE_AFTER_SECONDS = 120
CLOCK_SKEW = timedelta(minutes=5)


class SubmissionError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code = status, code


class EvidenceSink(Protocol):
    def get(self, dispute_id: str) -> dict[str, Any]: ...
    def provide_evidence(self, dispute_id: str, payload: dict[str, Any],
                         files: list[tuple[str, bytes, str]]) -> dict[str, Any]: ...


def _hash_checksums(checksums) -> str:
    return hashlib.sha256("\n".join(sorted(checksums)).encode()).hexdigest()


def _evidence_hash(s: Session, dispute_id: UUID) -> str:
    """The set of documents on the dispute, independent of upload order."""
    checksums = s.execute(text("SELECT checksum FROM evidence WHERE dispute_id = :d"), {"d": dispute_id}).scalars().all()
    return _hash_checksums(checksums)


def approve(merchant_id: UUID, draft_id: UUID, revision: int, snapshot_hash: str, actor: str,
            engine: Engine | None = None) -> dict[str, Any]:
    with tenant_session(merchant_id, engine) as s:
        row = s.execute(text("""
            SELECT d.id, d.dispute_id, d.revision, d.status, d.payload_hash, a.snapshot_hash, a.dispute_version,
                   p.version AS current_version,
                   (SELECT max(revision) FROM drafts x WHERE x.dispute_id = d.dispute_id) AS latest_revision
            FROM drafts d
            JOIN analyses a ON a.id = d.analysis_id
            JOIN disputes p ON p.id = d.dispute_id
            WHERE d.id = :id
            FOR UPDATE OF d, p"""), {"id": draft_id}).first()
        if row is None:
            raise SubmissionError(404, "DRAFT_NOT_FOUND", "Draft not found")
        if row.status != "DRAFT":
            raise SubmissionError(409, "DRAFT_NOT_PENDING", f"Draft is {row.status.lower()}, not awaiting approval")
        if revision != row.revision or row.revision != row.latest_revision:
            raise SubmissionError(409, "STALE_REVISION", "A newer draft revision exists; review it instead")
        if snapshot_hash != row.snapshot_hash:
            raise SubmissionError(409, "STALE_SNAPSHOT", "The analysis changed since you reviewed it")
        if row.dispute_version != row.current_version:
            raise SubmissionError(409, "DISPUTE_CHANGED", "The dispute changed after this analysis; wait for re-analysis")

        s.execute(text("""INSERT INTO approvals (merchant_id, draft_id, revision, payload_hash, snapshot_hash, actor,
                                                 evidence_hash)
                          VALUES (:m, :d, :r, :ph, :sh, :actor, :eh)"""),
                  {"m": merchant_id, "d": draft_id, "r": row.revision, "ph": row.payload_hash,
                   "sh": row.snapshot_hash, "actor": actor, "eh": _evidence_hash(s, row.dispute_id)})
        s.execute(text("UPDATE drafts SET status = 'APPROVED' WHERE id = :id"), {"id": draft_id})
        s.execute(text("UPDATE disputes SET internal_state = 'APPROVED', updated_at = now() WHERE id = :d"),
                  {"d": row.dispute_id})
        repo.write_audit(s, merchant_id, actor, "draft.approved", target=str(draft_id),
                         summary={"revision": row.revision, "snapshot_hash": row.snapshot_hash})
    return {"draft_id": str(draft_id), "status": "APPROVED", "revision": row.revision}


# PayPal may ask for several types at once, but only one entry can be sent, so it must be one the documents back.
# These describe something the seller did, not what the courier documents show, so SAL never sends under them.
NOT_SHIPPING_EVIDENCE = {"PROOF_OF_REFUND", "PROOF_OF_RETURN"}


def _evidence_type(requested: list[str]) -> str:
    usable = [t for t in requested if t not in NOT_SHIPPING_EVIDENCE]
    return "PROOF_OF_FULFILLMENT" if "PROOF_OF_FULFILLMENT" in usable or not usable else usable[0]


def _payload(claims: list[dict[str, Any]], facts: list[dict[str, Any]], requested: list[str],
             tracking_lines: list[str] = ()) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "evidence_type": _evidence_type(requested),
        "notes": " ".join(c["text"] for c in claims)[:2000],
    }
    tracking = [f["value"] for f in facts if f["field"] == "tracking_id" and f["status"] == "supported"]
    if tracking:
        # The real courier code lets PayPal follow the parcel; "OTHER" only when the document names none we know.
        entry["evidence_info"] = {"tracking_info": [
            carriers.tracking_info(tracking[0], carriers.carrier_for(list(tracking_lines)))]}
    return {"evidences": [entry]}  # one entry: disputes without item_id reject several (spike S6)


EXTENSIONS = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif"}


def _file_for(doc) -> tuple[str, bytes, str] | None:
    """The merchant's original upload when we have it; seeded demo documents are rendered from their text."""
    original = read_file(get_settings().storage_dir, doc.object_key) if doc.object_key else None
    if original is not None:
        return f"{doc.evidence_id}.{EXTENSIONS.get(doc.mime, 'pdf')}", original, doc.mime
    if doc.content_lines:
        pdf = render_text_pdf([f"Evidence {doc.evidence_id}", ""] + [line["text"] for line in doc.content_lines])
        return f"{doc.evidence_id}.pdf", pdf, "application/pdf"
    return None


def submit(merchant_id: UUID, draft_id: UUID, actor: str, paypal: EvidenceSink,
           engine: Engine | None = None) -> dict[str, Any]:
    # 1. Check, claim and gather everything to send, in one short transaction.
    with tenant_session(merchant_id, engine) as s:
        row = s.execute(text("""
            SELECT d.dispute_id, d.claims, a.facts, p.origin, p.provider_dispute_id, p.provider_payload,
                   ap.evidence_hash
            FROM drafts d JOIN analyses a ON a.id = d.analysis_id JOIN disputes p ON p.id = d.dispute_id
            LEFT JOIN approvals ap ON ap.draft_id = d.id
            WHERE d.id = :id"""), {"id": draft_id}).first()
        if row is None:
            raise SubmissionError(404, "DRAFT_NOT_FOUND", "Draft not found")
        if row.origin != "PAYPAL_SANDBOX":
            raise SubmissionError(422, "NOT_A_PAYPAL_DISPUTE", "Synthetic fixtures cannot be sent to PayPal")
        # Read the documents first and hash exactly these rows: what is checked is what is sent, even if an
        # upload commits in the middle of this transaction.
        docs = s.execute(text("""SELECT coalesce(source_ref, id::text) AS evidence_id, content_lines, object_key, mime,
                                        checksum, doc_type
                                 FROM evidence WHERE dispute_id = :d
                                 ORDER BY uploaded_at, source_ref NULLS LAST, id"""), {"d": row.dispute_id}).all()
        if row.evidence_hash is not None and row.evidence_hash != _hash_checksums(d.checksum for d in docs):
            raise SubmissionError(409, "EVIDENCE_CHANGED",
                                  "Documents changed after approval; review and approve the new reply")
        claimed = s.execute(text("""UPDATE drafts SET status = 'SUBMITTING', submit_started_at = now(), submit_note = NULL
                                    WHERE id = :id AND status IN ('APPROVED', 'SUBMIT_FAILED')
                                    RETURNING submit_started_at"""), {"id": draft_id}).first()
        if claimed is None:
            raise SubmissionError(409, "NOT_SUBMITTABLE", "Draft must be approved and not already sent")
        # Safety net for a crash or timeout below: the worker settles this send from PayPal's own record.
        repo.enqueue_job(s, merchant_id, "reconcile_submission",
                         f"reconcile:{draft_id}:{claimed.submit_started_at.isoformat()}", row.dispute_id,
                         payload={"draft_id": str(draft_id)}, delay_seconds=RECONCILE_AFTER_SECONDS)
    requested = [e["evidence_type"] for e in (row.provider_payload or {}).get("evidences") or []
                 if e.get("source") == "REQUESTED_FROM_SELLER"]
    tracking_lines = [line["text"] for d in docs if d.doc_type in ("carrier_tracking", "delivery_proof", "seller_shipment")
                      for line in (d.content_lines or [])]
    payload = _payload(row.claims, row.facts, requested, tracking_lines)
    # A resi the seller typed travels as tracking_info above; it is their word, not a document to attach.
    files = [_file_for(d) for d in docs if d.doc_type != "seller_shipment"]
    files = [f for f in files if f is not None]

    # 2. Network, outside any transaction.
    error, unknown = _send(paypal, row.provider_dispute_id, payload, files)

    # 3. Record the outcome. An unknown outcome stays SUBMITTING for reconcile() to settle.
    with tenant_session(merchant_id, engine) as s:
        if error and unknown:
            s.execute(text("UPDATE drafts SET submit_note = 'UNCONFIRMED' WHERE id = :id AND status = 'SUBMITTING'"),
                      {"id": draft_id})
            repo.write_audit(s, merchant_id, actor, "draft.submit_unconfirmed", target=str(draft_id),
                             summary={"files": len(files), "error": error})
        else:
            _settle(s, merchant_id, draft_id, row.dispute_id, row.provider_dispute_id, actor,
                    sent=error is None, note=None if error is None else "PAYPAL_REJECTED",
                    action="draft.submitted" if error is None else "draft.submit_failed",
                    summary={"files": len(files), "error": error,
                             "evidence_type": payload["evidences"][0]["evidence_type"]})
    if error and unknown:
        raise SubmissionError(504, "SUBMIT_UNCONFIRMED", error)
    if error:
        raise SubmissionError(502, "PAYPAL_REJECTED", error)
    return {"draft_id": str(draft_id), "status": "SUBMITTED", "files": len(files)}


def _send(paypal: EvidenceSink, provider_dispute_id: str, payload: dict[str, Any],
          files: list[tuple[str, bytes, str]]) -> tuple[str | None, bool]:
    """Send once. Returns (error, unknown): unknown means we cannot tell whether PayPal accepted it (a timeout
    or a 5xx), so the caller must not mark it failed. PayPal is re-checked first: it may have stopped
    offering provide_evidence since the operator approved (spike finding)."""
    unknown = False
    try:
        live = paypal.get(provider_dispute_id)
        if "provide_evidence" not in {link.get("rel") for link in live.get("links", [])}:
            return f"PayPal no longer offers provide_evidence (status {live.get('status')})", False
        try:
            paypal.provide_evidence(provider_dispute_id, payload, files)
        except httpx.HTTPStatusError as exc:
            unknown = exc.response.status_code >= 500  # a 4xx is PayPal saying no
            raise
        except Exception:
            unknown = True  # timeout or lost connection: the request may have reached PayPal
            raise
    except Exception as exc:  # noqa: BLE001 — the outcome must be recorded either way
        return f"{type(exc).__name__}: {exc}"[:500], unknown
    return None, False


def _settle(s: Session, merchant_id: UUID, draft_id: UUID, dispute_id: UUID, provider_dispute_id: str,
            actor: str, sent: bool, note: str | None, action: str, summary: dict[str, Any]) -> bool:
    """Record the final outcome of a send exactly once. False if the other path settled it first."""
    done = s.execute(text("""UPDATE drafts SET status = :st, submit_note = :n
                             WHERE id = :id AND status = 'SUBMITTING' RETURNING id"""),
                     {"st": "SUBMITTED" if sent else "SUBMIT_FAILED", "n": note, "id": draft_id}).first()
    if done is None:
        return False
    if sent:
        s.execute(text("UPDATE disputes SET internal_state = 'SUBMITTED', updated_at = now() WHERE id = :d"),
                  {"d": dispute_id})
        # refresh status/actions from PayPal shortly
        repo.enqueue_job(s, merchant_id, "sync_dispute", f"after-submit:{draft_id}",
                         payload={"provider_dispute_id": provider_dispute_id})
    queue_refresh(s, merchant_id, dispute_id, f"settled:{draft_id}:{action}")  # the send card closes (ADR-006)
    repo.write_audit(s, merchant_id, actor, action, target=str(draft_id), summary=summary)
    return True


def _paypal_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def decide(live: dict[str, Any], started_at: datetime) -> tuple[bool, str | None]:
    """(sent, note) for a send that started at started_at, from PayPal's current view of the dispute."""
    since = started_at - CLOCK_SKEW
    # Every accepted provide-evidence adds a SUBMITTED_BY_SELLER entry with its date (sandbox, 2026-10-12).
    for e in live.get("evidences") or []:
        when = _paypal_time(e.get("date"))
        # SAL always attaches files; a seller entry without documents (e.g. an escalation note) is not our send.
        if (e.get("source") == "SUBMITTED_BY_SELLER" and when is not None and when >= since
                and e.get("documents")):
            return True, None
    if "provide_evidence" in {link.get("rel") for link in live.get("links", [])}:
        return False, "NOT_RECEIVED"        # nothing arrived and PayPal still waits: safe to send again
    return False, "NEEDS_MANUAL_CHECK"      # nothing arrived but PayPal moved on: a person must look


def reconcile(merchant_id: UUID, draft_id: UUID, paypal: EvidenceSink, engine: Engine | None = None) -> dict[str, Any]:
    """Settle a send left in SUBMITTING from what PayPal recorded. Reads from PayPal, never writes."""
    with tenant_session(merchant_id, engine) as s:
        row = s.execute(text("""SELECT d.status, d.submit_started_at, d.dispute_id, p.provider_dispute_id
                                FROM drafts d JOIN disputes p ON p.id = d.dispute_id WHERE d.id = :id"""),
                        {"id": draft_id}).first()
    if row is None or row.status != "SUBMITTING":
        return {"skipped": f"draft is {row.status if row else 'missing'}"}

    try:
        live = paypal.get(row.provider_dispute_id)  # network errors and 5xx: the job retries with backoff
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= 500:
            raise
        # PayPal will not show this dispute (gone, forbidden): retrying cannot settle it, a person must look.
        with tenant_session(merchant_id, engine) as s:
            settled = _settle(s, merchant_id, draft_id, row.dispute_id, row.provider_dispute_id, "worker",
                              sent=False, note="NEEDS_MANUAL_CHECK", action="draft.submit_reconciled",
                              summary={"sent": False, "paypal_http": exc.response.status_code})
        return {"draft_id": str(draft_id), "sent": False, "note": "NEEDS_MANUAL_CHECK", "settled": settled}
    sent, note = decide(live, row.submit_started_at)
    with tenant_session(merchant_id, engine) as s:
        settled = _settle(s, merchant_id, draft_id, row.dispute_id, row.provider_dispute_id, "worker",
                          sent=sent, note=note, action="draft.submit_reconciled",
                          summary={"sent": sent, "note": note, "paypal_status": live.get("status")})
    return {"draft_id": str(draft_id), "sent": sent, "note": note, "settled": settled}
