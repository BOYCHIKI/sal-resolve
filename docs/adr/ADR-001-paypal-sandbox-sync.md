# ADR-001: Golden dataset ↔ PayPal Sandbox synchronization

**Status:** Accepted (validated by sandbox spike, 2026-10-12)
**Date:** 2026-10-12
**Deciders:** SAL project owner

## Context

- Hackathon rules require PayPal developer-platform (sandbox) integration to be the core of the project; a fixture-only demo risks failing Stage 1 (SAL v1.0 §15).
- The golden dataset v1.0.0 holds labeled ground truth (facts, missing evidence, conflicts, permitted/prohibited claims). The sandbox has no ground truth, and its disputes cannot reproduce document contents.
- The dataset is PayPal-*shaped*, not PayPal-*exact*: `ITEM_NOT_RECEIVED` vs `MERCHANDISE_OR_SERVICE_NOT_RECEIVED`, only `OPEN` status, internal evidence types, no carrier enum.
- PayPal sandbox offers buyer-side `POST /v1/customer/disputes` (limited release), plus sandbox-only `require-evidence` and `adjudicate`.

## Decision

One-way seeding, never two-way sync. The golden dataset stays frozen and offline; a PayPal adapter maps provider payloads into SAL's internal model; development cases may be seeded into the sandbox and linked by `contracts/sandbox_links.csv`.

```
golden JSONL ──┐
               ├─► internal Dispute model ─► SAL pipeline ─► scorer (vs ground_truth)
PayPal API ────┘   (PayPal adapter, contract-tested)
```

## Options considered

| Option | Summary | Verdict |
|---|---|---|
| A. Full two-way sync of all 40 cases | Real but non-deterministic, slow, contaminates holdout | Rejected |
| B. Offline only (adapter + fixtures) | Deterministic, but fails the hackathon's core-integration requirement | Rejected |
| C. Hybrid: offline evaluation + sandbox seeding of development cases | Evaluation stays clean; demo runs on real sandbox | **Chosen** |

## Consequences

- Easier: deterministic evaluation; schema drift caught by contract tests on recorded payloads.
- Harder: mapping tables (reason, status, evidence type, carrier) must be maintained.
- Revisit: evidence-type mapping after spike S6; physical vs digital vs mixed orders (`line_items[].fulfillment_type`) in dataset v1.1.0.

## Guards

- Only `development` cases may reach the sandbox; calibration/holdout are refused in code.
- Base URL is hard-coded to the sandbox host; live URLs are refused.
- Sandbox writes require explicit confirmation, mirroring SAL's human-approval rule.
- Recorded payloads are redacted (tokens, emails).

## Action items

1. [x] Spike scaffold (`spikes/paypal_sandbox`) with offline tests.
2. [x] Run S1–S8 against the sandbox; record G1 outcome (G1 passed; S8 pending PayPal action, S7 not run).
3. [x] Confirm evidence handling (S6). [ ] Webhook events (S7).
4. [ ] Dataset v1.1.0: carrier field, `line_items[].fulfillment_type`, digital and mixed cases.

## Spike results (2026-10-12)

Case SAL-INR-001 (45.00 USD) → order/capture → INR dispute `PP-R-RVX-10191107`. Golden sync check: OK.

| Step | Result |
|---|---|
| S1 OAuth | Pass. Scopes: disputes read-seller, update-seller, create. |
| S2 order + capture | Pass. `custom_id`/`invoice_id` carry the case id into the dispute. |
| S3 create dispute via API | **Fail**: `400 No permissions to set target_client_id` (buyer assertion needs partner permission). Fallback: buyer opens dispute in sandbox UI, `s3-find` links it by capture id. |
| S4 read dispute | Pass. `MERCHANDISE_OR_SERVICE_NOT_RECEIVED`, `WAITING_FOR_SELLER_RESPONSE`, `INQUIRY`. |
| S5 require-evidence | Not needed (only valid in `UNDER_REVIEW`). |
| S6 provide evidence | Pass with one `PROOF_OF_FULFILLMENT` + 5 PDFs + tracking → `WAITING_FOR_BUYER_RESPONSE`. |
| Escalate | Pass → `UNDER_REVIEW`; stage still `INQUIRY` at last check. |
| S8 adjudicate | Pending: `adjudicate` link not yet offered. |
| S7 webhooks | Not run (needs a public tunnel). |

### Design consequences

1. **Mandatory evidence comes from PayPal**: `evidences[]` with `source = REQUESTED_FROM_SELLER` is the authoritative checklist (SAL v1.0 §6.1).
2. **One evidence entry per item without `item_id`**: multiple entries fail with `ITEM_ID_IS_MANDATORY_FOR_MULTIPLE_EVIDENCES`; attach many files to one entry.
3. **Check HATEOAS links before every write**: re-submitting fails with `422 ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`. The UI must disable actions PayPal does not offer.
4. **Fields come and go with state**: `seller_response_due_date` and `allowed_response_options` become null after the seller responds.
5. **Item category must be sent on orders**: without it PayPal records `DIGITAL_DOWNLOAD`, which changes which evidence applies.
6. **Linking needs no extra table**: `custom` and `invoice_number` on the disputed transaction identify the SAL case.
7. Recorded payloads contain account ids and buyer address; redaction must cover PII, not just tokens.
