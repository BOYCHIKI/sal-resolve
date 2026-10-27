# SAL Resolve: engineering glossary

How SAL's parts map to standard software-engineering patterns. Every **Built** row points at code that exists today. **Planned** rows are design only (see the linked ADR or design doc).

## Architecture

| Term | In SAL | Where | Status |
|---|---|---|---|
| Modular monolith | One FastAPI codebase for API and worker, split into modules (agent, submission, sync, evidence), deployed as two processes | `apps/api/app/` | Built |
| Background worker | Long-running process that claims and runs jobs outside the request path | `app/worker.py` | Built |
| Backend-for-frontend (BFF) | The browser never calls the API; Next.js server actions call it server-side | `apps/web/app/actions.ts`, `lib/api.ts` | Built |
| Adapter pattern | PayPal and LLM clients sit behind small interfaces (`EvidenceSink`, `DisputeSource`, extractor/drafter roles) so they can be swapped or faked | `app/paypal.py`, `app/sync.py`, `app/agent/llm.py` | Built |
| Dependency injection | Fakes are injected through FastAPI `dependency_overrides` and the worker `Context` | `app/main.py`, `app/worker.py`, `tests/` | Built |
| Human-in-the-loop (HITL) | No write to PayPal without a person approving the exact revision | `app/submission.py` | Built |
| MCP server (agent-to-agent) | SAL exposes tools so other AI agents can delegate to it | — | Planned |

## Data and multi-tenancy

| Term | In SAL | Where | Status |
|---|---|---|---|
| Multi-tenancy | Every business row carries `merchant_id` | `migrations/sql/0001_core_rls.sql` | Built |
| Row-Level Security (RLS), fail-closed | `FORCE ROW LEVEL SECURITY` with a tenant set per transaction; a query without a tenant errors instead of returning everything | `0001_core_rls.sql`, `app/db.py` (`set_config`) | Built |
| Principle of least privilege | Separate DB roles: `sal_migrator` (DDL), `sal_app` (API), `sal_worker` (jobs); none bypasses RLS | `db/init/00_roles.sql` | Built |
| Composite foreign keys | `(id, merchant_id)` FKs stop rows linking across tenants | `0001`, `0003` | Built |
| Append-only audit log | The API role cannot UPDATE or DELETE `audit_logs`, `approvals` or `tool_calls` | grants in `0001`, `0003` | Built |
| Optimistic concurrency control | `disputes.version`; stale revision or snapshot → HTTP 409 | `app/submission.py` (`approve`) | Built |
| Pessimistic locking | `SELECT … FOR UPDATE` during approval | `app/submission.py` | Built |
| Schema migrations | Versioned Alembic migrations with tested downgrades | `migrations/versions/0001–0008` | Built |
| Exact money arithmetic | `NUMERIC(19,4)` plus ISO currency code; never floats | `0001_core_rls.sql`, `app/agent/validation.py` | Built |
| Keyset pagination | Dispute list pages by `(deadline_at, id)`, not OFFSET | `app/repositories.py` | Built |
| Table partitioning, read replicas, sharding by tenant | Scale path for large transaction volumes | — | Planned |

## Reliability

| Term | In SAL | Where | Status |
|---|---|---|---|
| Transactional job queue | Jobs live in Postgres, claimed with `FOR UPDATE SKIP LOCKED` | `app/repositories.py` (`claim_job`) | Built |
| Leases and heartbeats | A claimed job holds a 60 s lease, renewed every 20 s; an expired lease is reclaimed | `app/worker.py` | Built |
| Idempotency keys | `ON CONFLICT (idempotency_key) DO NOTHING` for jobs; webhook event-id dedupe | `app/repositories.py` | Built |
| Concurrency test for at-most-once send | Two simultaneous Send requests: PayPal receives one, the other gets 409 | `tests/test_submission.py` | Built |
| Retry with exponential backoff | 5 s, 10 s, 20 s … capped; permanent errors fail fast | `app/repositories.py` (`fail_job`), `worker.PermanentError` | Built |
| Exactly-once side effect (at-most-once send + reconciliation) | An atomic claim (`APPROVED → SUBMITTING`) means evidence is sent at most once; an unknown outcome is reconciled from PayPal's own record, never resent | `app/submission.py` (`submit`, `reconcile`), ADR-003 | Built |
| Graceful degradation (fallback) | If the LLM fails, the deterministic baseline runs and the run is labelled | `app/agent/runner.py` | Built |
| Health check and liveness | `/api/health` checks the DB and the worker heartbeat; the UI shows a banner when the worker is down | `app/main.py`, `components/AppHeader.tsx` | Built |
| Structured logging with correlation ids | JSON logs carrying `job_id`, `dispute_id`, `merchant_id`; 500s return an `error_id` | `app/logs.py`, `app/main.py` | Built |

## Security

| Term | In SAL | Where | Status |
|---|---|---|---|
| Defense in depth | Tenancy enforced in SQL policies, queries and FKs; output checked after the model | throughout | Built |
| Prompt-injection defense | Documents are data, instruction-like text is flagged, the model has no write tools | `app/agent/validation.py` (`INJECTION_RE`), `app/agent/tools.py` | Built |
| Output validation / sanitization | Reply text is filtered for links, e-mails, markup, control characters and instructions before it reaches PayPal | `validation.safe_claim_text` | Built |
| Constant-time secret comparison | Internal token compared with `hmac.compare_digest` | `app/main.py` | Built |
| Request size limits | Bodies refused before parsing (11 MB uploads, 256 KB otherwise) | `app/main.py` (`guard`) | Built |
| Content Security Policy and security headers | CSP, `frame-ancestors 'none'`, `nosniff`, no `X-Powered-By` | `apps/web/next.config.ts` | Built |
| Webhook signature verification | PayPal `verify-webhook-signature` before any event is stored | `app/main.py`, `app/paypal.py` | Built |
| Content sniffing | Upload type detected from bytes, not the filename | `app/evidence.py` | Built |
| Fail-fast configuration | One typed `Settings`; API and worker refuse to start and list every problem at once | `app/config.py` (`require_valid`) | Built |
| Secret redaction | Secrets excluded from `repr` and logs; PII redacted from stored PayPal payloads | `app/config.py`, `app/paypal.py` (`redact`) | Built |
| Supply-chain pinning | Exact dependency versions in a lock file | `apps/api/requirements.lock` | Built |

## AI and agent

| Term | In SAL | Where | Status |
|---|---|---|---|
| Bounded agent / tool allowlist | Only the "gather" step is agentic, with read-only tools and a step budget | `app/agent/pipeline.py`, `app/agent/tools.py` | Built |
| Grounding (citation verification) | Every fact must quote a line that really contains the value | `validation.value_in_line` | Built |
| Claim verification | Every reply sentence must map to supported facts; unsupported ones are dropped | `validation.verify_claims` | Built |
| Deterministic rules engine | Missing-evidence and conflict rules in plain code, versioned (`RULE_VERSION`) | `validation.apply_inr_rules`, `app/agent/assess.py` | Built |
| Ensemble extraction | Rule extractor ∪ LLM extractor, rules kept when the model misses them | `app/agent/roles.py` (`UnionExtractor`) | Built |
| Content-addressed snapshot | Analysis and evidence hashed; approval bound to the hash | `app/submission.py` (`_evidence_hash`), pipeline snapshot | Built |
| Content-addressed cache | LLM extraction reused per document when model, prompt and lines are unchanged; re-analysis measured 16.1 s → 3.6 s and ~74% fewer tokens on a 3-document case | `app/agent/llm.py` | Built |
| Offline evaluation (golden dataset) | Labelled cases with fact recall, readiness accuracy and unsupported-claim rate | `app/agent/evaluate.py`, `data/golden/` | Built |

## Testing and delivery

| Term | In SAL | Where | Status |
|---|---|---|---|
| Integration tests against a real database | Tests run on a separate `sal_test` Postgres database, never on demo data | `tests/conftest.py` | Built |
| Contract tests | Adapters tested against recorded, redacted PayPal Sandbox responses | `contracts/paypal/`, `tests/` | Built |
| Test doubles (fakes) | Fake PayPal client and fake LLM roles | `tests/test_submission.py`, `tests/test_agent.py` | Built |
| Continuous integration | GitHub Actions: API tests on Postgres, web lint, type-check and build | `.github/workflows/ci.yml` | Written, not yet run on GitHub |
| Architecture Decision Records (ADR) | Decisions, alternatives and consequences | `docs/adr/` | Built |
