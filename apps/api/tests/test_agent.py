"""Agent pipeline: guardrails against a misbehaving model, and the golden-dataset harness. Offline."""
from __future__ import annotations

import json

import pytest

from app.agent.evaluate import evaluate, load_cases, to_case_input
from app.agent.models import CandidateFact, Claim, SourceRef
from app.agent.pipeline import StepBudgetExceeded, analyze, gather
from app.agent.roles import ReadAllPlanner, RuleExtractor, TemplateDrafter
from tests.fakes import openai


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
    status = {f.field: f.status for f in conflicting.facts}
    assert status["reported_payment_amount"] == "conflicted" and status["payment_amount"] == "supported"

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


# --------------------------------------------------------------- LLM adapter (no network)
class _FakeCompletions:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        parsed = self.outputs.pop(0)
        msg = type("M", (), {"parsed": parsed})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


def _fake_client(outputs):
    completions = _FakeCompletions(outputs)
    return type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})(), completions


def test_llm_output_still_goes_through_grounding_and_claim_checks(monkeypatch):
    monkeypatch.delenv("SAL_LLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("SAL_LLM_REASONING_EFFORT", raising=False)
    from app.agent.llm import LLMRoles, _Claim, _Claims, _Fact, _Facts
    facts = _Facts(facts=[
        _Fact(field="transaction_id", value="TXN-SYN-100000", evidence_id="SAL-INR-001-E02", line=1,
              quote="SYNTHETIC PAYMENT RECORD | TXN-SYN-100000"),
        _Fact(field="payment_amount", value="45.00", evidence_id="SAL-INR-001-E02", line=2,
              quote="Settled amount: 45.00 USD"),
        _Fact(field="delivery_date", value="2026-07-09", evidence_id="SAL-INR-001-E04", line=3,  # hallucinated
              quote="Delivery date: 2026-07-09"),
    ])
    claims = _Claims(claims=[
        _Claim(text="The payment record references transaction TXN-SYN-100000.", fact_fields=["transaction_id"]),
        _Claim(text="Delivery was confirmed on 2026-07-09.", fact_fields=["delivery_date"]),
    ])
    client, completions = _fake_client([facts, claims])
    llm = LLMRoles(client=openai(client), model="test-model")
    result = analyze(case("SAL-INR-001"), ReadAllPlanner(), llm, llm)
    assert [(f.field, f.status) for f in result.facts] == [("transaction_id", "supported"),
                                                           ("payment_amount", "supported"),
                                                           ("delivery_date", "rejected")]
    assert [c.text for c in result.claims] == ["The payment record references transaction TXN-SYN-100000."]
    # nothing the model might reject is sent unless configured (gpt-5 models refuse temperature)
    assert "temperature" not in completions.calls[0] and "reasoning_effort" not in completions.calls[0]
    assert completions.calls[0]["max_completion_tokens"] > 0
    assert "untrusted" in completions.calls[0]["messages"][0]["content"].lower() or \
        "never follow" in completions.calls[0]["messages"][0]["content"].lower()


def test_llm_sends_only_configured_options(monkeypatch):
    from app.agent.llm import LLMRoles
    monkeypatch.setenv("SAL_LLM_REASONING_EFFORT", "low")
    monkeypatch.delenv("SAL_LLM_TEMPERATURE", raising=False)
    assert LLMRoles(client=openai(object()), model="gpt-5-nano").options == {"max_completion_tokens": 4000,
                                                                      "reasoning_effort": "low"}
    monkeypatch.delenv("SAL_LLM_REASONING_EFFORT")
    monkeypatch.setenv("SAL_LLM_TEMPERATURE", "0")
    from app.config import get_settings
    get_settings.cache_clear()  # settings are read once per process; this test changes them mid-way
    assert LLMRoles(client=openai(object()), model="gpt-4.1-nano").options["temperature"] == 0.0


def test_llm_needs_a_model(monkeypatch):
    from app.agent.llm import LLMRoles
    monkeypatch.delenv("SAL_LLM_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="SAL_LLM_MODEL"):
        LLMRoles(client=openai(object()))


def test_union_extractor_keeps_rule_facts_when_the_model_misses_them():
    from app.agent.roles import RuleExtractor, UnionExtractor

    class ForgetfulModel:  # finds nothing, as a weak model sometimes does
        def extract(self, documents):
            return []

    result = analyze(case("SAL-INR-021"), ReadAllPlanner(), UnionExtractor(RuleExtractor(), ForgetfulModel()),
                     TemplateDrafter())
    assert any(f.field == "delivery_date" for f in result.findings)  # the date conflict is still found


def test_reply_only_states_what_the_evidence_proves():
    """ADR-005: a tracking number is a fact, but without proof the parcel moved, 'shipped' is not proven,
    so the reply must not claim it; the payment, proven by the PayPal record, may be stated."""
    from app.agent.models import CaseInput, Document, Line
    docs = (Document("pp", "payment_record", (Line(1, "PayPal transaction record"), Line(2, "Amount: 45.00 USD")),
                     "PAYPAL_API"),
            Document("trk", "carrier_tracking", (Line(1, "Tracking: TRK-SYN-70000"),)))
    case_in = CaseInput("T-1", "ITEM_NOT_RECEIVED", "45.00", "USD", (), docs)

    class Extract:
        def extract(self, documents):
            return [CandidateFact("payment_amount", "45.00", SourceRef("pp", 2), "Amount: 45.00 USD"),
                    CandidateFact("tracking_id", "TRK-SYN-70000", SourceRef("trk", 1), "Tracking: TRK-SYN-70000")]

    class Draft:
        def draft(self, facts, findings):
            fields = {f.field for f in facts}
            assert "tracking_id" not in fields  # the drafter never even sees unproven facts
            return [Claim("PayPal recorded a payment of 45.00.", ("payment_amount",)),
                    Claim("We shipped it with tracking TRK-SYN-70000.", ("tracking_id",))]

    r = analyze(case_in, ReadAllPlanner(), Extract(), Draft())
    assert r.assessment.status("payment_matches") == "proven" and r.assessment.status("shipped") == "missing"
    assert [c.text for c in r.claims] == ["PayPal recorded a payment of 45.00."]
    assert r.assessment.readiness == "NEEDS_DOCUMENTS" and r.review_required


def test_an_uploaded_receipt_cannot_prove_a_paypal_payment():
    from app.agent.assess import assess
    from app.agent.models import Document, Fact, Line
    bank = Document("bank", "payment_record", (Line(1, "Bank transfer 45.00 USD"),), "UPLOAD")
    facts = [Fact("payment_amount", "45.00", SourceRef("bank", 1), "supported")]
    a = assess(facts, [], (bank,), "45.00", "USD")
    assert a.status("payment_matches") == "missing" and "not a PayPal record" in a.propositions[0].reason


def test_unchanged_documents_are_not_sent_to_the_model_again(monkeypatch):
    """Re-analysis after one new upload extracts only that document; everything else is reused."""
    monkeypatch.delenv("SAL_LLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("SAL_LLM_REASONING_EFFORT", raising=False)
    from dataclasses import replace

    from app.agent.llm import LLMRoles, _Fact, _Facts
    from app.agent.models import Line
    c = case("SAL-INR-001")
    docs = list(c.documents)
    payment = next(d for d in docs if d.evidence_id == "SAL-INR-001-E02")
    first = _Facts(facts=[_Fact(field="transaction_id", value="TXN-SYN-100000", evidence_id=payment.evidence_id,
                                line=1, quote="SYNTHETIC PAYMENT RECORD | TXN-SYN-100000")])
    client, completions = _fake_client([first, _Facts(facts=[]), _Facts(facts=[])])

    run1 = LLMRoles(client=openai(client), model="test-model")
    out1 = run1.extract(docs)
    assert len(completions.calls) == 1 and run1.cache == {"hits": 0, "misses": len(docs)}

    run2 = LLMRoles(client=openai(client), model="test-model")  # a later job: same documents
    assert run2.extract(docs) == out1
    assert len(completions.calls) == 1 and run2.cache == {"hits": len(docs), "misses": 0}

    # one document edited (or a new one uploaded): only that one goes to the model
    changed = replace(payment, lines=payment.lines + (Line(99, "Note added later"),))
    run3 = LLMRoles(client=openai(client), model="test-model")
    run3.extract([changed if d is payment else d for d in docs])
    sent = json.loads(completions.calls[1]["messages"][1]["content"])["documents"]
    assert [d["evidence_id"] for d in sent] == [payment.evidence_id]
    assert run3.cache == {"hits": len(docs) - 1, "misses": 1}

    # a different model never reuses another model's extraction
    run4 = LLMRoles(client=openai(client), model="other-model")
    run4.extract(docs)
    assert len(completions.calls) == 3 and run4.cache["hits"] == 0


def test_a_failed_model_call_caches_nothing(monkeypatch):
    monkeypatch.delenv("SAL_LLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("SAL_LLM_REASONING_EFFORT", raising=False)
    from app.agent.llm import LLMRoles, _Facts

    class Down:
        calls = 0

        def parse(self, **kwargs):
            Down.calls += 1
            raise TimeoutError("model down")

    client = type("Client", (), {"chat": type("Chat", (), {"completions": Down()})()})()
    docs = list(case("SAL-INR-001").documents)
    with pytest.raises(TimeoutError):
        LLMRoles(client=openai(client), model="test-model").extract(docs)
    ok_client, completions = _fake_client([_Facts(facts=[])])
    LLMRoles(client=openai(ok_client), model="test-model").extract(docs)
    assert len(completions.calls) == 1  # nothing was cached by the failed attempt


def test_one_merchants_cached_reading_never_serves_another():
    from unittest.mock import MagicMock

    from app.agent.llm import LLMRoles
    roles = LLMRoles(client=MagicMock(), model="test")
    doc = {"evidence_id": "resi:JP1", "type": "seller_shipment", "fields": "", "lines": []}
    roles.cache_scope = "merchant-a"
    key_a = roles._cache_key(doc)
    roles.cache_scope = "merchant-b"
    assert roles._cache_key(doc) != key_a
