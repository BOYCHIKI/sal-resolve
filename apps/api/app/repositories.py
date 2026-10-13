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
    provider_updated_at, version, updated_at
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
            version             = disputes.version + 1,
            updated_at          = now()
        WHERE (disputes.provider_status, disputes.lifecycle_stage, disputes.deadline_at,
               disputes.allowed_actions, disputes.amount, disputes.currency)
              IS DISTINCT FROM
              (EXCLUDED.provider_status, EXCLUDED.lifecycle_stage, EXCLUDED.deadline_at,
               EXCLUDED.allowed_actions, EXCLUDED.amount, EXCLUDED.currency)
        RETURNING {DISPUTE_COLUMNS}"""), params).first()
    if row is None:  # conflict with no real change: nothing written
        existing = session.execute(text(f"""
            SELECT {DISPUTE_COLUMNS} FROM disputes
            WHERE merchant_id = :mid AND provider_dispute_id = :pid"""), params).one()
        return DisputeRow(**existing._mapping), False
    return DisputeRow(**row._mapping), True


def write_audit(session: Session, merchant_id: UUID, actor: str, action: str,
                target: str | None = None, summary: dict[str, Any] | None = None) -> None:
    session.execute(text("""
        INSERT INTO audit_logs (merchant_id, actor, action, target, summary)
        VALUES (:mid, :actor, :action, :target, CAST(:summary AS jsonb))"""),
        {"mid": merchant_id, "actor": actor, "action": action, "target": target,
         "summary": json.dumps(summary or {})})


def enqueue_job(session: Session, merchant_id: UUID, kind: str, idempotency_key: str,
                target_id: UUID | None = None) -> bool:
    """Returns False when an identical job already exists (duplicate webhook/poll)."""
    row = session.execute(text("""
        INSERT INTO jobs (merchant_id, kind, target_id, idempotency_key)
        VALUES (:mid, :kind, :target, :key)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id"""), {"mid": merchant_id, "kind": kind, "target": target_id, "key": idempotency_key}).first()
    return row is not None


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    merchant_id: UUID
    kind: str
    target_id: UUID | None
    attempts: int


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
        RETURNING id, merchant_id, kind, target_id, attempts"""), {"lease": lease_seconds}).first()
    return ClaimedJob(**row._mapping) if row else None
