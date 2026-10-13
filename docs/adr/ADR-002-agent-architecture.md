# ADR-002: Agent architecture — fixed pipeline with one bounded agentic stage

**Status:** Accepted
**Date:** 2026-10-13
**Deciders:** SAL project owner

## Context

- Design Review v1 asked for a bounded pipeline; SAL v1.1 D1 asked for a background agent. They conflicted.
- The judges score "Best Use of PayPal + AI", but SAL's acceptance criteria require measurable grounding
  (zero unsupported claims, missing-evidence recall) against the golden dataset.
- The LLM provider is not chosen yet (v1.1 §8).

## Decision

**Option C.** Code owns the order of stages; only *gather* is agentic.

```
load → gather (agent loop: read-only tools, max 8 steps) → extract → ground → INR rules
     → snapshot hash → draft → verify claims → persist (agent_run, tool_calls, analysis, draft)
```

- Three provider-neutral roles (`app/agent/roles.py`): **Planner**, **Extractor**, **Drafter**. Any LLM
  adapter implements these protocols; the pipeline does not change when a provider is chosen.
- Deterministic baselines (`ReadAllPlanner`, `RuleExtractor`, `TemplateDrafter`) run today and set the floor
  an LLM must meet.
- Write tools do not exist in the agent toolbox. Requests for them are rejected and recorded.
- Extraction only sees documents the agent actually read. Every fact must quote its cited line, and its
  value must appear there as a whole token. Claims must cite supported facts and contain no prohibited
  assertion.
- Instruction-like text inside evidence becomes an `untrusted_instruction` finding, never an action.
- If the dispute changes while the agent runs, the result is discarded and a fresh analysis is queued.

## Options considered

| | A. Free agent | B. Pure pipeline | **C. Pipeline + bounded agent** |
|---|---|---|---|
| Testable against golden data | Low | High | High |
| Visible agent behaviour | High | Low | Medium–high (tool trail is stored and shown) |
| Risk (cost, loops, injection) | High | Low | Low |

## Baseline results (development split, 24 cases)

| Metric | Value |
|---|---|
| Fact precision / recall | 1.00 / 1.00 |
| Provenance (cites the labelled line) | 0.88 |
| Missing-evidence recall / precision | 1.00 / 1.00 |
| Conflict recall / precision | 1.00 / 1.00 |
| review_required accuracy | 1.00 |
| Unsupported / prohibited claims | 0 / 0 |

**Read with care.** Golden documents are uniform synthetic templates and the regex extractor was written
for them, so a perfect score is expected and says little about real PDFs, OCR or emails. These numbers are
a regression floor, not evidence of real-world quality.

## Dataset findings to fix in v1.1.0

1. **Holdout exposure.** While deriving the INR rules on 2026-10-13, labels from all three splits
   (including holdout) were printed. The rules are simple and identical across splits, but the holdout can
   no longer count as unseen for rule design. v1.1.0 should add a fresh, unopened holdout.
2. **Label inconsistency.** In `conflicting` cases the two delivery-date facts are labelled `conflicted`;
   in `edge` cases with the same date mismatch they are labelled `supported`. The scorer compares conflicts
   by field to stay neutral; v1.1.0 should make the labels consistent.
3. Grounding bugs found by tests and fixed: substring matching accepted `5.00` inside `45.00` and
   `TXN-…-100000` inside `TXN-…-1000001`. Matching is now whole-token.

## Consequences

- Choosing a provider means writing three adapter classes, then running `python -m app.agent.evaluate`.
- The harness refuses the holdout split without `--final`.
- Real documents need a parser that fills `evidence.content_lines`; upload is not built yet.
