"""Agent persistence through the worker, against Postgres."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app import repositories as repo
from app import worker
from app.agent.runner import baseline_roles, run_analysis
from app.db import tenant_session
from app.seed import create_merchant

pytestmark = pytest.mark.db


def seed_golden(app_engine, merchant: UUID, case_id: str) -> UUID:
    from app.seed_demo import seed_golden as seed
    dispute_id = seed(app_engine, merchant, case_id)
    with tenant_session(merchant, app_engine) as s:
        version = s.execute(text("SELECT version FROM disputes WHERE id = :d"), {"d": dispute_id}).scalar()
        repo.enqueue_job(s, merchant, "analyze_dispute", f"analyze:{dispute_id}:v{version}", dispute_id)
    return dispute_id


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Agent-{uuid4().hex[:6]}")


@pytest.fixture
def ctx(worker_engine):
    return worker.Context(worker_engine, lambda: None)


def test_worker_runs_agent_and_persists_everything(merchant, ctx, app_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-021")  # conflicting scenario
    while worker.run_one_job(ctx):
        pass
    with tenant_session(merchant, app_engine) as s:
        state = s.execute(text("SELECT internal_state FROM disputes WHERE id = :d"), {"d": dispute_id}).scalar()
        a = s.execute(text("SELECT findings, review_required, snapshot_hash FROM analyses WHERE dispute_id = :d"),
                      {"d": dispute_id}).one()
        draft = s.execute(text("SELECT revision, status, claims FROM drafts WHERE dispute_id = :d"),
                          {"d": dispute_id}).one()
        tools = s.execute(text("""SELECT tool, ok FROM tool_calls t JOIN agent_runs r ON r.id = t.agent_run_id
                                  WHERE r.dispute_id = :d ORDER BY step"""), {"d": dispute_id}).all()
    assert state == "NEEDS_REVIEW"
    assert {f["field"] for f in a.findings} == {"delivery_date", "reported_payment_amount"} and a.review_required
    assert len(a.snapshot_hash) == 64
    assert draft.revision == 1 and draft.status == "DRAFT" and draft.claims
    assert tools[0] == ("list_evidence", True) and all(ok for _, ok in tools) and len(tools) == 6


def test_reanalysis_supersedes_previous_draft(merchant, app_engine, worker_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    with tenant_session(merchant, app_engine) as s:
        rows = s.execute(text("SELECT revision, status FROM drafts WHERE dispute_id = :d ORDER BY revision"),
                         {"d": dispute_id}).all()
    assert [tuple(r) for r in rows] == [(1, "SUPERSEDED"), (2, "DRAFT")]


def test_stale_analysis_is_discarded_and_requeued(merchant, app_engine, worker_engine, monkeypatch):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    from app.agent import runner
    real_analyze = runner.analyze

    def analyze_while_dispute_changes(*args, **kwargs):
        result = real_analyze(*args, **kwargs)
        with tenant_session(merchant, app_engine) as s:  # PayPal update lands mid-analysis
            s.execute(text("UPDATE disputes SET version = version + 1 WHERE id = :d"), {"d": dispute_id})
        return result

    monkeypatch.setattr(runner, "analyze", analyze_while_dispute_changes)
    out = run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    assert out["discarded"] == "stale"
    with tenant_session(merchant, app_engine) as s:
        assert s.execute(text("SELECT count(*) FROM drafts WHERE dispute_id = :d"), {"d": dispute_id}).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM jobs WHERE idempotency_key = :k"),
                         {"k": f"analyze:{dispute_id}:v{out['current_version']}"}).scalar() == 1


def test_agent_records_are_append_only_and_not_writable_by_api(merchant, app_engine, worker_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    for stmt in ("UPDATE analyses SET review_required = true", "DELETE FROM tool_calls",
                 "INSERT INTO tool_calls (merchant_id, agent_run_id, step, tool, ok, summary) "
                 "SELECT merchant_id, id, 99, 'provide_evidence', true, 'forged' FROM agent_runs"):
        with pytest.raises(ProgrammingError):
            with tenant_session(merchant, app_engine) as s:
                s.execute(text(stmt))
    with pytest.raises(ProgrammingError, match="permission denied"):  # worker: no UPDATE grant
        with tenant_session(merchant, worker_engine) as s:
            s.execute(text("UPDATE analyses SET review_required = true"))
    from sqlalchemy import create_engine
    from app.config import get_settings
    owner = create_engine(get_settings().migrator_database_url)
    try:
        with pytest.raises(ProgrammingError, match="append-only"):  # even the table owner hits the trigger
            with tenant_session(merchant, owner) as s:
                s.execute(text("UPDATE analyses SET review_required = true"))
    finally:
        owner.dispose()


def test_other_tenant_cannot_see_agent_output(merchant, app_engine, worker_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    other = create_merchant("Other")
    with tenant_session(other, app_engine) as s:
        for table in ("analyses", "agent_runs", "tool_calls", "drafts"):
            assert s.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_analysis_endpoint_is_tenant_scoped(merchant, app_engine, worker_engine):
    from fastapi.testclient import TestClient

    from app.main import app, current_merchant
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-011")  # missing evidence
    run_analysis(merchant, dispute_id, None, baseline_roles(), worker_engine)
    client = TestClient(app)
    try:
        app.dependency_overrides[current_merchant] = lambda: merchant
        body = client.get(f"/api/disputes/{dispute_id}/analysis").json()
        assert {f["field"] for f in body["findings"] if f["kind"] == "missing"} == {"carrier_tracking", "delivery_proof"}
        assert body["draft"]["revision"] == 1 and body["agent"]["tool_calls"][0]["tool"] == "list_evidence"
        app.dependency_overrides[current_merchant] = lambda: create_merchant("Snoop")
        assert client.get(f"/api/disputes/{dispute_id}/analysis").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_evidence_endpoint_is_tenant_scoped(merchant, app_engine):
    from fastapi.testclient import TestClient

    from app.main import app, current_merchant
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    client = TestClient(app)
    try:
        app.dependency_overrides[current_merchant] = lambda: merchant
        items = client.get(f"/api/disputes/{dispute_id}/evidence").json()["items"]
        assert [i["evidence_id"] for i in items][:2] == ["SAL-INR-001-E01", "SAL-INR-001-E02"]
        assert items[0]["lines"][0] == {"line": 1, "text": "SYNTHETIC INVOICE | ORD-SYN-4000"}
        app.dependency_overrides[current_merchant] = lambda: create_merchant("Snoop2")
        assert client.get(f"/api/disputes/{dispute_id}/evidence").json()["items"] == []
    finally:
        app.dependency_overrides.clear()


def test_llm_failure_falls_back_to_baseline_and_says_so(merchant, app_engine, worker_engine):
    from app.agent.roles import ReadAllPlanner, TemplateDrafter
    from app.agent.runner import Roles

    class DownExtractor:
        def extract(self, documents):
            raise TimeoutError("model did not answer")

    roles = Roles(ReadAllPlanner(), DownExtractor(), TemplateDrafter(), "llm:test-model", fallback=baseline_roles())
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-011")
    out = run_analysis(merchant, dispute_id, None, roles, worker_engine)
    assert out["findings"] >= 2  # missing tracking + delivery proof still detected without the model
    with tenant_session(merchant, app_engine) as s:
        label = s.execute(text("SELECT roles FROM agent_runs WHERE dispute_id = :d"), {"d": dispute_id}).scalar()
    assert label.startswith("baseline:") and "LLM unavailable: TimeoutError" in label
