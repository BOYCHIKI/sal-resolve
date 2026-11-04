"""Tenant isolation and query-permission tests against a real Postgres (SAL v1.1 §7)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from app import repositories as repo
from app.db import tenant_session

pytestmark = pytest.mark.db


def _dispute(pid: str, amount: str = "45.00", currency: str = "USD", deadline=None) -> dict:
    return {"origin": "PAYPAL_SANDBOX", "provider_dispute_id": pid, "custom": "SAL-INR-001",
            "reason": "ITEM_NOT_RECEIVED", "amount": {"value": amount, "currency": currency},
            "provider_status": "WAITING_FOR_SELLER_RESPONSE", "lifecycle_stage": "INQUIRY",
            "response_deadline": deadline, "allowed_actions": ["provide_evidence"]}


@pytest.fixture(scope="module")
def seeded(tenants, app_engine):
    ids = {}
    for name in ("a", "b"):
        with tenant_session(tenants[name], app_engine) as s:
            row, _ = repo.upsert_provider_dispute(s, tenants[name], _dispute(f"PP-{name.upper()}-1"), {})
            ids[name] = row.id
    return ids


# --------------------------------------------------------------- isolation
def test_tenant_sees_only_own_disputes(tenants, seeded, app_engine):
    with tenant_session(tenants["a"], app_engine) as s:
        rows = s.execute(text("SELECT merchant_id, provider_dispute_id FROM disputes")).all()
    assert "PP-A-1" in {r.provider_dispute_id for r in rows}
    assert {r.merchant_id for r in rows} == {tenants["a"]}


def test_other_tenants_dispute_is_invisible_by_id(tenants, seeded, app_engine):
    with tenant_session(tenants["a"], app_engine) as s:
        assert repo.get_dispute(s, seeded["b"]) is None


def test_query_without_tenant_fails_closed(seeded, app_engine):
    with app_engine.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(text("SELECT count(*) FROM disputes"))


def test_tenant_does_not_leak_across_pooled_transactions(tenants, seeded, app_engine):
    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SELECT set_config('app.merchant_id', :m, true)"), {"m": str(tenants["a"])})
            assert conn.execute(text("SELECT count(*) FROM disputes")).scalar() >= 1
        with conn.begin(), pytest.raises(DBAPIError):  # same connection, setting is gone
            conn.execute(text("SELECT count(*) FROM disputes"))


def test_cannot_insert_row_for_another_tenant(tenants, seeded, app_engine):
    with pytest.raises(ProgrammingError, match="row-level security"):
        with tenant_session(tenants["a"], app_engine) as s:
            repo.upsert_provider_dispute(s, tenants["b"], _dispute("PP-SNEAK"), {})


def test_cannot_update_another_tenants_rows(tenants, seeded, app_engine):
    with tenant_session(tenants["a"], app_engine) as s:
        result = s.execute(text("UPDATE disputes SET provider_status = 'RESOLVED' WHERE id = :id RETURNING id"),
                           {"id": seeded["b"]})
        assert result.all() == []


def test_composite_fk_blocks_cross_tenant_evidence(tenants, seeded, app_engine):
    """Even with matching merchant_id, evidence cannot point at another tenant's dispute."""
    with pytest.raises(IntegrityError):
        with tenant_session(tenants["a"], app_engine) as s:
            s.execute(text("""INSERT INTO evidence (merchant_id, dispute_id, object_key, checksum, mime,
                              size_bytes, uploaded_by) VALUES (:m, :d, 'k', 'c', 'application/pdf', 10, 'u')"""),
                      {"m": tenants["a"], "d": seeded["b"]})


# --------------------------------------------------------------- permissions
def test_audit_log_is_append_only(tenants, seeded, app_engine):
    with tenant_session(tenants["a"], app_engine) as s:
        repo.write_audit(s, tenants["a"], "test", "audit.written")
    for stmt in ("UPDATE audit_logs SET action = 'x'", "DELETE FROM audit_logs"):
        with pytest.raises(ProgrammingError, match="permission denied"):
            with tenant_session(tenants["a"], app_engine) as s:
                s.execute(text(stmt))


def test_app_role_cannot_ddl_or_delete(tenants, seeded, app_engine):
    for stmt in ("DELETE FROM disputes", "DROP TABLE disputes", "ALTER TABLE disputes DISABLE ROW LEVEL SECURITY",
                 "SET row_security = off; SELECT 1 FROM disputes"):
        with pytest.raises(ProgrammingError):
            with tenant_session(tenants["a"], app_engine) as s:
                s.execute(text(stmt))


def test_no_runtime_role_can_bypass_rls(app_engine):
    with app_engine.connect() as conn:
        rows = conn.execute(text("""SELECT rolname FROM pg_roles
                                   WHERE rolname LIKE 'sal_%' AND (rolsuper OR rolbypassrls)""")).all()
    assert rows == []


def test_all_tenant_tables_force_rls(app_engine):
    with app_engine.connect() as conn:
        rows = conn.execute(text("""SELECT relname FROM pg_class
            WHERE relname IN ('merchants','disputes','evidence','drafts','approvals','audit_logs','jobs','agent_actions',
                              'packing_proofs','packing_files')
              AND NOT (relrowsecurity AND relforcerowsecurity)""")).all()
    assert rows == []


# --------------------------------------------------------------- data correctness
def test_money_is_exact_and_currency_validated(tenants, seeded, app_engine):
    with tenant_session(tenants["a"], app_engine) as s:
        row, _ = repo.upsert_provider_dispute(s, tenants["a"], _dispute("PP-A-MONEY", "0.10"), {})
        assert row.amount == Decimal("0.10")
    with pytest.raises(IntegrityError):
        with tenant_session(tenants["a"], app_engine) as s:
            repo.upsert_provider_dispute(s, tenants["a"], _dispute("PP-A-BAD", currency="usd"), {})


def test_upsert_bumps_version_only_on_change(tenants, seeded, app_engine):
    with tenant_session(tenants["a"], app_engine) as s:
        _, changed = repo.upsert_provider_dispute(s, tenants["a"], _dispute("PP-A-1"), {})
        row = repo.get_dispute(s, seeded["a"])
        assert row is not None
        before = row.version
    assert changed is False
    moved = dict(_dispute("PP-A-1"), provider_status="WAITING_FOR_BUYER_RESPONSE", allowed_actions=[])
    with tenant_session(tenants["a"], app_engine) as s:
        row, changed = repo.upsert_provider_dispute(s, tenants["a"], moved, {})
    assert changed is True and row.version == before + 1


def test_keyset_pagination_orders_deadline_nulls_last(tenants, migrated_db, app_engine):
    from app.seed import create_merchant
    m = create_merchant("Pager")
    now = datetime.now(timezone.utc)
    with tenant_session(m, app_engine) as s:
        for i, dl in enumerate([now + timedelta(days=3), None, now + timedelta(days=1), None, now + timedelta(days=2)]):
            repo.upsert_provider_dispute(s, m, _dispute(f"PP-P-{i}", deadline=dl), {})
    seen = []
    after = None
    while True:
        with tenant_session(m, app_engine) as s:
            page = repo.list_disputes(s, m, limit=2, after=after)
        seen += page
        if len(page) < 2:
            break
        after = (page[-1].deadline_at, page[-1].id)
    deadlines = [r.deadline_at for r in seen]
    assert len(seen) == 5 and len({r.id for r in seen}) == 5
    assert deadlines[:3] == sorted(deadlines[:3]) and deadlines[3:] == [None, None]


# --------------------------------------------------------------- jobs
def test_jobs_idempotent_and_tenant_scoped_for_app(tenants, seeded, app_engine):
    key = f"sync:{uuid4()}"
    with tenant_session(tenants["a"], app_engine) as s:
        assert repo.enqueue_job(s, tenants["a"], "sync", key) is True
        assert repo.enqueue_job(s, tenants["a"], "sync", key) is False
    with tenant_session(tenants["b"], app_engine) as s:
        assert s.execute(text("SELECT count(*) FROM jobs WHERE idempotency_key = :k"), {"k": key}).scalar() == 0


def test_worker_claims_across_tenants_but_not_business_rows(tenants, seeded, app_engine, worker_engine):
    with tenant_session(tenants["b"], app_engine) as s:
        repo.enqueue_job(s, tenants["b"], "analyze", f"analyze:{uuid4()}", seeded["b"])
    with worker_engine.begin() as conn:
        from sqlalchemy.orm import Session
        job = repo.claim_job(Session(bind=conn))
        assert job is not None
        with pytest.raises(DBAPIError):  # worker must switch into the job's tenant first
            conn.execute(text("SELECT count(*) FROM disputes"))
