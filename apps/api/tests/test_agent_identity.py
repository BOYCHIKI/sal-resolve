"""Agent identity: each agent has its own revocable credential, and may only do what its role allows."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import agent_identity
from app.agent_identity import AgentRole
from app.config import get_settings
from app.db import tenant_session
from app.main import app, current_merchant
from app.seed import create_merchant
from tests.test_deals import invoice_body, order_body

ORDER_URL = "/agent/v1/deals"
INVOICE_URL = "/agent/v1/deals/PO-7781/invoice"
DEAL_URL = "/agent/v1/deals/PO-7781"
BUYER = "buyer-agent:garage-01"


def test_roles_in_code_match_the_database_check():
    sql = next(Path(__file__).resolve().parents[1].glob("migrations/sql/*_agent_credentials.sql")).read_text(encoding="utf-8")
    declared = re.search(r"AgentRole: (.+)", sql)
    assert declared, "the migration documents the roles"
    assert set(re.findall(r"[A-Z_]{3,}", declared.group(1))) == {r.value for r in AgentRole}


def as_agent(token: str) -> TestClient:
    return TestClient(app, headers={"authorization": f"Bearer {token}"})


@pytest.fixture
def merchant(migrated_db, app_engine, monkeypatch) -> UUID:
    monkeypatch.setattr("app.deals.app_engine", lambda: app_engine)
    return create_merchant(f"Agent-{uuid4().hex[:6]}")


@pytest.fixture
def buyer(merchant, app_engine) -> TestClient:
    return as_agent(agent_identity.issue(merchant, BUYER, AgentRole.BUYER_AGENT, app_engine))


@pytest.fixture
def seller(merchant, app_engine) -> TestClient:
    return as_agent(agent_identity.issue(merchant, "seller-agent:shop", AgentRole.SELLER_AGENT, app_engine))


@pytest.mark.db
def test_only_the_hash_of_a_token_is_stored(merchant, app_engine):
    token = agent_identity.issue(merchant, BUYER, AgentRole.BUYER_AGENT, app_engine)
    with tenant_session(merchant, app_engine) as s:
        stored = s.execute(text("SELECT token_hash FROM agent_credentials")).scalar_one()
    assert token.rsplit(".", 1)[1] not in stored and token not in stored and len(stored) == 64


@pytest.mark.db
def test_a_token_names_its_agent(merchant, app_engine):
    token = agent_identity.issue(merchant, BUYER, AgentRole.BUYER_AGENT, app_engine)
    agent = agent_identity.authenticate(token, app_engine)
    assert agent is not None
    assert (agent.merchant_id, agent.name, agent.role) == (merchant, BUYER, AgentRole.BUYER_AGENT)


@pytest.mark.db
@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer nonsense", "Basic abc", "Bearer salagent.x.y",
                                    "Bearer salagent.aaaaaaaa-0000-4000-8000-000000000001.wrong"])
def test_anything_but_a_valid_token_gets_the_same_refusal(migrated_db, header):
    r = TestClient(app).post(ORDER_URL, json=order_body(),
                             headers={"authorization": header} if header is not None else {})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "AGENT_UNAUTHORIZED"


@pytest.mark.db
def test_a_secret_never_works_under_another_merchant(merchant, app_engine):
    token = agent_identity.issue(merchant, BUYER, AgentRole.BUYER_AGENT, app_engine)
    other = create_merchant(f"Agent-{uuid4().hex[:6]}")
    forged = token.replace(str(merchant), str(other))
    assert agent_identity.authenticate(forged, app_engine) is None


@pytest.mark.db
def test_a_revoked_token_stops_at_once(merchant, app_engine):
    token = agent_identity.issue(merchant, BUYER, AgentRole.BUYER_AGENT, app_engine)
    agent = agent_identity.authenticate(token, app_engine)
    assert agent is not None
    assert agent_identity.revoke(merchant, agent.id, app_engine) is True
    assert as_agent(token).post(ORDER_URL, json=order_body()).status_code == 401


@pytest.mark.db
def test_an_expired_token_stops(merchant, app_engine):
    token = agent_identity.issue(merchant, BUYER, AgentRole.BUYER_AGENT, app_engine)
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("UPDATE agent_credentials SET expires_at = :t"),
                  {"t": datetime.now(timezone.utc) - timedelta(seconds=1)})
    assert agent_identity.authenticate(token, app_engine) is None


@pytest.mark.db
def test_a_buyer_agent_orders_and_a_seller_agent_invoices_not_the_reverse(buyer, seller):
    assert seller.post(ORDER_URL, json=order_body()).status_code == 403
    assert buyer.post(ORDER_URL, json=order_body()).status_code == 201
    assert buyer.put(INVOICE_URL, json=invoice_body()).status_code == 403
    assert seller.put(INVOICE_URL, json=invoice_body()).status_code == 200


@pytest.mark.db
def test_an_agent_cannot_order_in_another_agents_name(buyer):
    r = buyer.post(ORDER_URL, json=order_body(approved_by="buyer-agent:the-boss"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "AGENT_NAME_MISMATCH"


@pytest.mark.db
def test_a_buyer_agent_sees_only_its_own_deals(buyer, seller, merchant, app_engine):
    buyer.post(ORDER_URL, json=order_body())
    assert buyer.get(DEAL_URL).status_code == 200 and seller.get(DEAL_URL).status_code == 200
    rival = as_agent(agent_identity.issue(merchant, "buyer-agent:rival", AgentRole.BUYER_AGENT, app_engine))
    assert rival.get(DEAL_URL).status_code == 404


@pytest.mark.db
def test_the_audit_names_the_verified_agent(buyer, seller, merchant, app_engine):
    buyer.post(ORDER_URL, json=order_body())
    seller.put(INVOICE_URL, json=invoice_body())
    with tenant_session(merchant, app_engine) as s:
        rows = dict(s.execute(text("SELECT action, actor FROM audit_logs WHERE action LIKE 'deal.%'")).all())
    assert rows == {"deal.ordered": f"agent:{BUYER}", "deal.invoiced": "agent:seller-agent:shop"}


@pytest.mark.db
def test_one_merchants_agent_never_reaches_anothers_deal(buyer, app_engine):
    buyer.post(ORDER_URL, json=order_body())
    other = create_merchant(f"Agent-{uuid4().hex[:6]}")
    outsider = as_agent(agent_identity.issue(other, "seller-agent:other", AgentRole.SELLER_AGENT, app_engine))
    assert outsider.get(DEAL_URL).status_code == 404
    assert outsider.put(INVOICE_URL, json=invoice_body()).status_code == 404


@pytest.mark.db
def test_the_web_side_of_deals_only_reads(merchant):
    app.dependency_overrides[current_merchant] = lambda: merchant
    try:
        web = TestClient(app)
        assert web.post("/api/deals", json=order_body()).status_code == 405
        assert web.put("/api/deals/PO-7781/invoice", json=invoice_body()).status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.db
def test_with_an_internal_token_agents_pass_and_nothing_else_opens(buyer, monkeypatch):
    monkeypatch.setenv("SAL_INTERNAL_TOKEN", "x" * 40)
    get_settings.cache_clear()
    assert buyer.post(ORDER_URL, json=order_body()).status_code == 201
    assert buyer.get("/api/deals").status_code == 401
    assert buyer.get("/agent/v1/../../api/deals").status_code == 401


@pytest.mark.db
def test_repeated_bad_tokens_are_slowed_and_good_ones_are_not_counted(buyer):
    stranger = TestClient(app, headers={"authorization": "Bearer nonsense"})
    for _ in range(agent_identity.MAX_FAILURES):
        assert stranger.get(DEAL_URL).status_code == 401
    assert stranger.get(DEAL_URL).status_code == 429
    assert buyer.get(DEAL_URL).status_code == 429   # same address, so the same limit
    agent_identity.failed_attempts.clear()
    assert buyer.post(ORDER_URL, json=order_body()).status_code == 201
