# ADR-003: Closing the remaining backend gaps

**Status:** Accepted, implemented 2026-10-14 (D1–D4); D5 deferred
**Date:** 2026-10-14
**Scope:** Problems the 2026-10-14 sandbox end-to-end run left open (ADR-001), before the 10 Nov internal target.
**Constraint:** No new infrastructure. Use Postgres, the existing job queue and the existing PayPal client only.

## 1. Requirements

| # | Requirement | Why it matters |
|---|---|---|
| R1 | PayPal never receives documents the operator did not approve | Human approval is SAL's core promise (v1.0 §8) |
| R2 | A send that crashed or timed out ends up `SUBMITTED` or `SUBMIT_FAILED`, never stuck | Today it stays `SUBMITTING` forever, and the operator cannot retry |
| R3 | SAL never re-sends to PayPal without a person pressing Send | Sending is irreversible on PayPal's side |
| R4 | Running the tests leaves the demo data alone | Today `pytest` wipes the dev database |
| R5 | Operators upload documents from the case page | Today uploads need `curl` |
| R6 | Case status stays reasonably fresh without the operator pressing a button | This one is optional for the demo |

Load assumptions for the hackathon: fewer than 10 merchants and fewer than 100 open disputes each. One worker. PayPal is called by people's clicks, not on a schedule.

## 2. Findings from reading the code

**G1: uploading after approval sends unapproved documents (R1). This is a correctness bug.**
- `runner.run_analysis` supersedes only drafts in `DRAFT` status. A draft that is already `APPROVED` keeps that status after a new upload triggers re-analysis.
- `submission.submit` then sends every evidence row the dispute has *now*, including the new file.
- An image upload has no text, so it does not even change the snapshot hash.

**G2: `SUBMITTING` has no exit (R2).**
- The worker can crash, or the API process can die, between the claim (`APPROVED → SUBMITTING`) and the outcome write. The draft then stays `SUBMITTING`.
- `submit` only accepts `APPROVED` or `SUBMIT_FAILED`, so the operator cannot retry.
- A network timeout is recorded as `SUBMIT_FAILED`, even though PayPal may have accepted the request.

**G3: tests share the dev database (R4).** `conftest.migrated_db` downgrades `sal` to base.

**G4: no upload in the UI (R5).** The backend is ready: `POST /api/disputes/{id}/evidence` validates type, size, duplicates and tenant.

## 3. Design

### D1: Bind approval to the exact documents (fixes G1)

```
approve ──► approvals.evidence_hash = sha256(sorted evidence checksums)
upload  ──► re-analysis ──► supersedes DRAFT *and* APPROVED drafts, dispute → NEEDS_REVIEW
submit  ──► recompute evidence_hash; different → 409 EVIDENCE_CHANGED, nothing sent
```

- **Runner:** change `status = 'DRAFT'` to `status IN ('DRAFT', 'APPROVED')` in the supersede update. The dispute already returns to `NEEDS_REVIEW`.
- **Submit:** inside the claim transaction, compute the hash of the current evidence and compare it with the approval's hash. This covers the race where a file is uploaded after approval but before the re-analysis job has run.
- **Migration 0005:** `ALTER TABLE approvals ADD COLUMN evidence_hash text`. The column is nullable so that approvals created before this change stay readable. Submit treats `NULL` as "re-approve".

*Trade-off:* the operator must re-approve after every upload. That is intended: they approved what they saw.

### D2: Recover stuck sends by asking PayPal (fixes G2)

PayPal's own record is the source of truth. The sandbox payloads recorded on 2026-10-12 show that every accepted `provide-evidence` adds an entry to `evidences[]` with `source = SUBMITTED_BY_SELLER`, a `date`, and the documents attached to it.

```
submit claim (tx) ─ drafts.status=SUBMITTING, submit_started_at=now()
                  └ enqueue reconcile_submission  run_after = now()+2 min   (same tx)
PayPal call ───────► ok      → SUBMITTED
                  ├► 4xx     → SUBMIT_FAILED (PayPal answered: definitely not accepted)
                  └► timeout / connection lost / crash → stay SUBMITTING (unknown)

reconcile_submission (worker, tenant-scoped, normal retries):
  draft not SUBMITTING                                    → no-op (normal path finished)
  GET dispute:
    SUBMITTED_BY_SELLER entry with date ≥ submit_started_at − 5 min → SUBMITTED, enqueue sync
    provide_evidence still offered                        → SUBMIT_FAILED  (operator may press Send again)
    neither                                               → SUBMIT_FAILED, code NEEDS_MANUAL_CHECK
  every outcome writes audit  draft.submit_reconciled
```

- **Migration 0005:** `ALTER TABLE drafts ADD COLUMN submit_started_at timestamptz`.
- **Scheduling:** the job queue already has `jobs.run_after`. `enqueue_job` needs an optional `run_after` argument. No sweeper and no new process.
- **No automatic resend (R3).** The reconciler only finds out what happened. Retrying stays a human click. PayPal also rejects a second send once the state has moved (`422 ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`, spike S6), so even a mistaken retry cannot double-submit. One narrow exception (2026-10-30): a `400 EVIDENCE_TYPE_IS_NOT_ALLOWED` means nothing arrived, so the same approved notes and documents go once more as `OTHER`, the fallback PayPal's dev team recommended. Timeouts and 5xx are never retried.
- **Error classification:** an `httpx.HTTPStatusError` carrying a 4xx means PayPal definitely did not accept the request. Everything else, including timeouts, connection errors and 5xx, counts as unknown.
- **UI (`lib/plain.ts`):**
  - `SUBMITTING` → "Sending to PayPal… checking"
  - `NEEDS_MANUAL_CHECK` → "Check this case in PayPal before sending again"

*Alternative rejected:* an idempotency key on `provide-evidence`. PayPal-Request-Id is not documented for this endpoint, and we cannot verify it in sandbox before the deadline.

*Alternative rejected:* a cron sweeper over all `SUBMITTING` drafts. It needs cross-tenant reads, which RLS deliberately prevents. A per-draft job stays tenant-scoped.

### D3: Separate test database (fixes G3)

```
Postgres container
├── sal        dev + demo data   (.\sal start, seed_demo)
└── sal_test   pytest only       (downgrade/upgrade every session)
```

- **`db/init/01_test_db.sql`:** creates `sal_test` with the same owner, schema grants and pgcrypto. For volumes that already exist, `.\sal setup` runs the script idempotently through `docker compose exec`.
- **`conftest.py`:** before any `app` import, rewrite the three `SAL_*_DATABASE_URL` variables from `/sal` to `/sal_test`.
- **Guard:** `migrated_db` refuses to run unless the database name ends in `_test`. A misconfigured `.env` then fails loudly instead of wiping data.
- **`.\sal test`:** no longer re-seeds.

### D4: Upload on the case page (fixes G4)

```
browser ─(FormData, 1 file)─► Next Server Action ─(multipart, server-side)─► API /evidence
        ◄─ plain-language result ─┘                                        └─ queue analysis
browser polls router.refresh() every 3 s until the analysis revision changes (max 60 s)
```

- **Component:** `components/UploadEvidence.tsx` (client) contains a document-type select with the plain names from `lib/plain.ts` and a multi-file input. Files are sent **one per action call**, in sequence, so each stays under the limit and each gets its own ✓ or error.
- **Size limit:** `next.config.ts` sets `serverActions.bodySizeLimit: "11mb"`. The default of 1 MB would reject most PDFs. The API remains the real limit (10 MB per file, 50 MB per case).
- **Visibility:** the upload area is hidden when the case is `SUBMITTED`, or when PayPal no longer offers `provide_evidence`. There is nothing to attach to in those states.
- **Errors:** error codes map to sentences:
  - `UNSUPPORTED_TYPE` → "Only PDF, JPG, PNG or GIF"
  - `DUPLICATE_FILE` → "Already attached"
  - `FILE_TOO_LARGE` / `CASE_TOO_LARGE` → size message
- **The API base URL stays server-side,** as it is today.

### D5: Freshness (R6). Deferred.

- `/webhooks/paypal` with signature verification and routing already exists and is tested. It only needs a public URL, which is a deploy concern.
- For the local demo, the **Check PayPal** button plus the post-submit sync (already in place) is enough.
- A scheduled poll would call PayPal every N minutes for every merchant, and would need a cross-tenant scheduler for little demo value.
- **Revisit at deploy:** register the webhook. Add a poll only if webhooks prove unreliable.

## 4. Order of work and size

| Step | Change | Effort | Tests to add |
|---|---|---|---|
| 1 | D3 test DB (do first so the rest is tested without wiping demo data) | S | guard refuses `sal`; dev data survives a test run |
| 2 | D1 approval bound to evidence (bug) | S | upload after approve → submit 409, nothing sent; re-analysis supersedes APPROVED |
| 3 | D2 reconcile stuck sends | M | timeout → stays SUBMITTING; reconcile with seller evidence → SUBMITTED; with action offered → SUBMIT_FAILED; neither → NEEDS_MANUAL_CHECK; no PayPal write in any reconcile path |
| 4 | D4 upload button | M | manual check in the browser with real PDFs and an image (no UI test framework added) |

All four use one migration (`0005`) and no new services.

## 5. Consequences and what to revisit

**Easier**
- Approval means exactly what the operator saw.
- A crash during a send heals itself within minutes.
- Tests can run at any time.

**Harder**
- One more job kind.
- Approvals need re-doing after uploads.
- `SUBMITTING` now legitimately lasts up to about 2 minutes after a timeout.

**Revisit when**
- **Several workers or merchants with many disputes:** keep reconciliation per draft. It scales with sends, not with disputes.
- **Production PayPal:** confirm that `evidences[].date` uses the same clock as our timestamps. The 5-minute window absorbs skew. Narrow it if live data allows.
- **Object storage (S3) at deploy:** the evidence hash uses DB checksums, so it does not change.

## 6. Results (2026-10-14)

- **Tests:** 87 backend tests pass on `sal_test`. Demo data in `sal` is untouched by a test run.
- **Reconciliation, offline:** checked against the responses PayPal Sandbox recorded on 2026-10-12, from before and after spike S6 sent 5 documents. The verdicts are `NOT_RECEIVED` before the send and `SUBMITTED` after it. A send that starts after the last seller evidence gets `NEEDS_MANUAL_CHECK`.
- **Reconciliation, live and read-only:** `decide()` on dispute `PP-R-RVX-10191107`.
  - It recognised all three seller-evidence entries PayPal holds as received, including the end-to-end send at 2026-10-14T07:36:58Z.
  - A hypothetical new send gets `NEEDS_MANUAL_CHECK`, because the dispute is `UNDER_REVIEW` and no longer offers `provide_evidence`.
- **Upload in the browser:**
  - On practice case SAL-INR-011, a delivery-receipt PDF was added. Missing documents went from 2 to 1 after the re-analysis, which the page picked up by itself.
  - An executable renamed `.pdf` was refused with "Only PDF, JPG, PNG or GIF files can be added."
  - On the sandbox dispute (`UNDER_REVIEW`), the upload area is hidden.
- **Observed:** the sandbox dispute now also offers `adjudicate`, so spike S8 can be run.
