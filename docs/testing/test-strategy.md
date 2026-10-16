# SAL Resolve: test strategy

**Date:** 2026-10-16
**Scope:** `apps/api`, `apps/web` and the agent evaluation, on branch `feat/frontend`.

## Current state

- **Backend:** 114 test functions across 13 files, 149 test cases in total (parametrized).
- **Web:** no tests.
- **CI:** none. Tests run only on a developer machine (`.\sal test`) and need Docker.
- **Coverage measurement:** none (`pytest-cov` is not installed).

| Layer | What exists | Assessment |
|---|---|---|
| Unit: agent rules (`validation`, `assess`, grounding, claim checks) | Strong (`test_agent`, `test_assess`, `test_grounding_formats`) | Good. These are example-based only: no fuzzing of the text filters. |
| Integration with the DB: RLS and tenancy | Strong (16 tests in `test_rls`) | Good. This is the best-protected area. |
| Integration with the DB: worker and queue | Good (`test_worker`, `test_ops`) | Leases, retries and heartbeat are covered. |
| Submission safety (ADR-003) | Good (17 tests) | All tests are sequential. The double-send guard is never exercised by two callers at the same time. |
| HTTP edges and security | Good (`test_security`, `test_api`) | — |
| PayPal client (`paypal.py`) | Only `to_internal` and `redact` | Token expiry and refresh, pagination and the HTTP error mapping are untested. |
| Contract (recorded sandbox payloads) | 1 dispute payload | The Transaction Search payload is recorded but only used by `test_paypal_evidence` fakes. |
| Agent quality (golden eval) | `test_baseline_floor_on_development_split`, plus a manual `.\sal eval` | The LLM path has no regression gate. |
| Web (`lib/plain.ts`, components, flows) | None | **Largest gap.** The plain-language layer decides what a merchant reads, and nothing checks it. |
| End-to-end (browser → API → worker → fake PayPal) | Manual, in the browser | It works, but is repeated by hand before each demo. |

## Principles for this codebase

1. **Test by risk, not by line count.** The expensive failures are:
   - evidence sent to PayPal twice, or without approval;
   - one tenant seeing another tenant's data;
   - a claim the documents don't prove;
   - the merchant being told "ready" when the case isn't.

   These areas get the strictest targets.
2. **The real database in integration tests stays.** RLS cannot be tested with mocks. Keep `sal_test` and the reset-only-`*_test` guard.
3. **PayPal is never called from tests.** Use the recorded payloads in `contracts/paypal/`, `httpx.MockTransport` for the client, and fakes for the worker. Live sandbox checks stay manual.
4. **The LLM is never called in the normal suite.** Tests run on the baseline roles. Model quality is measured by `evaluate.py` as a separate, opt-in gate.
5. **Test names state the rule in plain words,** as the existing names do (`test_document_added_after_approval_is_never_sent`).

## Coverage targets

These are branch coverage, measured with `pytest --cov=app --cov-branch`.

| Area | Target | Why |
|---|---|---|
| `submission.py`, `agent/assess.py`, `agent/validation.py` | ≥ 95% | Money, PayPal writes and what we tell the merchant |
| `repositories.py`, `worker.py`, `sync.py`, `paypal_evidence.py` | ≥ 85% | Data integrity and the job queue |
| `main.py`, `config.py`, `paypal.py` | ≥ 80% | Request edges and adapters |
| `seed_demo.py`, `evidence_pdf.py` rendering details | No target | Demo scripts and layout code |
| `apps/web/lib/plain.ts` | 100% of exported functions | Pure functions; every readiness and status maps to text |
| Whole backend | ≥ 80% line coverage | Reported, not enforced, until CI runs |

## Gaps and the tests that close them

Ordered by priority.

### P0: before the submission (Nov 10)

**G1. CI on every push.** Use GitHub Actions with a `postgres:16` service. The steps are:
1. Run `db/init/01_test_db.sql`.
2. `pip install -r requirements.lock`.
3. `pytest -q --cov`.
4. In `apps/web`: `npm ci`, `npm run lint`, `npx tsc --noEmit`, `npm test`, `npm run build`.

Judges will see the repo, and a green check shows that the 149 tests actually run. The job costs nothing, because no PayPal or OpenAI secrets are needed.

**G2. Web unit tests for `lib/plain.ts`** (Vitest, no browser). Example cases:
- `readiness("READY" | "NEEDS_DOCUMENTS" | "NEEDS_CHECK" | "WEAK")` returns a distinct title and tone for each. An unknown value falls back without throwing.
- `nextStep(...)` never suggests sending when readiness is not READY.
- `docName("paypal_transaction", "PAYPAL_API")` shows the "From PayPal" label. An uploaded receipt does not.
- `propositionTitle` covers every proposition id that `assess.py` emits. This is a **cross-language check**: export the id list from Python into a JSON fixture and assert that both sides agree, so a renamed proposition fails a test instead of showing raw ids to the merchant.

**G3. Concurrent double submit.** In a `db` test, two threads call `POST /api/drafts/{id}/submit` on the same approved draft. The fake PayPal records its calls.
- Expect exactly one `provide_evidence` call.
- One response is 200 and the other is 409 (or the same result).
- The audit log has one send.

This is the most important property in ADR-003, and today it is tested only sequentially.

**G4. PayPal client unit tests** with `httpx.MockTransport`:
- The token is fetched once, reused, and refreshed 60 s before expiry.
- `list_summaries` follows `next` links and stops at `max_pages`.
- `transaction()` returns `None` on an empty result, and the 403 (feature not enabled) surfaces as a permanent error.
- `verify_webhook` returns False on `FAILURE` and on HTTP errors, and never raises into the webhook handler.

### P1: hardening, the same week

**G5. Property-based tests for the text filters** with `hypothesis`, on `safe_claim_text`, `value_in_line`, `amounts_in` and `dates_in`:
- `safe_claim_text` never returns text containing `http`, `@`, `<`, or a control character, whatever it is given.
- Feeding `amounts_in` text it produced itself (`f"{x:.2f} USD"`) finds `x` exactly. No float drift, because the values are `Decimal`.
- `value_in_line(v, line)` stays True when `line` gets extra whitespace or a different case.

The filters are the injection defence (security review S2), and example tests only cover the attacks we thought of.

**G6. Contract tests from every recorded payload.** Each file in `contracts/paypal/*.json` is parsed by the adapter that consumes it:
- disputes → `to_internal`;
- transaction search → `render_record`.

Assert the required fields and that no personal data survives `redact`. When PayPal changes a field, re-recording the file then fails a test instead of a demo.

**G7. Migration round trip.** Upgrade to head, downgrade one step, then upgrade again, for each revision. This catches a broken `downgrade()` before it is needed in production. The session fixture only does a full downgrade to base.

**G8. One end-to-end happy path** with Playwright. It runs against `next start`, the API and the worker, with fake PayPal (`SAL_PAYPAL_FAKE=1` or a stub server):
1. Open the queue and open a dispute.
2. Upload a courier PDF.
3. Wait for the analysis.
4. See "What your documents prove".
5. Tick the checkbox, approve, and send.
6. See SUBMITTED.

This replaces the manual pre-demo check and catches CSP and server-action breakage that unit tests can't. Keep it to one or two flows, because they are slow.

### P2: after the submission

- **G9. LLM regression gate.** Run `evaluate.py --split real_format --roles llm` manually or nightly, with the model key as a CI secret. It fails if fact recall drops below 0.95, readiness accuracy below 1.00, or any unsupported claim appears. Today's results are 0.96, 1.00 and 0, so the gate has a margin. The cost is cents per run with gpt-5-nano.
- **G10. Component tests** for `DraftActions` (the states SUBMITTING, NEEDS_MANUAL_CHECK and SUBMITTED, and Approve disabled until the checkbox is ticked) and `UploadEvidence` (size and type errors are shown).
- **G11. Smoke test after deploy.** Check that `/api/health` is `ok`, that `/` returns 200 with the CSP header, and that an API call without the internal token gets 401.
- **G12. Load test.** Not needed for a single-merchant demo. Revisit when there is more than one real tenant.

## Tests to write first for pending features

These come from the Ka Ocid case: proposals 1, 2, 3 and 5. They are written test-first once the features are approved.

| Scenario | Expected |
|---|---|
| Courier record says "in transit", no delivered scan | Readiness is not READY. The suggested step is "answer with tracking, wait for delivery", not "send evidence". |
| Tracking last updated 10 days ago | A staleness flag with the date, in plain words |
| Dispute stage is INQUIRY, 3 days left | The urgency shown is based on PayPal's deadline, not our guess |
| Delivered scan, but the city doesn't match the shipping address | `delivered` is NEEDS_CHECK, never proven |
| Amount ≥ USD 750 with no signature | Flagged under Seller Protection's signature rule |
| Customs hold at the destination | Shown as "held at customs, waiting for the buyer", stronger than in transit, but not delivered |

## What we deliberately don't test

- Next.js and FastAPI framework behaviour, Tailwind styles, and `seed_demo.py` output.
- Live PayPal sandbox calls in the automated suite. They are slow, flaky (we've seen 520s) and need secrets. They stay a manual check, recorded in `contracts/paypal/`.
- Visual regression of the glass UI. It costs more to maintain than it is worth for a hackathon.

## Running

```
.\sal test                         # backend, needs Docker
pytest -q --cov=app --cov-branch   # with coverage (after adding pytest-cov to requirements.lock)
cd apps/web; npm test              # after G2 adds Vitest
```
