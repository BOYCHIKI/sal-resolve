"""Hand-written, parameterized queries. No text-to-SQL, no string interpolation (SAL v1.1 §6).

Tenant filtering is enforced by RLS; queries still name merchant_id where it lets Postgres use
the merchant-led indexes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

DISPUTE_COLUMNS = """
    id, merchant_id, origin, provider_dispute_id, case_ref, reason, amount, currency,
    provider_status, lifecycle_stage, internal_state, deadline_at, allowed_actions,
    provider_updated_at, version, updated_at,
    provider_payload->>'dispute_channel' AS channel,
    provider_payload#>>'{disputed_transactions,0,seller_protection_eligible}' AS seller_protection
"""


@dataclass(frozen=True)
class DisputeRow:
    id: UUID
    merchant_id: UUID
    origin: str
    provider_dispute_id: str
    case_ref: str | None
    reason: str
    amount: Decimal
    currency: str
    provider_status: str
    lifecycle_stage: str | None
    internal_state: str
    deadline_at: datetime | None
    allowed_actions: list[str]
    provider_updated_at: datetime | None
    version: int
    updated_at: datetime
    channel: str | None = None   # PayPal dispute_channel: INTERNAL (filed with PayPal) or EXTERNAL (bank chargeback)
    seller_protection: str | None = None   # 'true'/'false' as PayPal marks the payment; None when it says nothing


def list_disputes(session: Session, merchant_id: UUID, *, limit: int = 50,
                  after: tuple[datetime | None, UUID] | None = None) -> list[DisputeRow]:
    """Keyset pagination ordered by deadline (NULLS LAST), then id — matches disputes_queue_idx."""
    limit = max(1, min(limit, 200))
    if after is None:
        rows = session.execute(text(f"""
            SELECT {DISPUTE_COLUMNS} FROM disputes
            WHERE merchant_id = :mid
            ORDER BY deadline_at ASC NULLS LAST, id ASC
            LIMIT :limit"""), {"mid": merchant_id, "limit": limit})
    elif after[0] is None:
        rows = session.execute(text(f"""
            SELECT {DISPUTE_COLUMNS} FROM disputes
            WHERE merchant_id = :mid AND deadline_at IS NULL AND id > :aid
            ORDER BY deadline_at ASC NULLS LAST, id ASC
            LIMIT :limit"""), {"mid": merchant_id, "aid": after[1], "limit": limit})
    else:
        rows = session.execute(text(f"""
            SELECT {DISPUTE_COLUMNS} FROM disputes
            WHERE merchant_id = :mid
              AND (deadline_at IS NULL OR (deadline_at, id) > (:adl, :aid))
            ORDER BY deadline_at ASC NULLS LAST, id ASC
            LIMIT :limit"""), {"mid": merchant_id, "adl": after[0], "aid": after[1], "limit": limit})
    return [DisputeRow(**r._mapping) for r in rows]


def get_dispute(session: Session, dispute_id: UUID) -> DisputeRow | None:
    row = session.execute(text(f"SELECT {DISPUTE_COLUMNS} FROM disputes WHERE id = :id"),
                          {"id": dispute_id}).first()
    return DisputeRow(**row._mapping) if row else None


def upsert_provider_dispute(session: Session, merchant_id: UUID, d: dict[str, Any],
                            payload: dict[str, Any]) -> tuple[DisputeRow, bool]:
    """Insert or refresh a PayPal dispute. Returns (row, changed). Version bumps only on real change."""
    params = {
        "mid": merchant_id,
        "origin": d["origin"],
        "pid": d["provider_dispute_id"],
        "case_ref": d.get("custom"),
        "reason": d["reason"],
        "amount": Decimal(d["amount"]["value"]),
        "currency": d["amount"]["currency"],
        "status": d["provider_status"],
        "stage": d.get("lifecycle_stage"),
        "deadline": d.get("response_deadline"),
        "actions": sorted(d.get("allowed_actions") or []),
        "payload": json.dumps(payload),
        "pupdated": d.get("updated_at"),
    }
    before = session.execute(text("""
        SELECT version FROM disputes WHERE merchant_id = :mid AND provider_dispute_id = :pid
        FOR UPDATE"""), params).scalar()
    row = session.execute(text(f"""
        INSERT INTO disputes (merchant_id, origin, provider_dispute_id, case_ref, reason, amount, currency,
                              provider_status, lifecycle_stage, deadline_at, allowed_actions,
                              provider_payload, provider_updated_at)
        VALUES (:mid, :origin, :pid, :case_ref, :reason, :amount, :currency, :status, :stage,
                :deadline, :actions, CAST(:payload AS jsonb), :pupdated)
        ON CONFLICT (merchant_id, provider_dispute_id) DO UPDATE SET
            provider_status     = EXCLUDED.provider_status,
            lifecycle_stage     = EXCLUDED.lifecycle_stage,
            deadline_at         = EXCLUDED.deadline_at,
            allowed_actions     = EXCLUDED.allowed_actions,
            amount              = EXCLUDED.amount,
            currency            = EXCLUDED.currency,
            provider_payload    = EXCLUDED.provider_payload,
            provider_updated_at = EXCLUDED.provider_updated_at,
            -- version tracks what SAL acts on; a provider timestamp alone is not a change
            version = disputes.version + CASE WHEN
                (disputes.provider_status, disputes.lifecycle_stage, disputes.deadline_at,
                 disputes.allowed_actions, disputes.amount, disputes.currency)
                IS DISTINCT FROM
                (EXCLUDED.provider_status, EXCLUDED.lifecycle_stage, EXCLUDED.deadline_at,
                 EXCLUDED.allowed_actions, EXCLUDED.amount, EXCLUDED.currency) THEN 1 ELSE 0 END,
            updated_at = now()
        WHERE (disputes.provider_status, disputes.lifecycle_stage, disputes.deadline_at,
               disputes.allowed_actions, disputes.amount, disputes.currency, disputes.provider_updated_at)
              IS DISTINCT FROM
              (EXCLUDED.provider_status, EXCLUDED.lifecycle_stage, EXCLUDED.deadline_at,
               EXCLUDED.allowed_actions, EXCLUDED.amount, EXCLUDED.currency, EXCLUDED.provider_updated_at)
        RETURNING {DISPUTE_COLUMNS}"""), params).first()
    if row is None:  # identical delivery: nothing written
        existing = session.execute(text(f"""
            SELECT {DISPUTE_COLUMNS} FROM disputes
            WHERE merchant_id = :mid AND provider_dispute_id = :pid"""), params).one()
        return DisputeRow(**existing._mapping), False
    result = DisputeRow(**row._mapping)
    return result, before is None or result.version != before


def write_audit(session: Session, merchant_id: UUID, actor: str, action: str,
                target: str | None = None, summary: dict[str, Any] | None = None) -> None:
    session.execute(text("""
        INSERT INTO audit_logs (merchant_id, actor, action, target, summary)
        VALUES (:mid, :actor, :action, :target, CAST(:summary AS jsonb))"""),
        {"mid": merchant_id, "actor": actor, "action": action, "target": target,
         "summary": json.dumps(summary or {})})


def enqueue_job(session: Session, merchant_id: UUID, kind: str, idempotency_key: str,
                target_id: UUID | None = None, payload: dict[str, Any] | None = None,
                delay_seconds: int = 0) -> bool:
    """Returns False when an identical job already exists (duplicate webhook/poll)."""
    row = session.execute(text("""
        INSERT INTO jobs (merchant_id, kind, target_id, idempotency_key, payload, run_after)
        VALUES (:mid, :kind, :target, :key, CAST(:payload AS jsonb), now() + make_interval(secs => :delay))
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id"""), {"mid": merchant_id, "kind": kind, "target": target_id, "key": idempotency_key,
                           "payload": json.dumps(payload or {}), "delay": delay_seconds}).first()
    return row is not None


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    merchant_id: UUID
    kind: str
    target_id: UUID | None
    attempts: int
    payload: dict[str, Any]


def claim_job(session: Session, lease_seconds: int = 60) -> ClaimedJob | None:
    """Worker-only. Claims one due job (or one whose lease expired) without blocking other workers."""
    row = session.execute(text("""
        UPDATE jobs SET state = 'RUNNING', attempts = attempts + 1,
                        lease_until = now() + make_interval(secs => :lease), updated_at = now()
        WHERE id = (
            SELECT id FROM jobs
            WHERE ((state = 'QUEUED' AND run_after <= now())
                OR (state = 'RUNNING' AND lease_until < now()))
              AND attempts < max_attempts
            ORDER BY run_after
            FOR UPDATE SKIP LOCKED
            LIMIT 1)
        RETURNING id, merchant_id, kind, target_id, attempts, payload"""), {"lease": lease_seconds}).first()
    return ClaimedJob(**row._mapping) if row else None


MAX_BACKOFF_SECONDS = 900


def complete_job(session: Session, job_id: UUID, result: dict[str, Any] | None = None) -> None:
    session.execute(text("""
        UPDATE jobs SET state = 'SUCCEEDED', lease_until = NULL, last_error = NULL,
                        result = CAST(:result AS jsonb), updated_at = now()
        WHERE id = :id"""), {"id": job_id, "result": json.dumps(result or {})})


def fail_job(session: Session, job_id: UUID, error: str, *, retryable: bool = True) -> str:
    """Requeue with exponential backoff (5s, 10s, 20s ... capped), or FAILED when out of attempts."""
    row = session.execute(text("""
        UPDATE jobs SET
            state = CASE WHEN :retryable AND attempts < max_attempts THEN 'QUEUED' ELSE 'FAILED' END,
            run_after = now() + make_interval(secs => LEAST(:cap, 5 * power(2, GREATEST(attempts - 1, 0)))),
            lease_until = NULL, last_error = left(:error, 2000), updated_at = now()
        WHERE id = :id
        RETURNING state"""), {"id": job_id, "error": error, "retryable": retryable,
                               "cap": MAX_BACKOFF_SECONDS}).one()
    return row.state


def extend_lease(session: Session, job_id: UUID, lease_seconds: int = 60) -> None:
    session.execute(text("""
        UPDATE jobs SET lease_until = now() + make_interval(secs => :lease)
        WHERE id = :id AND state = 'RUNNING'"""), {"id": job_id, "lease": lease_seconds})


def fail_exhausted_jobs(session: Session) -> int:
    """Jobs whose lease expired on their last attempt would otherwise sit in RUNNING forever."""
    rows = session.execute(text("""
        UPDATE jobs SET state = 'FAILED', lease_until = NULL, updated_at = now(),
                        last_error = coalesce(last_error, 'lease expired on final attempt')
        WHERE state = 'RUNNING' AND lease_until < now() AND attempts >= max_attempts
        RETURNING id""")).all()
    return len(rows)


def get_job(session: Session, job_id: UUID) -> dict[str, Any] | None:
    row = session.execute(text("""
        SELECT id, kind, state, attempts, max_attempts, last_error, result, created_at, updated_at
        FROM jobs WHERE id = :id"""), {"id": job_id}).first()
    return dict(row._mapping) if row else None


def enqueue_job_returning(session: Session, merchant_id: UUID, kind: str, idempotency_key: str,
                          target_id: UUID | None = None, payload: dict[str, Any] | None = None) -> UUID:
    """Like enqueue_job, but returns the id of the new or already-existing job."""
    row = session.execute(text("""
        WITH ins AS (
            INSERT INTO jobs (merchant_id, kind, target_id, idempotency_key, payload)
            VALUES (:mid, :kind, :target, :key, CAST(:payload AS jsonb))
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id)
        SELECT id FROM ins
        UNION ALL
        SELECT id FROM jobs WHERE idempotency_key = :key
        LIMIT 1"""), {"mid": merchant_id, "kind": kind, "target": target_id, "key": idempotency_key,
                      "payload": json.dumps(payload or {})}).one()
    return row.id


# ---------------------------------------------------------------- worker liveness
def worker_heartbeat(session: Session, worker_id: str, jobs_done: int = 0) -> None:
    session.execute(text("""
        INSERT INTO worker_heartbeats (worker_id, seen_at, jobs_done) VALUES (:w, now(), :n)
        ON CONFLICT (worker_id) DO UPDATE SET seen_at = now(), jobs_done = worker_heartbeats.jobs_done + :n"""),
        {"w": worker_id, "n": jobs_done})


# ---------------------------------------------------------------- webhooks
def insert_webhook_event(session: Session, event: dict[str, Any]) -> bool:
    """API role (insert-only). Returns False for a duplicate delivery."""
    row = session.execute(text("""
        INSERT INTO webhook_events (provider_event_id, event_type, resource_id, payload)
        VALUES (:eid, :etype, :rid, CAST(:payload AS jsonb))
        ON CONFLICT (provider_event_id) DO NOTHING
        RETURNING id"""), {
        "eid": event["id"], "etype": event.get("event_type", "UNKNOWN"),
        "rid": (event.get("resource") or {}).get("dispute_id"), "payload": json.dumps(event)}).first()
    return row is not None


def claim_webhook_event(session: Session) -> dict[str, Any] | None:
    row = session.execute(text("""
        SELECT id, provider_event_id, event_type, resource_id, payload FROM webhook_events
        WHERE processed_at IS NULL
        ORDER BY received_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1""")).first()
    return dict(row._mapping) if row else None


def mark_webhook_processed(session: Session, event_id: UUID, error: str | None = None) -> None:
    session.execute(text("UPDATE webhook_events SET processed_at = now(), error = :err WHERE id = :id"),
                    {"id": event_id, "err": error})


def merchant_for_paypal_account(session: Session, paypal_merchant_id: str) -> UUID | None:
    return session.execute(text("SELECT merchant_id FROM paypal_connections WHERE paypal_merchant_id = :p"),
                           {"p": paypal_merchant_id}).scalar()


def case_summaries(session: Session, dispute_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    """What a person needs on the queue: the product, the order, how many things to check, draft state.
    One query for the whole page (lateral joins on the latest analysis and draft)."""
    if not dispute_ids:
        return {}
    rows = session.execute(text("""
        SELECT d.id,
               d.provider_payload #>> '{disputed_transactions,0,items,0,item_name}' AS item,
               d.provider_payload #>> '{disputed_transactions,0,invoice_number}'    AS invoice,
               a.findings, a.facts, a.assessment ->> 'readiness' AS readiness, dr.status AS draft_status
        FROM disputes d
        LEFT JOIN LATERAL (SELECT findings, facts, assessment FROM analyses
                           WHERE dispute_id = d.id ORDER BY created_at DESC LIMIT 1) a ON true
        LEFT JOIN LATERAL (SELECT status FROM drafts
                           WHERE dispute_id = d.id ORDER BY revision DESC LIMIT 1) dr ON true
        WHERE d.id = ANY(:ids)"""), {"ids": list(dispute_ids)}).all()
    out: dict[UUID, dict[str, Any]] = {}
    for r in rows:
        findings = r.findings or []
        order = next((f["value"] for f in (r.facts or []) if f["field"] == "order_id" and f["status"] != "rejected"),
                     r.invoice)
        item = (r.item or "").removeprefix("SAL synthetic test: ").strip() or None
        out[r.id] = {"item": item, "order_ref": order,
                     "missing": sum(1 for f in findings if f["kind"] == "missing"),
                     "conflicts": sum(1 for f in findings if f["kind"] == "conflict"),
                     "draft_status": r.draft_status, "readiness": r.readiness}
    return out
