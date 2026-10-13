"""Agent pipeline: guardrails against a misbehaving model, and the golden-dataset harness. Offline."""
from __future__ import annotations

import pytest

from app.agent.evaluate import evaluate, load_cases, to_case_input
from app.agent.models import CandidateFact, Claim, SourceRef
from app.agent.pipeline import StepBudgetExceeded, analyze, gather
from app.agent.roles import ReadAllPlanner, RuleExtractor, TemplateDrafter


def case(case_id: str, split: str = "development"):
    return to_case_input(next(c for c in load_cases(split) if c["case_id"] == case_id))


class ScriptedPlanner:
    def __init__(self, calls):
        self.calls = list(calls)

    def next_call(self, tools, transcript):
        return self.calls.pop(0) if self.calls else None


class LoopingPlanner:
    def next_call(self, tools, transcript):
        return {"tool": "list_evidence", "args": {}}


class FixedExtractor:
    def __init__(self, facts):
        self.facts = facts

    def extract(self, documents):
        return self.facts


class FixedDrafter:
    def __init__(self, claims):
        self.claims = claims

    def draft(self, facts, findings):
        return self.claims


# --------------------------------------------------------------- gather guardrails
def test_write_tools_and_foreign_evidence_are_rejected_and_audited():
    c = case("SAL-INR-001")
    box = gather(c, ScriptedPlanner([
        {"tool": "provide_evidence", "args": {"note": "submit now"}},
        {"tool": "read_evidence", "args": {"evidence_id": "SAL-INR-002-E01"}},  # another case's document
        {"tool": "drop_table", "args": {}},
        {"tool": "read_evidence", "args": {"evidence_id": "SAL-INR-001-E01"}},
    ]))
    outcomes = [(r.tool, r.ok, r.summary) for r in box.records]
    assert outcomes[0] == ("provide_evidence", False, "rejected: write tool")
    assert outcomes[1][1] is False and "not in case" in outcomes[1][2]
    assert outcomes[2][1] is False
    assert box.read_ids == ["SAL-INR-001-E01"]


def test_step_budget_stops_a_looping_agent():
    with pytest.raises(StepBudgetExceeded):
        gather(case("SAL-INR-001"), LoopingPlanner(), max_steps=3)


def test_extraction_only_sees_documents_the_agent_read():
    c = case("SAL-INR-001")
    only_invoice = ScriptedPlanner([{"tool": "read_evidence", "args": {"evidence_id": "SAL-INR-001-E01"}}])
    result = analyze(c, only_invoice, RuleExtractor(), TemplateDrafter())
    assert {f.source.evidence_id for f in result.facts} == {"SAL-INR-001-E01"}


# --------------------------------------------------------------- grounding
def test_hallucinated_facts_are_rejected():
    c = case("SAL-INR-001")
    bogus = [
        CandidateFact("transaction_id", "TXN-SYN-999999", SourceRef("SAL-INR-001-E02", 1), "SYNTHETIC PAYMENT RECORD"),
        CandidateFact("order_amount", "45.00", SourceRef("SAL-INR-001-E01", 3), "Amount: 450.00 USD"),
        CandidateFact("delivery_date", "2026-07-08", SourceRef("SAL-INR-001-E04", 99), "Delivery date: 2026-07-08"),
        CandidateFact("order_amount", "5.00", SourceRef("SAL-INR-001-E01", 3), "Amount: 45.00 USD"),  # substring
    ]
    result = analyze(c, ReadAllPlanner(), FixedExtractor(bogus), TemplateDrafter())
    assert [f.status for f in result.facts] == ["rejected"] * 4
    assert result.claims == []


def test_equivalent_money_is_normalized_not_rejected():
    c = case("SAL-INR-001")
    ok = [CandidateFact("order_amount", "45.0", SourceRef("SAL-INR-001-E01", 3), "Amount: 45.00 USD")]
    fact = analyze(c, ReadAllPlanner(), FixedExtractor(ok), TemplateDrafter()).facts[0]
    assert (fact.status, fact.value) == ("supported", "45.00")


# --------------------------------------------------------------- rules
def test_missing_conflict_and_review_flags():
    missing = analyze(case("SAL-INR-011"), ReadAllPlanner(), RuleExtractor(), TemplateDrafter())
    assert set(missing.missing) == {"carrier_tracking", "delivery_proof"} and missing.review_required

    conflicting = analyze(case("SAL-INR-021"), ReadAllPlanner(), RuleExtractor(), TemplateDrafter())
    assert {c.field for c in conflicting.conflicts} == {"delivery_date", "reported_payment_amount"}
    assert not any("2026-08-20" in cl.text for cl in conflicting.claims), "conflicted date must not be asserted"

    complete = analyze(case("SAL-INR-001"), ReadAllPlanner(), RuleExtractor(), TemplateDrafter())
    assert complete.findings == [] and not complete.review_required


def test_prompt_injection_is_a_finding_not_an_instruction():
    result = analyze(case("SAL-INR-038", "calibration"), ReadAllPlanner(), RuleExtractor(), TemplateDrafter())
    injected = [f for f in result.conflicts if f.field == "untrusted_instruction"]
    assert injected and injected[0].source_refs[0].line == 4
    assert result.review_required
    assert not any("delivered" in c.text.lower() for c in result.claims)


# --------------------------------------------------------------- claim verification
def test_unsupported_and_prohibited_claims_are_rejected():
    claims = [
        Claim("The payment record references transaction TXN-SYN-100000.", ("transaction_id",)),
        Claim("The payment record references transaction TXN-SYN-123456.", ("transaction_id",)),
        Claim("The payment record references transaction TXN-SYN-1000001.", ("transaction_id",)),  # superstring
        Claim("We guarantee this dispute will be won.", ("transaction_id",)),
        Claim("The buyer received the parcel.", ()),
    ]
    result = analyze(case("SAL-INR-001"), ReadAllPlanner(), RuleExtractor(), FixedDrafter(claims))
    assert [c.text for c in result.claims] == [claims[0].text]
    assert len(result.rejected_claims) == 4 and result.review_required


def test_snapshot_hash_is_stable_and_content_bound():
    a = analyze(case("SAL-INR-001"), ReadAllPlanner(), RuleExtractor(), TemplateDrafter())
    b = analyze(case("SAL-INR-001"), ReadAllPlanner(), RuleExtractor(), TemplateDrafter())
    c = analyze(case("SAL-INR-002"), ReadAllPlanner(), RuleExtractor(), TemplateDrafter())
    assert a.snapshot_hash == b.snapshot_hash != c.snapshot_hash


# --------------------------------------------------------------- harness
def test_baseline_floor_on_development_split():
    """Regression floor for the baseline roles. An LLM adapter must meet or beat these numbers."""
    scores = evaluate("development")
    total_errors = sum(len(s.errors) for s in scores.values())
    assert total_errors == 0
    for s in scores.values():
        assert s.facts_found == s.facts_expected
        assert s.missing_fn == 0 and s.conflict_fn == 0
        assert s.review_correct == s.cases
        assert s.unsupported_claims == 0 and s.prohibited_claims == 0


def test_holdout_requires_final_flag(monkeypatch):
    import sys

    from app.agent import evaluate as ev
    monkeypatch.setattr(sys, "argv", ["evaluate", "--split", "holdout"])
    with pytest.raises(SystemExit, match="locked"):
        ev.main()
