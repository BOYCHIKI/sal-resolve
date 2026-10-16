"""Operations: health, the ops summary, structured logs, LLM usage on agent runs."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import logs
from app import repositories as repo
from app.agent.roles import ReadAllPlanner, TemplateDrafter
from app.agent.runner import Roles, baseline_roles, run_analysis
from app.db import tenant_session
from app.main import app, current_merchant
from app.seed import create_merchant
from app.seed_demo import seed_golden


def test_json_logs_carry_the_case_being_worked_on():
    record = logging.LogRecord("sal.worker", logging.INFO, __file__, 1, "job %s succeeded", ("analyze",), None)
    record.duration_ms = 1234
    token = logs.dispute_id.set("d-1")
    try:
        entry = json.loads(logs.JsonFormatter().format(record))
    finally:
        logs.dispute_id.reset(token)
    assert entry["msg"] == "job analyze succeeded" and entry["dispute_id"] == "d-1" and entry["duration_ms"] == 1234


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Ops-{uuid4().hex[:6]}")


@pytest.fixture
def client(merchant):
    app.dependency_overrides[current_merchant] = lambda: merchant
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.db
def test_health_reports_a_worker_that_stopped_beating(client, worker_engine):
    with Session(worker_engine) as s, s.begin():
        s.execute(text("""INSERT INTO worker_heartbeats (worker_id, seen_at) VALUES ('old', now() - interval '1 hour')
                          ON CONFLICT (worker_id) DO UPDATE SET seen_at = EXCLUDED.seen_at"""))
    body = client.get("/api/health").json()
    if body["worker"]["seconds_since"] >= 60:  # no fresher heartbeat from another test
        assert body["status"] == "degraded" and body["worker"]["alive"] is False
    with Session(worker_engine) as s, s.begin():
        repo.worker_heartbeat(s, "test-worker", 3)
    body = client.get("/api/health").json()
    assert body == {**body, "status": "ok", "database": "ok"} and body["worker"]["alive"] is True


@pytest.mark.db
def test_ops_shows_failures_fallbacks_and_llm_tokens(client, merchant, app_engine, worker_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")

    class Down:  # an LLM that answers once (tokens spent) and then fails
        usage = {"input_tokens": 1200, "output_tokens": 300}

        def extract(self, documents):
            raise TimeoutError("model did not answer")

    roles = Roles(ReadAllPlanner(), Down(), TemplateDrafter(), "llm:test", fallback=baseline_roles())
    roles.drafter = SimpleNamespace(usage=Down.usage, draft=TemplateDrafter().draft)
    run_analysis(merchant, dispute_id, None, roles, worker_engine)
    with tenant_session(merchant, worker_engine) as s:  # only the worker role may change jobs
        repo.enqueue_job(s, merchant, "analyze_dispute", f"ops-test:{dispute_id}", dispute_id)
        s.execute(text("UPDATE jobs SET state = 'FAILED', last_error = 'boom' WHERE idempotency_key = :k"),
                  {"k": f"ops-test:{dispute_id}"})
    body = client.get("/api/ops").json()
    assert body["agent_last_24h"]["llm_fallbacks"] == 1
    assert (body["agent_last_24h"]["llm_input_tokens"], body["agent_last_24h"]["llm_output_tokens"]) == (1200, 300)
    assert body["failed_last_24h"][0]["error"] == "boom" and body["queue"]["FAILED"] == 1
