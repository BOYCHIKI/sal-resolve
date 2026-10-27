"""SAL API. The merchant id always comes from the server-side identity, never from request input."""
from __future__ import annotations

import hmac
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from functools import lru_cache

from app import logs
from app import repositories as repo
from app import actions
from app import evidence as evidence_store
from app import submission
from app.config import get_settings, require_valid
from app.db import app_engine, tenant_session
from app.paypal import PayPalDisputes

log = logging.getLogger("sal.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logs.setup()
    log.info("api starting", extra={"kind": "config", "outcome": json.dumps(require_valid().summary())})
    yield


_prod = get_settings().env == "prod"
app = FastAPI(title="SAL Resolve API", version="0.1.0", lifespan=lifespan,
              docs_url=None if _prod else "/docs", redoc_url=None, openapi_url=None if _prod else "/openapi.json")

# ---------------------------------------------------------------- request guard
# Paths anyone may reach: platform health checks and PayPal's webhook (which carries its own signature).
OPEN_PATHS = {"/api/health", "/webhooks/paypal"}
MAX_BODY_BYTES = 256 * 1024              # JSON bodies
MAX_UPLOAD_BYTES = 11 * 1024 * 1024      # one evidence file (< 10 MB) plus multipart overhead


@app.middleware("http")
async def guard(request: Request, call_next):
    """Before any handler runs: refuse oversized bodies, and, when an internal token is configured (always in
    prod), answer only the SAL web server. The browser never talks to this API directly."""
    path = request.url.path
    declared = request.headers.get("content-length")
    limit = MAX_UPLOAD_BYTES if path.endswith("/evidence") else MAX_BODY_BYTES
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        return JSONResponse({"detail": {"code": "PAYLOAD_TOO_LARGE", "retryable": False}}, status_code=413)
    token = get_settings().internal_token
    if token and path not in OPEN_PATHS:
        given = request.headers.get("x-sal-internal-token", "")
        if not hmac.compare_digest(given.encode(), token.encode()):
            return JSONResponse({"detail": {"code": "UNAUTHORIZED", "retryable": False}}, status_code=401)
    return await call_next(request)


@app.exception_handler(Exception)
async def unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Never leak internals: the caller gets an id, the log gets the stack trace."""
    error_id = uuid.uuid4().hex[:12]
    log.error("unhandled error %s on %s %s", error_id, request.method, request.url.path, exc_info=exc)
    return JSONResponse({"detail": {"code": "INTERNAL_ERROR", "error_id": error_id, "retryable": True}},
                        status_code=500)

# One PayPal client per API process: the OAuth token is reused until it expires (created on first use).
_paypal_client = lru_cache(maxsize=1)(PayPalDisputes)
WORKER_STALE_SECONDS = 60


def current_merchant() -> UUID:
    """Demo identity until the auth provider is chosen (v1.1 §8): a server-configured merchant.
    Deliberately does not read headers or query parameters."""
    merchant_id = get_settings().demo_merchant_id
    if merchant_id is None:
        raise HTTPException(503, detail={"code": "AUTH_NOT_CONFIGURED", "retryable": False})
    return merchant_id


ZERO_DECIMAL_CURRENCIES = {"JPY", "HUF", "TWD"}  # PayPal: amounts in whole units


def money_str(amount: Decimal, currency: str) -> str:
    """Exact decimal string at the currency's precision (NUMERIC(19,4) comes back as 45.0000)."""
    exp = Decimal(1) if currency in ZERO_DECIMAL_CURRENCIES else Decimal("0.01")
    if amount != amount.quantize(exp):
        return format(amount.normalize(), "f")  # never round away precision silently
    return str(amount.quantize(exp))


def _serialize(row: repo.DisputeRow) -> dict:
    return {
        "id": str(row.id), "origin": row.origin, "provider_dispute_id": row.provider_dispute_id,
        "case_ref": row.case_ref, "reason": row.reason,
        "amount": {"value": money_str(row.amount, row.currency), "currency": row.currency},
        "provider_status": row.provider_status, "lifecycle_stage": row.lifecycle_stage,
        "internal_state": row.internal_state,
        "deadline_at": row.deadline_at.isoformat() if row.deadline_at else None,
        "allowed_actions": row.allowed_actions, "version": row.version,
    }


@app.get("/api/disputes")
def list_disputes(merchant_id: UUID = Depends(current_merchant), limit: int = Query(50, ge=1, le=200),
                  after_deadline: datetime | None = None, after_id: UUID | None = None) -> dict:
    after = (after_deadline, after_id) if after_id else None
    with tenant_session(merchant_id) as s:
        rows = repo.list_disputes(s, merchant_id, limit=limit, after=after)
        summaries = repo.case_summaries(s, [r.id for r in rows])
    items = [{**_serialize(r), "summary": summaries.get(r.id)} for r in rows]
    cursor = ({"after_deadline": rows[-1].deadline_at.isoformat() if rows[-1].deadline_at else None,
               "after_id": str(rows[-1].id)} if len(rows) == limit else None)
    return {"items": items, "next": cursor}


@app.get("/api/disputes/{dispute_id}")
def get_dispute(dispute_id: UUID, merchant_id: UUID = Depends(current_merchant)) -> dict:
    with tenant_session(merchant_id) as s:
        row = repo.get_dispute(s, dispute_id)
        summary = repo.case_summaries(s, [dispute_id]).get(dispute_id) if row else None
    if row is None:  # another tenant's dispute is indistinguishable from a missing one
        raise HTTPException(404, detail={"code": "DISPUTE_NOT_FOUND", "retryable": False})
    return {**_serialize(row), "summary": summary}


@app.post("/api/disputes/sync", status_code=202)
def sync_disputes(merchant_id: UUID = Depends(current_merchant)) -> dict:
    """Queues a sync. Repeated clicks within the same minute coalesce into one job."""
    bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    with tenant_session(merchant_id) as s:
        job_id = repo.enqueue_job_returning(s, merchant_id, "sync_disputes", f"sync_disputes:{merchant_id}:{bucket}")
        repo.enqueue_job(s, merchant_id, "scan_holds", f"scan_holds:{merchant_id}:{bucket}")  # held-funds cards
    return {"job_id": str(job_id), "status_url": f"/api/jobs/{job_id}"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: UUID, merchant_id: UUID = Depends(current_merchant)) -> dict:
    with tenant_session(merchant_id) as s:
        job = repo.get_job(s, job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "JOB_NOT_FOUND", "retryable": False})
    return {"id": str(job["id"]), "kind": job["kind"], "state": job["state"], "attempts": job["attempts"],
            "max_attempts": job["max_attempts"], "error": job["last_error"], "result": job["result"]}


# ---------------------------------------------------------------- PayPal webhooks
MAX_WEBHOOK_BYTES = 256 * 1024


class WebhookVerifier(Protocol):
    def __call__(self, headers: dict[str, str], event: dict) -> bool: ...


def paypal_verifier() -> WebhookVerifier:
    webhook_id = get_settings().paypal_webhook_id
    if not webhook_id:
        raise HTTPException(503, detail={"code": "WEBHOOK_NOT_CONFIGURED", "retryable": True})
    client = _paypal_client()
    return lambda headers, event: client.verify_webhook(headers, event, webhook_id)


@app.post("/webhooks/paypal")
async def paypal_webhook(request: Request, verify: WebhookVerifier = Depends(paypal_verifier)) -> dict:
    """Verify, deduplicate, store. Routing to a merchant happens in the worker (tenant unknown here)."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_WEBHOOK_BYTES):
        raise HTTPException(413, detail={"code": "PAYLOAD_TOO_LARGE", "retryable": False})
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, detail={"code": "PAYLOAD_TOO_LARGE", "retryable": False})
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(400, detail={"code": "INVALID_JSON", "retryable": False}) from None
    if not isinstance(event, dict) or not event.get("id"):
        raise HTTPException(400, detail={"code": "INVALID_EVENT", "retryable": False})
    try:
        verified = await run_in_threadpool(verify, {k.lower(): v for k, v in request.headers.items()}, event)
    except Exception:  # PayPal verify API unavailable: let PayPal retry the delivery
        raise HTTPException(503, detail={"code": "VERIFICATION_UNAVAILABLE", "retryable": True}) from None
    if not verified:
        raise HTTPException(401, detail={"code": "INVALID_SIGNATURE", "retryable": False})
    with Session(app_engine()) as s, s.begin():
        stored = repo.insert_webhook_event(s, event)
    return {"received": True, "duplicate": not stored}


@app.get("/api/disputes/{dispute_id}/analysis")
def get_analysis(dispute_id: UUID, merchant_id: UUID = Depends(current_merchant)) -> dict:
    """Latest analysis, its current draft and the agent's tool trail (for the Case Workspace)."""
    with tenant_session(merchant_id) as s:
        a = s.execute(text("""
            SELECT a.id, a.dispute_version, a.rule_version, a.facts, a.findings, a.review_required,
                   a.snapshot_hash, a.created_at, a.assessment, r.id AS run_id, r.roles, r.steps
            FROM analyses a JOIN agent_runs r ON r.id = a.agent_run_id
            WHERE a.dispute_id = :d ORDER BY a.created_at DESC LIMIT 1"""), {"d": dispute_id}).first()
        if a is None:
            raise HTTPException(404, detail={"code": "ANALYSIS_NOT_FOUND", "retryable": False})
        draft = s.execute(text("""SELECT id, revision, status, claims, submit_note FROM drafts
                                  WHERE analysis_id = :a ORDER BY revision DESC LIMIT 1"""), {"a": a.id}).first()
        tools = s.execute(text("""SELECT step, tool, args, ok, summary FROM tool_calls
                                  WHERE agent_run_id = :r ORDER BY step"""), {"r": a.run_id}).all()
    return {
        "analysis_id": str(a.id), "dispute_version": a.dispute_version, "rule_version": a.rule_version,
        "review_required": a.review_required, "snapshot_hash": a.snapshot_hash,
        "facts": a.facts, "findings": a.findings, "assessment": a.assessment,
        "draft": {"id": str(draft.id), "revision": draft.revision, "status": draft.status,
                  "claims": draft.claims, "submit_note": draft.submit_note} if draft else None,
        "agent": {"roles": a.roles, "steps": a.steps,
                  "tool_calls": [dict(t._mapping) for t in tools]},
    }


@app.get("/api/disputes/{dispute_id}/evidence")
def list_evidence(dispute_id: UUID, merchant_id: UUID = Depends(current_merchant)) -> dict:
    """Parsed evidence text with line numbers, so the UI can show the exact line behind each fact."""
    with tenant_session(merchant_id) as s:
        rows = s.execute(text("""SELECT coalesce(source_ref, id::text) AS evidence_id, doc_type, content_lines,
                                        uploaded_at, origin
                                 FROM evidence WHERE dispute_id = :d ORDER BY uploaded_at, source_ref NULLS LAST, id"""),
                         {"d": dispute_id}).all()
    return {"items": [{"evidence_id": r.evidence_id, "type": r.doc_type, "lines": r.content_lines or [],
                       "origin": r.origin} for r in rows]}


# ---------------------------------------------------------------- approval and submission
class ApproveBody(BaseModel):
    revision: int
    snapshot_hash: str


DEMO_ACTOR = "operator:demo"  # replaced by the authenticated user once auth exists


def paypal_sink() -> submission.EvidenceSink:
    return _paypal_client()


# ---------------------------------------------------------------- health and operations
@app.get("/api/health")
def health() -> dict:
    """Liveness for the hosting platform and the UI banner: database reachable, worker heartbeat recent.
    No tenant data, so no merchant needed."""
    try:
        with Session(app_engine()) as s:
            beat = s.execute(text("""SELECT max(seen_at) AS seen, extract(epoch FROM now() - max(seen_at)) AS age
                                     FROM worker_heartbeats""")).one()
    except Exception as exc:  # noqa: BLE001 — health must answer, not raise
        return {"status": "down", "database": f"error: {type(exc).__name__}", "worker": None}
    age = float(beat.age) if beat.age is not None else None
    alive = age is not None and age < WORKER_STALE_SECONDS
    return {"status": "ok" if alive else "degraded", "database": "ok",
            "worker": {"alive": alive, "last_seen": beat.seen, "seconds_since": None if age is None else round(age)}}


@app.get("/api/ops")
def ops(merchant_id: UUID = Depends(current_merchant)) -> dict:
    """What an operator needs to trust the background work: queue, failures, AI fallbacks and cost, last sync."""
    with tenant_session(merchant_id) as s:
        queue = {r.state: r.n for r in s.execute(text("SELECT state, count(*) AS n FROM jobs GROUP BY state"))}
        oldest = s.execute(text("""SELECT extract(epoch FROM now() - min(run_after)) FROM jobs
                                   WHERE state = 'QUEUED' AND run_after <= now()""")).scalar()
        failed = s.execute(text("""SELECT kind, target_id, left(last_error, 200) AS error, updated_at FROM jobs
                                   WHERE state = 'FAILED' AND updated_at > now() - interval '24 hours'
                                   ORDER BY updated_at DESC LIMIT 10""")).all()
        runs = s.execute(text("""SELECT count(*) AS runs,
                                        count(*) FILTER (WHERE roles LIKE '%LLM unavailable%') AS fallbacks,
                                        coalesce(sum(llm_input_tokens), 0) AS tin,
                                        coalesce(sum(llm_output_tokens), 0) AS tout
                                 FROM agent_runs WHERE started_at > now() - interval '24 hours'""")).one()
        last_sync = s.execute(text("""SELECT max(occurred_at) FROM audit_logs
                                      WHERE action IN ('disputes.synced', 'dispute.synced')""")).scalar()
    return {"queue": queue, "oldest_ready_job_seconds": round(oldest) if oldest else 0,
            "failed_last_24h": [dict(r._mapping) for r in failed],
            "agent_last_24h": {"runs": runs.runs, "llm_fallbacks": runs.fallbacks,
                               "llm_input_tokens": runs.tin, "llm_output_tokens": runs.tout},
            "last_paypal_sync": last_sync}


def _submission_error(exc: submission.SubmissionError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": str(exc), "retryable": exc.status >= 500})


@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: UUID, body: ApproveBody, merchant_id: UUID = Depends(current_merchant)) -> dict:
    """The operator approves the exact revision and analysis snapshot they reviewed."""
    try:
        return submission.approve(merchant_id, draft_id, body.revision, body.snapshot_hash, DEMO_ACTOR)
    except submission.SubmissionError as exc:
        raise _submission_error(exc) from None


@app.post("/api/drafts/{draft_id}/submit")
def submit_draft(draft_id: UUID, merchant_id: UUID = Depends(current_merchant),
                 paypal: submission.EvidenceSink = Depends(paypal_sink)) -> dict:
    """Send an approved draft to PayPal Sandbox as evidence. Never called by the agent."""
    try:
        return submission.submit(merchant_id, draft_id, DEMO_ACTOR, paypal)
    except submission.SubmissionError as exc:
        raise _submission_error(exc) from None


# ---------------------------------------------------------------- agent suggestions (ADR-006)
class ActionApproveBody(BaseModel):
    payload_hash: str


ACTION_STATUSES = {"PROPOSED", "APPROVED", "DONE", "FAILED", "DISMISSED", "SUPERSEDED"}


def _action_error(exc: actions.ActionError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": str(exc), "retryable": exc.status >= 500})


@app.get("/api/actions")
def list_actions(status: str = Query("PROPOSED"), dispute_id: UUID | None = Query(None),
                 merchant_id: UUID = Depends(current_merchant)) -> dict:
    """What SAL suggests the merchant does next, most urgent first."""
    if status not in ACTION_STATUSES:
        raise HTTPException(422, detail={"code": "BAD_STATUS", "retryable": False})
    return {"items": actions.list_actions(merchant_id, status, dispute_id)}


@app.post("/api/actions/{action_id}/approve")
def approve_action(action_id: UUID, body: ActionApproveBody, merchant_id: UUID = Depends(current_merchant),
                   paypal: submission.EvidenceSink = Depends(paypal_sink)) -> dict:
    """The merchant approves the exact suggestion they read (payload_hash). Only SEND_EVIDENCE writes to PayPal."""
    try:
        return actions.approve(merchant_id, action_id, body.payload_hash, DEMO_ACTOR, paypal)
    except actions.ActionError as exc:
        raise _action_error(exc) from None


@app.post("/api/actions/{action_id}/dismiss")
def dismiss_action(action_id: UUID, merchant_id: UUID = Depends(current_merchant)) -> dict:
    try:
        return actions.dismiss(merchant_id, action_id, DEMO_ACTOR)
    except actions.ActionError as exc:
        raise _action_error(exc) from None


# ---------------------------------------------------------------- evidence upload
class TrackingBody(BaseModel):
    tracking_number: str = Field(min_length=1, max_length=60)
    courier: str | None = Field(default=None, max_length=60)


@app.post("/api/disputes/{dispute_id}/tracking", status_code=201)
def add_tracking(dispute_id: UUID, body: TrackingBody, merchant_id: UUID = Depends(current_merchant)) -> dict:
    """The seller types the resi and courier. SAL records it as the seller's word (not proof), names the PayPal
    carrier code, and checks the case again; the courier's own page still has to show the parcel moving."""
    try:
        return evidence_store.add_tracking_number(merchant_id, dispute_id, body.tracking_number, body.courier,
                                                  DEMO_ACTOR)
    except evidence_store.EvidenceError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": str(exc), "retryable": False}) from None

@app.post("/api/disputes/{dispute_id}/evidence", status_code=201)
async def upload_evidence(dispute_id: UUID, file: UploadFile = File(...), doc_type: str = Form(...),
                          merchant_id: UUID = Depends(current_merchant)) -> dict:
    """Attach a document (PDF/JPG/PNG/GIF, < 10 MB). Its text is extracted and the case is re-analyzed."""
    data = await file.read(evidence_store.MAX_BYTES + 1)  # never read more than the limit allows
    try:
        stored = await run_in_threadpool(
            evidence_store.store, merchant_id, dispute_id, data, file.filename or "", doc_type, DEMO_ACTOR,
            get_settings().storage_dir)
    except evidence_store.EvidenceError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": str(exc), "retryable": False}) from None
    return {"evidence_id": str(stored.evidence_id), "mime": stored.mime, "text_lines": stored.lines,
            "analysis_queued": stored.job_queued}
