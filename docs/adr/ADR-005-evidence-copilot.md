# ADR-005: SAL Resolve as the evidence copilot for PayPal disputes

**Status:** Accepted (positioning chosen by the project owner, 2026-10-15). Implementation in progress.
**Date:** 2026-10-15
**Design:** [SAL v2 system design](../design/SAL-v2-evidence-copilot.md)

## Context

SAL already grounds every fact, flags missing and conflicting evidence, ignores hidden instructions, and
sends nothing without a person's approval. Its name and its case page still lead with the reply, so it
reads like a reply generator.

Three positionings were weighed:

| Option | Positioning | Pros | Cons |
|---|---|---|---|
| A | An Evidence Intelligence Copilot for Payment Disputes | Strongest sense of a new category | Jargon for merchants; "payment disputes" overclaims (today: PayPal, Item Not Received) |
| B | The evidence copilot for PayPal disputes | Honest scope, easy to understand, fits "Best Use of PayPal + AI" | Sounds less ambitious |
| C | Keep "Your AI agent for PayPal disputes" | No extra work | Sounds like a reply generator; hides what SAL does best |

## Decision

Use **B as the name and A as the idea**:

> **SAL Resolve: the evidence copilot for PayPal disputes.**
> *Evidence intelligence for merchants: know what your documents prove before you reply.*

The product has to show this, not just say it:

1. **ASSESS stage (deterministic).**
   - Five Item-Not-Received propositions (payment matches, shipped, delivered, delivery date consistent, buyer messages clean), each proven, missing, contradicted or flagged, and each pointing to its source lines.
   - A readiness status (READY / NEEDS_DOCUMENTS / NEEDS_CHECK / WEAK) with one next action.
   - No win or loss prediction, and no numeric "strength" score.
2. **Payment proof comes from PayPal.**
   - A worker job reads the disputed transaction through Transaction Search and stores it as a "PayPal transaction record" (`origin = PAYPAL_API`).
   - Only a PayPal record, or a seeded practice record, can prove payment. An uploaded bank or e-wallet receipt is labelled "Not a PayPal record".
   - Spike S9 (2026-10-15) confirmed Transaction Search works on the sandbox app.
3. **The reply follows the assessment.** The drafter only receives facts behind proven propositions, and verification rejects anything else.
4. **The case page leads with "What your documents prove".**

## Consequences

**Easier**
- The demo tells one coherent story: evidence, then decision, then reply.
- Review finding #1 (two values for one field) becomes part of the model: a contradiction.
- The PayPal integration is deeper: Disputes, Transaction Search, provide-evidence and webhooks.

**Harder**
- One more migration (0006), one more job kind, and a readiness metric to keep accurate.

**Revisit when**
- Other dispute reasons are added: propositions become per-reason rule sets.
- PayPal grants Tracking API access: `shipped` and `delivered` can also be proven from PayPal.
- Real merchant data arrives (golden v2.0.0): measure readiness against PayPal's own outcomes.

## Results (2026-10-15)

### Built
- `app/agent/assess.py`: the five propositions, readiness, next action and `claimable()`.
- Migration 0006: `evidence.origin` (UPLOAD / PAYPAL_API / SEED), a nullable `object_key`, and `analyses.assessment`.
- `paypal_evidence` job:
  - Calls Transaction Search, renders a "PayPal transaction record" with no personal data, and stores it with `origin = PAYPAL_API`.
  - Missing permission (4xx) fails visibly; "not found yet" retries.
- The rule extractor reads SAL's own rendering of the PayPal record exactly, so payment is proven even without the LLM.
- Readiness is shown in the API (analysis and queue summary) and on the web, which leads with "What your documents prove" and marks documents fetched from PayPal with a **From PayPal** badge.
- `RULE_VERSION` is now `SAL-SYN-INR-2`.
- The evaluator adds `ready acc`: readiness compared with the readiness implied by the labels alone.

### Verified
- **Tests:** 130 backend tests pass. They include a contract recorded from sandbox Transaction Search (`contracts/paypal/*_s9_transaction_search.json`, personal data removed) and an "oracle extractor" check that every real-format label yields the expected readiness.
- **Live sandbox:** for dispute `PP-R-RVX-10191107`, the job stored PayPal's record of transaction `2MK81285P20231246` (Completed, 45.00 USD). The case page shows "The PayPal payment matches the dispute: Proven". Readiness is WEAK, correctly: the earlier courier uploads were lost when the dev database was reset.

| Evaluation (gpt-5-nano, rules+LLM) | Golden dev (24) | Real-format (6) |
|---|---|---|
| Fact precision / recall | 1.00 / 1.00 | 1.00 / 0.96 |
| Missing / conflict recall | 1.00 / 1.00 | 1.00 / 1.00 |
| **Readiness accuracy** | **1.00** | **1.00** |
| Unsupported / prohibited claims | 0 / 0 | 0 / 0 |

Baseline without the LLM: golden 1.00 on every metric, including readiness.

### Note on `review acc`
On real-format, `review acc` is 0.83 (RF-05). The v1 labels' `review_required` predates ADR-005. RF-05 has no PayPal payment record, so v2 rightly asks for review (NEEDS_DOCUMENTS). This is a label definition mismatch, not an error. Readiness, which is the v2 measure, is 1.00.
