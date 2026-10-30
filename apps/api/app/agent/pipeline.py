"""AnalyzeDispute pipeline (Option C): fixed stages, with one bounded agentic stage (gather).

    load -> gather (agent loop, read-only tools, max steps) -> extract -> ground -> rules -> assess
         -> draft (proven propositions only) -> verify claims -> snapshot hash

Pure function over a CaseInput: no DB, no network. The worker persists the result; the evaluation
harness scores it against the golden dataset.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from app.agent.models import RULE_VERSION, AnalysisResult, CaseInput
from app.agent.roles import Drafter, Extractor, Planner
from app.agent.tools import TOOL_SPECS, CaseToolbox
from app.agent.assess import SUPPORTED_REASONS, assess, claimable
from app.agent.validation import apply_inr_rules, ground, verify_claims

MAX_GATHER_STEPS = 8


class StepBudgetExceeded(RuntimeError):
    pass


def gather(case: CaseInput, planner: Planner, max_steps: int = MAX_GATHER_STEPS) -> CaseToolbox:
    box = CaseToolbox(case)
    transcript: list[dict[str, Any]] = []
    for step in range(1, max_steps + 1):
        call = planner.next_call(TOOL_SPECS, transcript)
        if call is None:
            return box
        result = box.call(step, str(call.get("tool")), call.get("args") or {})
        transcript.append({"tool": call.get("tool"), "args": call.get("args") or {}, "result": result})
    if planner.next_call(TOOL_SPECS, transcript) is not None:
        raise StepBudgetExceeded(f"gather did not finish within {max_steps} steps")
    return box


def analyze(case: CaseInput, planner: Planner, extractor: Extractor, drafter: Drafter,
            max_steps: int = MAX_GATHER_STEPS) -> AnalysisResult:
    box = gather(case, planner, max_steps)
    # Only documents the agent actually read are visible to extraction.
    read = [d for d in case.documents if d.evidence_id in set(box.read_ids)]

    facts = ground(extractor.extract(read), read)
    inr = case.reason in SUPPORTED_REASONS  # the shipping rules: courier documents, dates, address, timeline
    findings = apply_inr_rules(facts, case.documents, case.amount, case.currency, inr=inr)
    assessment = assess(facts, findings, case.documents, case.amount, case.currency, case.reason,
                        case.requested_evidence)
    # The reply may only state what the evidence proves (ADR-005).
    allowed = claimable(facts, assessment)
    claims, rejected = verify_claims(drafter.draft(allowed, findings), allowed)

    result = AnalysisResult(
        rule_version=RULE_VERSION, facts=facts, findings=findings, claims=claims, rejected_claims=rejected,
        review_required=bool(findings) or bool(rejected) or assessment.readiness != "READY",
        tool_calls=box.records, assessment=assessment)
    result.snapshot_hash = snapshot_hash(result)
    return result


def snapshot_hash(result: AnalysisResult) -> str:
    """Hash of what an approval will be bound to: facts, findings, claims and rule version."""
    payload = {"rule_version": result.rule_version,
               "facts": [asdict(f) for f in result.facts],
               "findings": [asdict(f) for f in result.findings],
               "claims": [asdict(c) for c in result.claims],
               "assessment": asdict(result.assessment) if result.assessment else None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
