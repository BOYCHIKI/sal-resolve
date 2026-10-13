"""Runs the pipeline for a stored dispute and persists the run, tool calls, analysis and draft.

Three transactions, like sync: load (short) -> analyze (no transaction; future LLM calls are network)
-> persist (short). If the dispute changed while the agent was thinking, the result is discarded
and a fresh analysis is queued, so a draft is never bound to stale data.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from app import repositories as repo
from app.agent.models import CaseInput, Document, Line
from app.agent.pipeline import analyze
from app.agent.roles import Drafter, Extractor, Planner, ReadAllPlanner, RuleExtractor, TemplateDrafter
from app.db import tenant_session


class Roles:
    def __init__(self, planner: Planner, extractor: Extractor, drafter: Drafter, label: str) -> None:
        self.planner, self.extractor, self.drafter, self.label = planner, extractor, drafter, label


def baseline_roles() -> Roles:
    return Roles(ReadAllPlanner(), RuleExtractor(), TemplateDrafter(), "baseline:ReadAll/RuleExtractor/Template")


def configured_roles() -> Roles:
    """LLM roles when an API key is configured, otherwise the deterministic baseline."""
    import os
    if not os.environ.get("SAL_LLM_API_KEY"):
        return baseline_roles()
    from app.agent.llm import LLMRoles
    llm = LLMRoles()
    return Roles(ReadAllPlanner(), llm, llm, f"llm:{llm.model}")


def _requested(payload: dict[str, Any] | None) -> tuple[str, ...]:
    return tuple(e["evidence_type"] for e in (payload or {}).get("evidences") or []
                 if e.get("source") == "REQUESTED_FROM_SELLER" and e.get("evidence_type"))


def load_case(engine: Engine | None, merchant_id: UUID, dispute_id: UUID) -> tuple[CaseInput, int] | None:
    with tenant_session(merchant_id, engine) as s:
        d = s.execute(text("""SELECT id, case_ref, provider_dispute_id, reason, amount, currency, version,
                                     provider_payload FROM disputes WHERE id = :id"""), {"id": dispute_id}).first()
        if d is None:
            return None
        rows = s.execute(text("""SELECT coalesce(source_ref, id::text) AS evidence_id, doc_type, content_lines
                                 FROM evidence WHERE dispute_id = :id AND content_lines IS NOT NULL
                                 ORDER BY uploaded_at, id"""), {"id": dispute_id}).all()
    docs = tuple(Document(r.evidence_id, r.doc_type or "unknown",
                          tuple(Line(int(l["line"]), str(l["text"])) for l in r.content_lines)) for r in rows)
    case = CaseInput(d.case_ref or d.provider_dispute_id, d.reason, f"{d.amount:.2f}", d.currency,
                     _requested(d.provider_payload), docs)
    return case, d.version


def run_analysis(merchant_id: UUID, dispute_id: UUID, job_id: UUID | None, roles: Roles,
                 engine: Engine | None = None) -> dict[str, Any]:
    loaded = load_case(engine, merchant_id, dispute_id)
    if loaded is None:
        return {"skipped": "dispute not found"}
    case, version = loaded

    result = analyze(case, roles.planner, roles.extractor, roles.drafter)

    claims = [asdict(c) for c in result.claims]
    body = "\n".join(c.text for c in result.claims)
    with tenant_session(merchant_id, engine) as s:
        current = s.execute(text("SELECT version FROM disputes WHERE id = :id FOR UPDATE"),
                            {"id": dispute_id}).scalar()
        if current != version:  # dispute moved on while we were analyzing
            repo.enqueue_job(s, merchant_id, "analyze_dispute", f"analyze:{dispute_id}:v{current}", dispute_id)
            return {"discarded": "stale", "analyzed_version": version, "current_version": current}

        run_id = s.execute(text("""
            INSERT INTO agent_runs (merchant_id, dispute_id, job_id, roles, status, steps, ended_at)
            VALUES (:m, :d, :j, :roles, 'SUCCEEDED', :steps, now()) RETURNING id"""),
            {"m": merchant_id, "d": dispute_id, "j": job_id, "roles": roles.label,
             "steps": len(result.tool_calls)}).scalar_one()
        for call in result.tool_calls:
            s.execute(text("""INSERT INTO tool_calls (merchant_id, agent_run_id, step, tool, args, ok, summary)
                              VALUES (:m, :r, :step, :tool, CAST(:args AS jsonb), :ok, :summary)"""),
                      {"m": merchant_id, "r": run_id, "step": call.step, "tool": call.tool,
                       "args": json.dumps(call.args), "ok": call.ok, "summary": call.summary})
        analysis_id = s.execute(text("""
            INSERT INTO analyses (merchant_id, dispute_id, agent_run_id, dispute_version, rule_version, facts,
                                  findings, review_required, snapshot_hash)
            VALUES (:m, :d, :r, :v, :rv, CAST(:facts AS jsonb), CAST(:findings AS jsonb), :review, :hash)
            RETURNING id"""),
            {"m": merchant_id, "d": dispute_id, "r": run_id, "v": version, "rv": result.rule_version,
             "facts": json.dumps([asdict(f) for f in result.facts]),
             "findings": json.dumps([asdict(f) for f in result.findings]),
             "review": result.review_required, "hash": result.snapshot_hash}).scalar_one()
        s.execute(text("UPDATE drafts SET status = 'SUPERSEDED' WHERE dispute_id = :d AND status = 'DRAFT'"),
                  {"d": dispute_id})
        revision = s.execute(text("""
            INSERT INTO drafts (merchant_id, dispute_id, revision, body, payload_hash, analysis_id, claims)
            SELECT :m, :d, coalesce(max(revision), 0) + 1, :body, :ph, :a, CAST(:claims AS jsonb)
            FROM drafts WHERE dispute_id = :d
            RETURNING revision"""),
            {"m": merchant_id, "d": dispute_id, "body": body, "ph": hashlib.sha256(body.encode()).hexdigest(),
             "a": analysis_id, "claims": json.dumps(claims)}).scalar_one()
        s.execute(text("UPDATE disputes SET internal_state = 'NEEDS_REVIEW', updated_at = now() WHERE id = :d"),
                  {"d": dispute_id})
        repo.write_audit(s, merchant_id, "agent", "analysis.completed", target=str(dispute_id),
                         summary={"run": str(run_id), "revision": revision, "findings": len(result.findings),
                                  "review_required": result.review_required})
    return {"agent_run_id": str(run_id), "analysis_id": str(analysis_id), "draft_revision": revision,
            "findings": len(result.findings), "claims": len(claims), "review_required": result.review_required}
