"""Human approval and submission of a draft to PayPal (SAL v1.0 §8, v1.1 D4).

approve():  one transaction — lock the draft, check it is the latest DRAFT revision of the current
            analysis and that the operator saw the same snapshot hash, record the approval.
submit():   PayPal Sandbox disputes only. Claims the draft atomically (APPROVED -> SUBMITTING) so it
            can never be sent twice, checks PayPal still offers provide_evidence, sends one evidence
            entry with the documents as PDFs, then records SUBMITTED or SUBMIT_FAILED.
"""
from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Engine, text

from app import repositories as repo
from app.db import tenant_session
from app.config import get_settings
from app.evidence import read_file
from app.evidence_pdf import render_text_pdf


class SubmissionError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code = status, code


class EvidenceSink(Protocol):
    def get(self, dispute_id: str) -> dict[str, Any]: ...
    def provide_evidence(self, dispute_id: str, payload: dict[str, Any],
                         files: list[tuple[str, bytes, str]]) -> dict[str, Any]: ...


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

        s.execute(text("""INSERT INTO approvals (merchant_id, draft_id, revision, payload_hash, snapshot_hash, actor)
                          VALUES (:m, :d, :r, :ph, :sh, :actor)"""),
                  {"m": merchant_id, "d": draft_id, "r": row.revision, "ph": row.payload_hash,
                   "sh": row.snapshot_hash, "actor": actor})
        s.execute(text("UPDATE drafts SET status = 'APPROVED' WHERE id = :id"), {"id": draft_id})
        s.execute(text("UPDATE disputes SET internal_state = 'APPROVED', updated_at = now() WHERE id = :d"),
                  {"d": row.dispute_id})
        repo.write_audit(s, merchant_id, actor, "draft.approved", target=str(draft_id),
                         summary={"revision": row.revision, "snapshot_hash": row.snapshot_hash})
    return {"draft_id": str(draft_id), "status": "APPROVED", "revision": row.revision}


def _payload(claims: list[dict[str, Any]], facts: list[dict[str, Any]], requested: list[str]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "evidence_type": requested[0] if requested else "PROOF_OF_FULFILLMENT",
        "notes": " ".join(c["text"] for c in claims)[:2000],
    }
    tracking = [f["value"] for f in facts if f["field"] == "tracking_id" and f["status"] == "supported"]
    if tracking:
        entry["evidence_info"] = {"tracking_info": [
            {"carrier_name": "OTHER", "carrier_name_other": "Carrier on file", "tracking_number": tracking[0]}]}
    return {"evidences": [entry]}  # one entry: disputes without item_id reject several (spike S6)


EXTENSIONS = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif"}


def _file_for(doc) -> tuple[str, bytes, str] | None:
    """The merchant's original upload when we have it; seeded demo documents are rendered from their text."""
    original = read_file(get_settings().storage_dir, doc.object_key)
    if original is not None:
        return f"{doc.evidence_id}.{EXTENSIONS.get(doc.mime, 'pdf')}", original, doc.mime
    if doc.content_lines:
        pdf = render_text_pdf([f"Evidence {doc.evidence_id}", ""] + [l["text"] for l in doc.content_lines])
        return f"{doc.evidence_id}.pdf", pdf, "application/pdf"
    return None


def submit(merchant_id: UUID, draft_id: UUID, actor: str, paypal: EvidenceSink,
           engine: Engine | None = None) -> dict[str, Any]:
    # 1. Claim the approved draft and gather everything to send, in one short transaction.
    with tenant_session(merchant_id, engine) as s:
        row = s.execute(text("""
            SELECT d.dispute_id, d.claims, a.facts, p.origin, p.provider_dispute_id, p.provider_payload
            FROM drafts d JOIN analyses a ON a.id = d.analysis_id JOIN disputes p ON p.id = d.dispute_id
            WHERE d.id = :id"""), {"id": draft_id}).first()
        if row is None:
            raise SubmissionError(404, "DRAFT_NOT_FOUND", "Draft not found")
        if row.origin != "PAYPAL_SANDBOX":
            raise SubmissionError(422, "NOT_A_PAYPAL_DISPUTE", "Synthetic fixtures cannot be sent to PayPal")
        claimed = s.execute(text("""UPDATE drafts SET status = 'SUBMITTING'
                                    WHERE id = :id AND status IN ('APPROVED', 'SUBMIT_FAILED') RETURNING id"""),
                            {"id": draft_id}).first()
        if claimed is None:
            raise SubmissionError(409, "NOT_SUBMITTABLE", "Draft must be approved and not already sent")
        docs = s.execute(text("""SELECT coalesce(source_ref, id::text) AS evidence_id, content_lines, object_key, mime
                                 FROM evidence WHERE dispute_id = :d
                                 ORDER BY uploaded_at, source_ref NULLS LAST, id"""), {"d": row.dispute_id}).all()
    requested = [e["evidence_type"] for e in (row.provider_payload or {}).get("evidences") or []
                 if e.get("source") == "REQUESTED_FROM_SELLER"]
    payload = _payload(row.claims, row.facts, requested)
    files = [_file_for(d) for d in docs]
    files = [f for f in files if f is not None]

    # 2. Network, outside any transaction. Re-check that PayPal still offers the action (spike finding).
    error: str | None = None
    try:
        live = paypal.get(row.provider_dispute_id)
        if "provide_evidence" not in {l.get("rel") for l in live.get("links", [])}:
            error = f"PayPal no longer offers provide_evidence (status {live.get('status')})"
        else:
            paypal.provide_evidence(row.provider_dispute_id, payload, files)
    except Exception as exc:  # noqa: BLE001 — the outcome must be recorded either way
        error = f"{type(exc).__name__}: {exc}"[:500]

    # 3. Record the outcome.
    with tenant_session(merchant_id, engine) as s:
        status = "SUBMIT_FAILED" if error else "SUBMITTED"
        s.execute(text("UPDATE drafts SET status = :st WHERE id = :id"), {"st": status, "id": draft_id})
        if not error:
            s.execute(text("UPDATE disputes SET internal_state = 'SUBMITTED', updated_at = now() WHERE id = :d"),
                      {"d": row.dispute_id})
            # refresh status/actions from PayPal shortly
            repo.enqueue_job(s, merchant_id, "sync_dispute", f"after-submit:{draft_id}",
                             payload={"provider_dispute_id": row.provider_dispute_id})
        repo.write_audit(s, merchant_id, actor, "draft.submitted" if not error else "draft.submit_failed",
                         target=str(draft_id), summary={"files": len(files), "error": error,
                                                        "evidence_type": payload["evidences"][0]["evidence_type"]})
    if error:
        raise SubmissionError(502, "PAYPAL_REJECTED", error)
    return {"draft_id": str(draft_id), "status": "SUBMITTED", "files": len(files)}
