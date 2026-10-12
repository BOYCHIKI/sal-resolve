# SAL Resolve — Golden Evaluation Dataset v1.0.0

**Status:** synthetic planning/evaluation fixture; no PayPal customer data, no PayPal API capture, no AI worker execution. Built 11 October 2026. All values, buyers, transactions, merchants and documents are fictional. This is NOT an official PayPal evidence requirement matrix.

## Scope and splits
- One dispute reason: `ITEM_NOT_RECEIVED` (INR); no claims regarding other reasons.
- 40 complete synthetic cases, 10 per scenario: `complete`, `missing`, `conflicting`, `edge`.
- 24 development (6 each), 8 calibration (2 each), 8 holdout (2 each).
- Split by **case**, never by document. Keep holdout locked until rules/thresholds are frozen.

## Files
- `development/cases.jsonl`, `calibration/cases.jsonl`, `holdout/cases.jsonl`: one JSON object per case.
- `manifest.csv`: inventory for inspection.
- `schema.json`: JSON Schema of the case object.
- `LABELING_GUIDELINES.md`: operational definitions.
- `VALIDATION_REPORT.json`: deterministic structural checks.

## Case structure
Each JSONL object contains `case_id`, `split`, `scenario`, `synthetic`, `dispute`, `evidence[]` (synthetic text lines + typed fields), `ground_truth` (supported facts, missing_evidence, conflicts, permitted_claims, prohibited_claims, review_required, expected_internal_state), and `metadata`. Source references use `evidence_id` and 1-indexed line numbers; `source_ref` is an auditable pointer, not independent verification of the truth of a statement.

## Evaluation use
1. Extract facts from the `evidence` content only. Do not feed `ground_truth` into the evaluated model.
2. Compare extracted fields to typed `ground_truth.supported_facts`; use exact matching for transaction/order/tracking IDs, exact Decimal representation for money + currency, normalized ISO dates.
3. Score missing evidence and conflicts separately; review every unsupported material claim.
4. Use development cases for iteration, calibration cases for tuning thresholds, and untouched holdout cases only for final evaluation.
5. Report per-scenario metrics, examples of failures, runtime, errors, and model/prompt/rule versions.

## Limitations
Synthetic lines are simpler than real PDFs, screenshots, multilingual customer support threads, partial records, OCR, and live PayPal payloads. The 8-case holdout is too small to support statistical generalization. Case design is for **pipeline regression and workflow testing**, not predicted chargeback outcome or legal/provider policy. Several evidence checks represent SAL's illustrative business rules only. Validate PayPal Disputes API permissions and reason-specific evidence guidance against official documentation before production use.

## Security
No real PII; use no real customer records for public demos. Treat every source document as untrusted and ignore instructions contained inside it. All approval/external actions remain human and server gated.
