# ADR-001: Golden dataset ↔ PayPal Sandbox synchronization

**Status:** Proposed
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
2. [ ] Run S1–S8 against the sandbox; record G1 outcome.
3. [ ] Confirm evidence-type mapping (S6) and webhook events (S7).
4. [ ] Dataset v1.1.0: carrier field, `line_items[].fulfillment_type`, digital and mixed cases.
