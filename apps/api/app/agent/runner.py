"""Runs the pipeline for a stored dispute and persists the run, tool calls, analysis and draft.

Three transactions, like sync: load (short) -> analyze (no transaction; future LLM calls are network)
-> persist (short). If the dispute changed while the agent was thinking, the result is discarded
and a fresh analysis is queued, so a draft is never bound to stale data.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from app import repositories as repo
from app.actions import queue_refresh
from app.agent.models import CaseInput, Document, Line
from app.agent.pipeline import analyze
from app.agent.roles import (Drafter, Extractor, LabelExtractor, Planner, ReadAllPlanner, RuleExtractor,
                             TemplateDrafter, UnionExtractor)
from app.db import tenant_session

log = logging.getLogger("sal.agent")


class Roles:
    def __init__(self, planner: Planner, extractor: Extractor, drafter: Drafter, label: str,
                 fallback: "Roles | None" = None) -> None:
        self.planner, self.extractor, self.drafter, self.label = planner, extractor, drafter, label
        self.fallback = fallback  # used when these roles fail (e.g. the LLM is down or out of quota)


def baseline_roles() -> Roles:
    return Roles(ReadAllPlanner(), RuleExtractor(), TemplateDrafter(), "baseline:ReadAll/RuleExtractor/Template")


def configured_roles() -> Roles:
    """Deterministic baseline unless the LLM is switched on explicitly (SAL_AGENT_ROLES=llm).
    A key alone never turns it on: the LLM is postponed for the demo and free tiers are slow and capped."""
    from app.config import get_settings
    if get_settings().agent_roles != "llm":
        return baseline_roles()
    from app.agent.llm import LLMRoles
    llm = LLMRoles()
    return Roles(ReadAllPlanner(), UnionExtractor(RuleExtractor(), LabelExtractor(), llm), llm, f"rules+llm:{llm.model}",
                 fallback=baseline_roles())


def _requested(payload: dict[str, Any] | None) -> tuple[str, ...]:
    return tuple(e["evidence_type"] for e in (payload or {}).get("evidences") or []
                 if e.get("source") == "REQUESTED_FROM_SELLER" and e.get("evidence_type"))


def load_case(engine: Engine | None, merchant_id: UUID, dispute_id: UUID) -> tuple[CaseInput, int, str] | None:
    with tenant_session(merchant_id, engine) as s:
        d = s.execute(text("""SELECT id, case_ref, provider_dispute_id, reason, amount, currency, version,
                                     provider_payload FROM disputes WHERE id = :id"""), {"id": dispute_id}).first()
        if d is None:
            return None
        rows = s.execute(text("""SELECT coalesce(source_ref, id::text) AS evidence_id, doc_type, content_lines, origin
                                 FROM evidence WHERE dispute_id = :id AND content_lines IS NOT NULL
                                 ORDER BY uploaded_at, source_ref NULLS LAST, id"""), {"id": dispute_id}).all()
        evidence_hash = repo.evidence_hash(s, dispute_id)
    docs = tuple(Document(r.evidence_id, r.doc_type or "unknown",
                          tuple(Line(int(line["line"]), str(line["text"])) for line in r.content_lines), r.origin) for r in rows)
    case = CaseInput(d.case_ref or d.provider_dispute_id, d.reason, f"{d.amount:.2f}", d.currency,
                     _requested(d.provider_payload), docs)
    return case, d.version, evidence_hash


def run_analysis(merchant_id: UUID, dispute_id: UUID, job_id: UUID | None, roles: Roles,
                 engine: Engine | None = None) -> dict[str, Any]:
    loaded = load_case(engine, merchant_id, dispute_id)
    if loaded is None:
        return {"skipped": "dispute not found"}
    case, version, evidence_hash = loaded

    label = roles.label
    try:
        result = analyze(case, roles.planner, roles.extractor, roles.drafter)
    except Exception as exc:  # noqa: BLE001 â€” degrade, never block (ADR-004)
        if roles.fallback is None:
            raise
        # The SDK already retried. Missing-evidence checks still work without the model; the run says so.
        log.warning("%s failed (%s); falling back to %s", roles.label, type(exc).__name__, roles.fallback.label)
        label = f"{roles.fallback.label} (LLM unavailable: {type(exc).__name__})"
        result = analyze(case, roles.fallback.planner, roles.fallback.extractor, roles.fallback.drafter)

    usage = getattr(roles.drafter, "usage", None)  # tokens spent, even when the run fell back to rules
    claims = [asdict(c) for c in result.claims]
    body = "\n".join(c.text for c in result.claims)
    with tenant_session(merchant_id, engine) as s:
        current = s.execute(text("SELECT version FROM disputes WHERE id = :id FOR UPDATE"),
                            {"id": dispute_id}).scalar()
        if current != version:  # dispute moved on while we were analyzing
            repo.enqueue_job(s, merchant_id, "analyze_dispute", f"analyze:{dispute_id}:v{current}", dispute_id)
            return {"discarded": "stale", "analyzed_version": version, "current_version": current}
        current_hash = repo.evidence_hash(s, dispute_id)
        if current_hash != evidence_hash:  # a document arrived while we were analyzing, so this verdict never saw it
            repo.enqueue_job(s, merchant_id, "analyze_dispute", f"analyze:{dispute_id}:docs:{current_hash}", dispute_id)
            return {"discarded": "documents changed"}

        run_id = s.execute(text("""
            INSERT INTO agent_runs (merchant_id, dispute_id, job_id, roles, status, steps, ended_at,
                                    llm_input_tokens, llm_output_tokens)
            VALUES (:m, :d, :j, :roles, 'SUCCEEDED', :steps, now(), :tin, :tout) RETURNING id"""),
            {"m": merchant_id, "d": dispute_id, "j": job_id, "roles": label, "steps": len(result.tool_calls),
             "tin": usage.get("input_tokens") if usage else None,
             "tout": usage.get("output_tokens") if usage else None}).scalar_one()
        for call in result.tool_calls:
            s.execute(text("""INSERT INTO tool_calls (merchant_id, agent_run_id, step, tool, args, ok, summary)
                              VALUES (:m, :r, :step, :tool, CAST(:args AS jsonb), :ok, :summary)"""),
                      {"m": merchant_id, "r": run_id, "step": call.step, "tool": call.tool,
                       "args": json.dumps(call.args), "ok": call.ok, "summary": call.summary})
        analysis_id = s.execute(text("""
            INSERT INTO analyses (merchant_id, dispute_id, agent_run_id, dispute_version, rule_version, facts,
                                  findings, review_required, snapshot_hash, assessment, evidence_hash)
            VALUES (:m, :d, :r, :v, :rv, CAST(:facts AS jsonb), CAST(:findings AS jsonb), :review, :hash,
                    CAST(:assessment AS jsonb), :evidence_hash)
            RETURNING id"""),
            {"m": merchant_id, "d": dispute_id, "r": run_id, "v": version, "rv": result.rule_version,
             "evidence_hash": evidence_hash,
             "facts": json.dumps([asdict(f) for f in result.facts]),
             "findings": json.dumps([asdict(f) for f in result.findings]),
             "review": result.review_required, "hash": result.snapshot_hash,
             "assessment": json.dumps(asdict(result.assessment)) if result.assessment else None}).scalar_one()
        # A new analysis also cancels an approval that was not sent yet: the operator approved what they
        # saw, and the documents or the case have changed since (ADR-003 D1).
        s.execute(text("""UPDATE drafts SET status = 'SUPERSEDED'
                          WHERE dispute_id = :d AND status IN ('DRAFT', 'APPROVED', 'SUBMIT_FAILED')"""),
                  {"d": dispute_id})
        revision = s.execute(text("""
            INSERT INTO drafts (merchant_id, dispute_id, revision, body, payload_hash, analysis_id, claims)
            SELECT :m, :d, coalesce(max(revision), 0) + 1, :body, :ph, :a, CAST(:claims AS jsonb)
            FROM drafts WHERE dispute_id = :d
            RETURNING revision"""),
            {"m": merchant_id, "d": dispute_id, "body": body, "ph": hashlib.sha256(body.encode()).hexdigest(),
             "a": analysis_id, "claims": json.dumps(claims)}).scalar_one()
        # A reply already sent stays "sent" while PayPal reviews it; only a new request for evidence
        # (provide_evidence offered again) puts the case back in front of the operator.
        s.execute(text("""UPDATE disputes SET updated_at = now(), internal_state = CASE
                              WHEN internal_state = 'SUBMITTED' AND NOT ('provide_evidence' = ANY(allowed_actions))
                              THEN internal_state ELSE 'NEEDS_REVIEW' END
                          WHERE id = :d"""),
                  {"d": dispute_id})
        queue_refresh(s, merchant_id, dispute_id, f"analysis:{analysis_id}")  # new facts, new suggestions (ADR-006)
        repo.write_audit(s, merchant_id, "agent", "analysis.completed", target=str(dispute_id),
                         summary={"run": str(run_id), "revision": revision, "findings": len(result.findings),
                                  "review_required": result.review_required})
    out = {"agent_run_id": str(run_id), "analysis_id": str(analysis_id), "draft_revision": revision,
           "findings": len(result.findings), "claims": len(claims), "review_required": result.review_required}
    cache = getattr(roles.drafter, "cache", None)  # documents reused from earlier extractions (LLM roles only)
    if cache:
        out["extraction_cache"] = dict(cache)
    return out
