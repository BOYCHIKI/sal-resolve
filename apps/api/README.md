# SAL API (FastAPI + PostgreSQL)

Backend for SAL Resolve. Tenant isolation is enforced by PostgreSQL Row-Level Security, not only by
application code (SAL v1.1 §6).

## Run locally

From the repo root:

```
docker compose up -d --wait
cd apps/api
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
python -m app.seed            # prints a merchant id → SAL_DEMO_MERCHANT_ID in .env
uvicorn app.main:app --reload
pytest -q                     # DB tests skip automatically when Postgres is not running
```

## Query permission model

| Role | Used by | Can | Cannot |
|---|---|---|---|
| `sal_migrator` | Alembic | DDL; owns tables | bypass RLS (tables use `FORCE ROW LEVEL SECURITY`) |
| `sal_app` | API requests | read/insert/update own tenant's rows; enqueue jobs; ingest webhooks | DELETE anything; UPDATE/DELETE audit or approvals; DDL; `row_security = off` |
| `sal_worker` | background worker | claim any job (`SKIP LOCKED`); mark webhooks processed | read business rows without switching into the job's tenant |

No runtime role is superuser or `BYPASSRLS`.

**Tenant context.** `app.db.tenant_session(merchant_id)` opens a transaction and runs
`set_config('app.merchant_id', :mid, true)` as its first statement. The setting is transaction-local,
so a pooled connection never carries a tenant into the next request. Without it, every tenant table
query errors (fail closed). The merchant id comes from the server-side identity
(`current_merchant()`), never from headers or query parameters.

**Defense in depth.**
1. RLS `USING` + `WITH CHECK` on every tenant table.
2. Composite foreign keys `(dispute_id, merchant_id)` — a row cannot point at another tenant's parent.
3. Grants: no `DELETE`; `audit_logs` and `approvals` are insert-only, plus an append-only trigger on audit.
4. Hand-written, parameterized SQL only; no text-to-SQL.

## Performance notes

- Policies call `(SELECT current_merchant_id())`, evaluated once per query as an InitPlan.
- Indexes lead with `merchant_id`; the dispute queue uses keyset pagination on
  `(deadline_at NULLS LAST, id)`. Verified: 20k disputes / 200 merchants → Index Only Scan, 0.3 ms.
- Partial indexes for claimable jobs and unprocessed webhooks.
- Connections set `statement_timeout=5s` and `idle_in_transaction_session_timeout=10s`.
- PayPal calls in `/api/disputes/sync` run before the DB transaction opens, so no transaction waits on the network.
- Dispute upserts only bump `version` when a tracked field actually changed.

## Tests

`tests/test_rls.py` (needs Postgres) covers: tenant visibility, fail-closed without tenant, no leak across
pooled transactions, cross-tenant insert/update blocked, composite FK, append-only audit, no DELETE/DDL,
no `BYPASSRLS` roles, FORCE RLS on all tenant tables, exact money and currency checks, version bumps,
keyset pagination, job idempotency, and worker isolation. `tests/test_unit.py` runs offline.
