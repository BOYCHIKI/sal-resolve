"""The /demo agent run: one at a time, a daily cap, no retry after a failure, and the steps kept on the job.
The agents themselves are faked; app/ai_agents.py is exercised live (it needs a model)."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import ai_agents, worker
from app import main as main_module
from app.config import get_settings
from app.db import worker_engine
from app.main import app, current_merchant
from app.seed import create_merchant
from tests.fakes import NO_PAYPAL

pytestmark = pytest.mark.db


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"AgentRun-{uuid4().hex[:6]}")


@pytest.fixture
def client(merchant, monkeypatch):
    monkeypatch.setenv("SAL_LLM_API_KEY", "test-key")
    monkeypatch.setenv("SAL_LLM_MODEL", "test-model")
    get_settings.cache_clear()
    app.dependency_overrides[current_merchant] = lambda: merchant
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def ctx(worker_engine):
    context = worker.Context(worker_engine, NO_PAYPAL)
    worker.drain(context)   # jobs other modules left due run first
    return context


def _run_jobs(ctx) -> None:
    for _ in range(20):
        if not worker.run_one_job(ctx, slow=True):
            return


def test_a_run_records_every_step_on_the_job(client, ctx, monkeypatch):
    def fake_run(merchant_id, llm, record):
        record({"actor": "Buyer's agent", "text": "create_order", "sal": "WAITING_INVOICE"})
        record({"actor": "Buyer's agent", "text": "PAY. It is clear.", "sal": None})
        return "PO-FAKE"

    monkeypatch.setattr(ai_agents, "llm_client", lambda: None)
    monkeypatch.setattr(ai_agents, "run", fake_run)
    assert client.get("/api/agent-runs/latest").json() == {"run": None}
    started = client.post("/api/agent-runs").json()["run"]
    assert started["state"] == "QUEUED"
    assert client.post("/api/agent-runs").json()["run"]["id"] == started["id"]   # one at a time
    _run_jobs(ctx)
    run = client.get("/api/agent-runs/latest").json()["run"]
    assert run["state"] == "SUCCEEDED"
    assert run["result"]["deal_ref"] == "PO-FAKE" and len(run["result"]["steps"]) == 2


def test_a_failed_run_is_not_retried(client, ctx, monkeypatch, merchant):
    def broken_run(merchant_id, llm, record):
        record({"actor": "Buyer's agent", "text": "create_order", "sal": "REFUSED: AGENT_NAME_MISMATCH"})
        raise ai_agents.AgentRunFailed("The buyer's agent did not place the order.")

    monkeypatch.setattr(ai_agents, "llm_client", lambda: None)
    monkeypatch.setattr(ai_agents, "run", broken_run)
    client.post("/api/agent-runs")
    _run_jobs(ctx)
    run = client.get("/api/agent-runs/latest").json()["run"]
    assert run["state"] == "FAILED" and "after 1 steps" in run["error"]
    with ctx.engine.begin() as conn:
        attempts = conn.execute(text("SELECT attempts FROM jobs WHERE id = :i"), {"i": run["id"]}).scalar()
    assert attempts == 1


def test_runs_are_capped_per_day(client, monkeypatch):
    monkeypatch.setattr(main_module, "AGENT_RUNS_PER_DAY", 1)
    first = client.post("/api/agent-runs").json()["run"]
    with worker_engine().begin() as conn:   # finish the first run so only the cap stands in the way
        conn.execute(text("UPDATE jobs SET state = 'SUCCEEDED' WHERE id = :i"), {"i": first["id"]})
    refused = client.post("/api/agent-runs")
    assert refused.status_code == 429 and refused.json()["detail"]["code"] == "AGENT_RUNS_USED_UP"


def test_agent_runs_never_block_the_lane_that_checks_deals(client, ctx, monkeypatch):
    monkeypatch.setattr(ai_agents, "llm_client", lambda: None)
    monkeypatch.setattr(ai_agents, "run", lambda merchant_id, llm, record: "PO-FAKE")
    client.post("/api/agent-runs")
    while worker.run_one_job(ctx):    # the main lane runs everything else and leaves the agent run queued
        pass
    assert client.get("/api/agent-runs/latest").json()["run"]["state"] == "QUEUED"
    _run_jobs(ctx)
    assert client.get("/api/agent-runs/latest").json()["run"]["state"] == "SUCCEEDED"


def test_no_model_configured_is_503(merchant, monkeypatch):
    monkeypatch.setenv("SAL_LLM_API_KEY", "")
    app.dependency_overrides[current_merchant] = lambda: merchant
    try:
        response = TestClient(app).post("/api/agent-runs")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503 and response.json()["detail"]["code"] == "LLM_NOT_CONFIGURED"
