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
python -m app.worker          # second terminal: background jobs + webhook routing
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

## Jobs and webhooks

```
POST /api/disputes/sync ─► jobs (QUEUED) ─► worker claims (SKIP LOCKED, 60s lease + heartbeat)
                                              ├─ ok        → SUCCEEDED (+ result)
                                              ├─ transient → QUEUED, backoff 5s·2^n (max 15 min)
                                              └─ permanent / attempts exhausted → FAILED (visible)
PayPal ─► POST /webhooks/paypal ─► verify signature ─► webhook_events (dedupe by event id)
          worker: resolve seller → merchant (paypal_connections) ─► tenant job sync_dispute
```

- `POST /api/disputes/sync` returns `202` with `job_id`; clicks within the same minute share one job.
- `GET /api/jobs/{id}` shows state, attempts, last error and result.
- The API role can only *insert* webhooks; it cannot read their payloads or the PayPal account mapping.
- Unroutable webhooks are kept with an `error`, never silently dropped.

## Evidence upload

`POST /api/disputes/{id}/evidence` (multipart: `file`, `doc_type`) accepts PDF, JPG, PNG or GIF under
10 MB (50 MB per dispute), PayPal's limits. The type is decided from the file's bytes, not its name.
PDF text is extracted with `pypdf` into numbered lines; images are stored without text (no OCR yet).
`doc_type` is chosen by the person uploading (`order_invoice`, `payment_record`, `carrier_tracking`,
`delivery_proof`, `support_message`, `other`) because the rules depend on it. Files go to private local
storage (`SAL_STORAGE_DIR`, default `apps/api/storage/`, git-ignored); duplicates are rejected; every
upload queues a fresh analysis. When a reply is sent to PayPal, original uploads are sent as-is.

## Agent (ADR-002)

`app/agent/` runs a fixed pipeline with one bounded agentic stage:
`load → gather (read-only tools, max 8 steps) → extract → ground → INR rules → snapshot → draft → verify`.
The worker runs it as job `analyze_dispute`, queued automatically when a sync changes a dispute
(one job per dispute version). Results are stored in `agent_runs`, `tool_calls`, `analyses` (append-only)
and a new `drafts` revision; `GET /api/disputes/{id}/analysis` returns them.

Planner, Extractor and Drafter are provider-neutral protocols. Deterministic baselines run today:

```
python -m app.agent.evaluate                     # development split
python -m app.agent.evaluate --split calibration
python -m app.agent.evaluate --split holdout --final
```

## Performance notes

- Policies call `(SELECT current_merchant_id())`, evaluated once per query as an InitPlan.
- Indexes lead with `merchant_id`; the dispute queue uses keyset pagination on
  `(deadline_at NULLS LAST, id)`. Verified: 20k disputes / 200 merchants → Index Only Scan, 0.3 ms.
- Partial indexes for claimable jobs and unprocessed webhooks.
- Connections set `statement_timeout=5s` and `idle_in_transaction_session_timeout=10s`.
- Sync runs in three phases (short read → network → short write); no transaction waits on PayPal.
- Sync lists summaries first and fetches details only for new or changed disputes (4 in parallel).
  A timestamp-only change (e.g. a buyer message) is stored without bumping `version`.
- Dispute upserts only bump `version` when a tracked field actually changed.

## Tests

`tests/test_rls.py` (needs Postgres) covers: tenant visibility, fail-closed without tenant, no leak across
pooled transactions, cross-tenant insert/update blocked, composite FK, append-only audit, no DELETE/DDL,
no `BYPASSRLS` roles, FORCE RLS on all tenant tables, exact money and currency checks, version bumps,
keyset pagination, job idempotency, and worker isolation. `tests/test_worker.py` covers sync
change detection, retry/backoff, permanent failures, expired leases, webhook signature/size/dedupe/routing,
and the API role's lack of access to webhook payloads. `tests/test_unit.py` runs offline.
