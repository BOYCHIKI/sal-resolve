# SAL v2: Evidence Intelligence Copilot (system design)

**Status:** Proposed. Nothing is built yet; the positioning decision is pending.
**Date:** 2026-10-15
**Builds on:** ADR-001 (sandbox), ADR-002 (agent pipeline), ADR-003 (submission safety), ADR-004 (OpenAI).
**Deadline:** submit by 12 Nov 2026, 12:00 PT. Internal target is 10 Nov.

## 1. Why v2

SAL already does more than write text. It grounds every fact to a line, flags missing and conflicting
evidence, ignores hidden instructions, and only sends after a person approves. What it does not do yet
is **say what the evidence proves**. The case page still opens on the reply.

v2 makes the assessment the product and the reply its output:

> SAL reads your documents, shows what they prove and what's missing, and drafts a reply only from
> verified facts. You decide.

## 2. Requirements

### Functional

| # | Requirement |
|---|---|
| F1 | For each dispute, show the **propositions** the evidence must prove (Item Not Received), each one proven, missing or contradicted, and each linked to its source line. |
| F2 | Show a **readiness** status and **one next action**. Never predict win or loss. |
| F3 | **Payment proof comes from PayPal.** Fetch the disputed transaction from PayPal and store it as evidence with PayPal as its source. A bank or e-wallet receipt never proves payment. |
| F4 | The drafter states only **proven** propositions. Every sentence cites a proposition and its facts. |
| F5 | Two different values for one field become a **contradiction**, never a silent pick (review #1). |
| F6 | Judges can open a **hosted demo** or run it locally on any operating system. |

### Non-functional

| | Target | Notes |
|---|---|---|
| Correctness | 0 unsupported claims; 1.00 conflict recall on golden and real-format data | Same gate as ADR-004, plus readiness accuracy |
| Latency | Analysis under 60 s in the background; page loads under 1 s | The LLM takes 20–45 s; the UI already shows progress |
| Cost | Under $10 for OpenAI and about $25/month for hosting until judging ends (15 Dec) | Hosting prices are estimates; check before buying |
| Privacy | No real customer data in git or in the hosted demo | The demo uses sandbox and synthetic data only |
| Load | Demo scale: 1–10 merchants, under 100 open disputes each | Nothing here needs horizontal scaling |

### Constraints

- One developer. About 26 days.
- Keep the current stack: FastAPI, Postgres with row-level security, a Postgres job queue, Next.js.
- The PayPal adapter stays **sandbox-only**.
- No over-engineering: no new services, no queue broker.

## 3. High-level design

```
                         ┌──────────────────────── Render (or local docker) ─────────────────────────┐
 Operator ──HTTPS──► Web (Next.js, server-side calls only)                                            │
                         │                                                                            │
                         ▼                                                                            │
                     API (FastAPI) ── private disk: uploaded evidence files (API only)                │
                         │   ▲                                                                        │
            webhook ─────┘   │ RLS (sal_app)                                                          │
                         ▼   │                                                                        │
                     Postgres: disputes · evidence · analyses(+assessment) · drafts · approvals · jobs│
                         ▲   │ RLS (sal_worker), SKIP LOCKED                                          │
                         │   ▼                                                                        │
                     Worker: sync · paypal_evidence (new) · analyze · reconcile                       │
                         │                                                                            │
                         └───────────────────────────────────────────────────────────────────────────┘
                         │ GET only                           │ provide-evidence (API only, after approval)
                         ▼                                    ▼
             PayPal Sandbox: Disputes · Transaction Search (new) · Tracking (new, optional)
                         │
                     OpenAI (extract + draft; optional, falls back to rules)
```

### Pipeline (changes in bold)

```
load → gather → extract (rules ∪ LLM) → ground → rules → **ASSESS** → snapshot → draft(**proven only**) → verify → persist
```

## 4. Deep dive

### 4.1 PayPal-native evidence (F3)

**Job `paypal_evidence`** is enqueued by sync whenever a dispute is new or its transaction changed. It runs these steps:

1. Read `disputed_transactions[0].seller_transaction_id` from the stored dispute.
2. Call `GET /v1/reporting/transactions?transaction_id=…`, with a window of ±15 days around the dispute's transaction time, because the API requires a date range.
3. Render the result as a **"PayPal transaction record"** document with numbered lines: transaction ID, status, gross amount and currency, time, invoice ID, items and shipping address. Address and names are kept out of the lines.
4. Insert it as evidence with `origin = 'PAYPAL_API'`. Its checksum is computed over the rendered lines, so it is deduplicated by checksum like any upload.
5. If PayPal has tracking for the transaction, render a **"PayPal tracking record"** the same way (optional; see open question Q2).

Then the existing analysis runs, with no new logic. Grounding treats these lines like any other document.
The UI badges these documents as **"From PayPal"**.

**Payment rule:** "Payment proven" requires a `payment_record` whose `origin = 'PAYPAL_API'` and whose
amount and currency equal the dispute's. An uploaded bank receipt is shown, but it is labelled
**"Not a PayPal record"** and proves nothing.

**Failure handling:**
- 403 or permission missing: the job ends with `PermanentError` and a visible note: "Transaction Search not enabled for this app".
- Transaction not found: retry once after 3 hours, since PayPal search data can lag. After that the payment proposition stays `missing` with the reason shown.

### 4.2 ASSESS stage (F1, F2, F5)

`assess(facts, findings, documents, dispute) -> Assessment` is deterministic code next to `apply_inr_rules`. It has no LLM.

| Proposition (INR) | proven when | contradicted when | missing when |
|---|---|---|---|
| `payment_matches` | a PayPal record's amount and currency equal the dispute's | they differ | there is no PayPal record |
| `shipped` | `tracking_id` plus a ship date or carrier event | — | no tracking |
| `delivered` | `carrier_status = DELIVERED` or a delivery proof with a date | — | neither |
| `delivery_date_consistent` | carrier date equals proof date | they differ | only one date exists |
| `buyer_messages_clean` | no instruction-like text | injection flagged | — (not applicable) |

There is also one general rule (F5). If a field has **more than one distinct supported value**, every
value becomes `conflicted` and a `field_value_conflict` finding is raised. This closes review #1.

**Readiness** is evaluated in this order:

1. **CONTRADICTED** when any proposition is contradicted. Next action: "Check {field} first".
2. **NEEDS_DOCUMENTS** when `shipped` or `delivered` is missing. Next action: "Add {doc}".
3. **WEAK** when `shipped` is missing **and** no courier document exists. Next action: "You may not be able to prove shipping; consider refunding in PayPal". This is advice only; SAL has no refund action.
4. **READY** otherwise. Next action: "Read and approve the reply".

The `Assessment` holds `propositions[]` (each with id, status, fact refs and reason), `readiness` and `next_action`.
It is stored in `analyses.assessment`, and the snapshot hash includes it, so an approval binds to the
assessment the operator saw.

### 4.3 Drafting from propositions (F4)

- The drafter receives only the facts behind **proven** propositions. This extends `CLAIM_FIELDS`.
- Each claim lists `proposition` and `fact_fields`.
- `verify_claims` additionally rejects a claim whose proposition is not proven.
- When readiness is not READY, a reply is still drafted, but Approve stays disabled until the operator ticks
  "I've checked the open items". The existing checkbox gets a stricter label.

### 4.4 Data model (migration 0006)

```sql
ALTER TABLE evidence ADD COLUMN origin text NOT NULL DEFAULT 'UPLOAD'
  CHECK (origin IN ('UPLOAD', 'PAYPAL_API', 'SEED'));
ALTER TABLE evidence ALTER COLUMN object_key DROP NOT NULL;  -- PAYPAL_API documents have no file
ALTER TABLE analyses ADD COLUMN assessment jsonb;            -- NULL for analyses made before v2
```

Submission renders `PAYPAL_API` documents to PDF, as it already does for seeded ones. The table grants stay unchanged.

### 4.5 API

| Endpoint | Change |
|---|---|
| `GET /api/disputes` | Each item gains `readiness`, and the list can be sorted by it (`?sort=readiness`), with documents-needed cases first |
| `GET /api/disputes/{id}/analysis` | Gains `assessment`; each evidence item gains `origin` |
| `POST /api/disputes/{id}/refresh-paypal-evidence` | Optional manual re-fetch; returns 202 with a job id |

Existing endpoints and error codes are unchanged.

### 4.6 Web

The case page is reordered:

1. **"What your documents prove"**: five rows with ✓, ✗ or ⚠ and a "see line" link, plus the readiness badge and the next action.
2. Documents, with a **From PayPal** badge where it applies.
3. The reply.
4. Approve and Send.

The queue sorts by readiness. Plain-language strings go into `lib/plain.ts`.

### 4.7 Review fixes folded in

- **#2:** select the documents first, hash those same rows, compare, then send those rows.
- **#3:** `_reconcile` maps PayPal 4xx to `SUBMIT_FAILED` with note `NEEDS_MANUAL_CHECK`.
- **#4:** an amount next to a currency mark only counts for real ISO codes or symbols.
- **#5:** `decide()` needs a `SUBMITTED_BY_SELLER` entry **with documents**.

## 5. Deployment for judges (F6)

Render is the default because of the sponsor prize and because it is simple. Each item below needs a check in spike S10.

| Service | Render type | Notes |
|---|---|---|
| web | Web Service (Node) | `SAL_API_URL` uses Render's private network |
| api | Web Service (Python) + **persistent disk** (1 GB) | Only the API touches files: upload and submit. A Render disk attaches to one service, which fits. |
| worker | Background Worker | Needs a paid instance; free instances sleep |
| db | Render Postgres | **Risk:** SAL's security model needs extra roles (`sal_app`, `sal_worker`) with FORCE RLS. If Render's database user cannot `CREATE ROLE`, use Neon or Supabase Postgres instead, since both allow roles. |
| webhook | `POST /webhooks/paypal` on the public API URL | Register it in the sandbox app; this finally activates live status updates |

- **Secrets:** go in Render environment groups only: PayPal sandbox client and secret, OpenAI key, `PAYPAL_WEBHOOK_ID`.
- **Demo data:** the hosted demo seeds synthetic cases plus whatever sandbox disputes exist.
- **No login yet:** the hosted demo has no auth and runs as one demo merchant. That is acceptable for judging, provided it uses **sandbox data only**, and the README says so.

## 6. Reliability and observability (demo-sized)

- **Job queue:** already has leases, retries, backoff and visible failures. Add a `/api/health` endpoint that reports DB reachability, the oldest queued job's age and the last worker heartbeat. The UI shows a banner when the worker is down.
- **PayPal and OpenAI outages:** sync retries; analysis falls back to rules (ADR-004); sends reconcile from PayPal's record (ADR-003).
- **Limits:** evidence is capped at 10 MB per file and 50 MB per case; LLM input is capped at 10 docs × 200 lines; OpenAI spend is capped at $10 in the dashboard.

## 7. Evaluation changes

- **Readiness accuracy.** Golden v1.0 labels map directly: missing evidence gives NEEDS_DOCUMENTS, conflicts give CONTRADICTED, neither gives READY. Real-format v1.1 is labelled the same way. The gate is readiness accuracy ≥ 0.95 on both.
- **Proposition accuracy.** Per-proposition status compared with labels derived from ground-truth facts.
- **Golden v2.0.0 (real PayPal data)** plugs in later through the same scorer, if a PayPal Business account or PayPal's samples arrive.

## 8. Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Who decides "proven" | Deterministic code | LLM judgement | Testable, explainable to judges, no hallucinated verdicts |
| Readiness, not a score | 4 states with one action | 0–100 "evidence strength" | No calibration data; a number would imply precision we don't have |
| Payment proof source | PayPal API record only | Accept any receipt | Matches the PayPal-only rule; removes the forged-receipt class of errors |
| PayPal records as evidence rows | Rendered lines plus origin | A separate "payment facts" table | Reuses grounding, UI and submission unchanged |
| Hosting | Render (+ Neon if roles are blocked) | Fly, Railway, a VPS | Sponsor prize, simplest path, background-worker support |
| Auth for the demo | None (one merchant, sandbox only) | Add login | Saves days; the risk is acceptable with sandbox data and is documented |

## 9. Plan and effort

| Step | Work | Effort | Needs a decision? |
|---|---|---|---|
| 0 | Review fixes #1–#5 + tests | 0.5 d | No |
| 1 | Migration 0006, `assess()`, propositions, readiness, F5 rule, tests, evaluation | 1 d | **Yes:** positioning |
| 2 | Spike S9: Transaction Search (and Tracking) in sandbox, then the `paypal_evidence` job | 0.5–1 d | No |
| 3 | Web: "What your documents prove", badges, queue sort | 1 d | Yes (same) |
| 4 | Spike S10 + deploy (Render, Neon if needed), register the webhook | 1 d | **Yes:** push, make the repo public, hosting cost |
| 5 | Screen-recorded demo video under 3 min, Devpost text, testing instructions | 1 d | — |

The total is about 5–6 working days, which leaves buffer before 10 Nov.

## 10. Open questions

1. ~~Is Transaction Search available to the sandbox app?~~ **Yes (spike S9, 2026-10-15)**, once "Transaction search" is ticked in the sandbox app.
   - Before ticking it, the call returned 403 NOT_AUTHORIZED (debug_id ca4ad2e7e7f10). After ticking: 200 (debug_id ca4ad501a1eb8). The token now carries `reporting/search/read`.
   - For dispute `PP-R-RVX-10191107` it returned exactly 1 match, 3 days after payment, with these fields:
     - `transaction_id` 2MK81285P20231246
     - `transaction_status` S (success)
     - amount 45.00 USD (equal to the dispute amount)
     - initiation date
     - `invoice_id` and `custom_field` = SAL case id
     - event code T0006
     - `cart_info` items
   - The response also includes `payer_info` and `shipping_info` (name, address). These are personal data and stay out of the rendered record.
2. Does PayPal record tracking for sandbox orders? **Unknown.** `GET /v1/shipping/trackers` still returns 403 (debug_id ca4ad501d8861). The token has no shipping scope, and the sandbox app shows no option for it. Until PayPal grants it (asked in the hackathon email), `shipped` and `delivered` keep coming from courier uploads.
   - Side finding: the token carries `documents/disputes/download`, so dispute attachments should be downloadable. That is useful for golden v2.0.0.
3. Can a Render Postgres user create roles? (Spike S10)
4. Should a WEAK case still allow sending? Proposal: yes, after an explicit "I understand" tick, because the merchant decides.

## 11. Revisit when

- **Real merchants use SAL.** Add auth and multi-merchant onboarding (PayPal Connect/Partner), and run zero-retention checks on OpenAI.
- **Image evidence is common.** Add OCR before extraction.
- **Other dispute reasons are added** (Not as described, Unauthorised). Propositions become per-reason rule sets; the readiness logic stays generic.
- **Volume grows.** The Postgres queue scales with more worker instances. Move files to S3-compatible storage when a second API instance is needed.

## 12. Database, cache, observability and business-logic review (2026-10-15)

### Fixed and tested (137 backend tests)

**Business logic**
- **B1, partial disputes.** A PayPal payment larger than the disputed amount (one item of two) is normal, and `payment_matches` is proven with the reason "buyer disputes X of Y". Only an amount below the dispute, or another currency, is a contradiction. This applies in both the rules and ASSESS.
- **B2, other dispute reasons.** Reasons other than Item Not Received are never judged by shipping rules: no propositions, readiness NEEDS_CHECK, and a plain note. The generic checks still run (one field/two values, amounts, currencies, hidden instructions).
- **B3, PayPal's own request.** A new proposition, `paypal_request_covered`, maps PayPal's `REQUESTED_FROM_SELLER` evidence types to propositions (e.g. PROOF_OF_FULFILLMENT needs shipped and delivered). An unknown type is flagged for the operator.
- **B4, deadlines.** These stay out of the assessment, so an approval's snapshot hash doesn't change with the clock. The case page shows a red warning when the reply is due within 3 days.

**Cache**
- **C1.** One PayPal client per worker and API process, so the OAuth token is reused until it expires. Before, each job fetched a new token.

**Database**
- **D1.** Migration 0007 adds a partial index for the "analysis already queued?" lookup made on every upload.

**Observability**
- **O1.** `GET /api/health` reports database and worker liveness from a new `worker_heartbeats` table. It needs no tenant, so it can serve as the hosting health check.
- **O2.** `GET /api/ops` reports, for the merchant: the queue by state, the oldest ready job, failures in the last 24 h with their errors, LLM fallbacks, OpenAI tokens and the last PayPal sync.
- **O3.** Structured JSON logs (`app/logs.py`) carry `job_id`, `dispute_id`, `merchant_id`, `kind`, `outcome` and `duration_ms`.
- **O4.** OpenAI input and output tokens are stored per agent run, and are recorded even when the run fell back to rules.
- **UI.** The header shows "Background work paused" when the worker heartbeat is stale, and "SAL can't reach its server" when the API is down.

### Verified live
- With no worker: health `degraded` and the banner shows.
- After starting the worker: health `ok`, the banner disappears, and a PayPal sync succeeds in 1.5 s with JSON logs.

### Still open
- **C2.** Cache LLM extraction per document hash, prompt and model.
- **D2.** Retention cleanup for jobs, webhook_events and tool_calls.
- **D3.** Backups and point-in-time recovery once hosted.
- **B5.** Digital goods.
- **B6.** Multi-transaction disputes (only the first transaction is used).
