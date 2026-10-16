# Security and controls review: SAL Resolve

**Date:** 2026-10-15
**Type:** Proactive review before deploy. This is a pre-mortem, not an incident, so it has no severity or status updates.
**Status:** Fixes merged into the working tree; 149 backend tests pass.
**Scope:** API, worker, agent, web (`feat/frontend`, uncommitted).
**Prompt:** Vibe-coded systems tend to ship with injection holes, weak access control and scattered configuration. Check SAL for each, with evidence.

## Summary

SAL had a strong core:
- Row-level security with fail-closed tenancy, one database role per runtime, and append-only audit.
- Parameterized SQL, PayPal writes only after human approval, grounding of every fact, and webhook signature checks.

The gaps sat at the edges:
- an API with no caller check
- configuration read ad hoc in five modules
- model-written text going to PayPal without an output filter
- no request-size guard
- no browser security headers
- unpinned dependencies

All were fixed and tested. The two remaining items need a deployment decision.

## Findings

| # | Area | Finding (with evidence) | Risk | Fix | Test |
|---|---|---|---|---|---|
| S1 | **Access control** | No caller authentication. Any client that reaches the API can approve and send evidence to PayPal. It is safe today only because uvicorn binds to 127.0.0.1. | High once deployed | `SAL_INTERNAL_TOKEN`: the API answers only the web server, using a constant-time compare. `/api/health` and the signed webhook stay open. **Required when `SAL_ENV=prod`.** | `test_api_answers_only_the_web_server_when_a_token_is_set` |
| S2 | **Output injection** | Model-written reply sentences go to PayPal's `notes` verbatim. They were checked for facts and prohibited claims, but not for links, e-mail addresses, markup, control characters or injected instructions. | Medium | `safe_claim_text()`: rejects URLs, e-mails, HTML, control characters, instruction-like text (`INJECTION_RE`) and anything over 300 characters | `test_unsafe_reply_text_never_reaches_paypal` (6 cases) |
| S3 | **Configuration** | Settings were read with `os.environ` in `llm.py`, `runner.py`, `paypal.py` and `main.py`. A typo (e.g. `SAL_LLM_TEMPERATURE=warm`) only failed inside a job, hours later. | Medium | One `Settings` with typed parsing and `require_valid()` at API and worker start, which lists every problem at once. Prod rules: an internal token is required and dev database passwords are refused. Secrets are excluded from `repr` and logs. | `test_bad_configuration_is_reported_all_at_once`, `test_secrets_never_appear_in_repr_or_summary` |
| S4 | **Input limits** | The upload handler reads at most 10 MB, but the multipart body was spooled before that check. Nothing limited JSON bodies. | Medium (memory and disk DoS) | Middleware refuses bodies over the declared limit before any parsing: 11 MB on `/evidence`, 256 KB elsewhere. | `test_oversized_bodies_are_refused_before_parsing` |
| S5 | **Error handling** | An unexpected exception produced a plain-text 500 and no correlation. | Low (information leak, hard to debug) | JSON 500 with an `error_id`; the stack trace is logged with the same id and never sent to the caller | `test_unexpected_errors_return_an_id_not_internals` |
| S6 | **Browser** | No security headers, so the page could be framed (clickjacking of Approve and Send) and MIME sniffing was allowed. | Low–medium | CSP (`default-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`, etc.), `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, and no `X-Powered-By`. Verified live: no console errors, and buttons still work. | Manual check in the browser |
| S7 | **Supply chain** | `requirements.txt` only had lower bounds (`>=`), so every install could pull different versions. | Low–medium | `requirements.lock` with exact, tested versions, used by `.\sal setup` and the README. `pip check` is clean. | `pip install -r requirements.lock`, `pip check` |
| S8 | API docs in prod | `/docs` and `/openapi.json` were always public. | Low | Disabled when `SAL_ENV=prod` | — |

## Checked and found sound (evidence, no change needed)

- **SQL injection.** All queries use bound parameters. The f-strings in `repositories.py` interpolate only the code constant `DISPUTE_COLUMNS`.
- **Prompt injection.** Documents reach the model as JSON data. The model has no tools and no write access. Every fact must quote its line (grounding), instruction-like text is flagged (`INJECTION_RE`), and now the output is filtered too (S2).
- **Path traversal.** `read_file()` resolves under the storage root only, object keys are UUID-based, and display names are sanitized.
- **Upload type.** Detected from the bytes, not the name. PDFs are limited to 50 pages and 400 lines, and encrypted PDFs are refused.
- **Tenancy.** The merchant comes from the server, never from request input. RLS is forced on every business table. Another tenant's data looks exactly like data that does not exist (404).
- **Double sends.** Atomic claim plus reconciliation from PayPal's record (ADR-003), and approval bound to the exact documents.
- **Webhook.** Size limit, signature verification and event-id deduplication.
- **XSS.** React escapes all text; there is no `dangerouslySetInnerHTML`.
- **CSRF.** Next.js server actions check the request origin, and the API is not browser-reachable.
- **Secrets.** `.env` is git-ignored. A scan of tracked files found no keys; one pattern hit was an npm integrity hash.

## Why these gaps happen (5 whys, blameless)

1. **Why could anyone call the API?** Auth was deferred ("demo identity until the auth provider is chosen").
2. **Why was that acceptable?** Locally the API only listens on 127.0.0.1, so the gap was invisible.
3. **Why wasn't it caught earlier?** There was no deploy checklist, and tests ran in-process, where everyone is trusted.
4. **Why did configuration end up scattered?** Each feature (LLM, PayPal, webhook) added its own `os.environ` read as it was built.
5. **Root cause.** Security controls lived in the *core* (database, grounding) but had no *perimeter* owner: request edges, configuration and outputs.

## Action items

| Action | Priority | Status |
|---|---|---|
| S1–S8 fixes with tests | P0 | Done (149 tests) |
| Set `SAL_ENV=prod`, a 32+ char `SAL_INTERNAL_TOKEN` on web and API, and non-dev database passwords at deploy | P0 | At deploy |
| Hosted demo is public: decide on basic auth, or accept sandbox-only abuse risk (anyone could press Send on sandbox data) | P1 | **Owner decision** |
| Rate limiting on mutating endpoints (per-IP), if the demo is public | P1 | With the deploy decision |
| Retention cleanup (jobs, webhook_events, tool_calls) | P2 | Open (design §12) |
| Re-run this review before each release; add `pip-audit` / `npm audit` to CI | P2 | Open |
