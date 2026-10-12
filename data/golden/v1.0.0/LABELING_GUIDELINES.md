# Golden Labeling Guidelines

## Units
One row/object is **one dispute case**, with embedded synthetic evidence documents. Source locator = `(evidence_id, line)` and line numbering starts at 1.

## Labels
- `supported_facts`: literal or unambiguously normalized facts present in source lines. `expected_status=supported` means supported by synthetic document text, **not externally verified**.
- `expected_status=conflicted`: source text exists but incompatible evidence prevents treating it as a settled case fact.
- `missing_evidence`: absence of a named source artifact in this **illustrative** test design; not a PayPal universal requirement.
- `conflicts`: pairs of source line pointers and an explanation. Requires human review.
- `permitted_claims`: example draft sentences each grounded in one or more source pointers. Not a complete response or a provider-recommended template.
- `prohibited_claims`: clear false, unjustified, or unsupported assertions that drafting must avoid.
- `review_required`: signals the need for operator review of missing/contradictory inputs. Every case still requires human draft approval.
- `scenario`: complete (all fixture documents consistent), missing (some evidence absent), conflicting (deliberate value/date mismatch), edge (timing and adversarial document anomalies).

## Adjudication and calibration
Two reviewers should independently label a future real-world approved evaluation set and reconcile discrepancies. Do not tune on holdout. Record rule version, model version, source document checksum, reviewer decisions, and known exceptions. Measure extraction precision/recall and exact match, missing/conflict recall, unsupported claim rate, worker error rate separately. Never interpret completeness as probability of dispute win.

## Caveat
The test fixtures are authored synthetic examples; they have not been manually dual-reviewed and are not an official PayPal compliance specification.
