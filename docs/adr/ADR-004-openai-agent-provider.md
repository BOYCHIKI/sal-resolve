# ADR-004: OpenAI as the LLM provider for the agent

**Status:** Accepted (gate passed 2026-10-14 with gpt-5-nano, reasoning effort low)
**Date:** 2026-10-14
**Deciders:** SAL project owner
**Builds on:** ADR-002 (pipeline with one bounded agentic stage). That ADR left the provider open.

## Context

- **Where the agent is today.** It runs on deterministic baselines: `ReadAllPlanner`, `RuleExtractor` and `TemplateDrafter`.
  - They score perfectly on the golden dataset only because those documents are uniform templates.
  - On a real courier PDF, the text is extracted but `RuleExtractor` finds no facts. The case then shows "missing" and "no reply", even when the proof is there. This is the gap an LLM must close.
- **The adapter already exists.** `app/agent/llm.py` (`LLMRoles`) is written against the OpenAI Python SDK and uses `chat.completions.parse` with Pydantic schemas. It is currently pointed at Gemini's OpenAI-compatible endpoint.
- **What went wrong with Gemini.** The free tier ran out at 20 requests a day during development. Adding the API key also once switched the worker to the LLM by accident; that is now opt-in only, via `SAL_AGENT_ROLES=llm`.
- **Safety stays in code, not in the model.**
  - Grounding: every fact must quote its cited line, and its value must appear there as a whole token.
  - Claim verification and the INR rules also stay in code.
  - The LLM produces *candidates*. Code decides what is true.
- **Constraints.**
  - Submit by 12 Nov 2026 (internal target 10 Nov).
  - One developer.
  - No over-engineering.
  - Tests must never call a paid API.

## Decision

Use **OpenAI** for the **Extractor** and **Drafter** roles through the existing `LLMRoles` adapter.

```
load → gather: ReadAllPlanner (code)          ← unchanged: ≤10 docs per case, reading all is cheaper and safer
     → extract: OpenAI, structured output       ← candidate facts with quotes
     → ground   (code) rejects any fact whose quote/value is not in the cited line
     → INR rules (code) missing / conflicts / injection
     → draft:   OpenAI, structured output       ← statements citing supported facts only
     → verify   (code) every statement backed by a supported fact, no prohibited claims
```

- **Two calls per analysis** (extract, draft). There are no tools and no write access. The model only sees document text, never files, keys or other tenants.
- **The model is chosen by evaluation, not by name in code.**
  - `SAL_LLM_MODEL` is required when `SAL_AGENT_ROLES=llm`; there is no hard-coded default that can go stale.
  - Start with OpenAI's current small model that supports Structured Outputs. Move up a size only if it fails the gate below.
- **The planner stays deterministic.** An LLM planner (an agentic gather) only pays off when cases have many documents. Revisit after the demo.

### Model and budget until submission

Prices are OpenAI standard tier per 1M tokens, checked 2026-10-14.

| Model | Input | Output | Est. per analysis¹ | ~800 analyses² |
|---|---|---|---|---|
| **gpt-5-nano** (try first) | $0.05 | $0.40 | ~$0.0015 | **~$1.20** |
| **gpt-5-mini** (step up if nano fails the gate) | $0.25 | $2.00 | ~$0.007 | ~$6 |
| gpt-4.1-nano | $0.10 | $0.40 | ~$0.001 | ~$0.80 |
| gpt-4.1-mini | $0.40 | $1.60 | ~$0.004 | ~$3.20 |

¹ Two calls: about 4k input tokens, plus about 1.5–3k output tokens. For gpt-5 models that output includes reasoning tokens.
² About 20 evaluation runs × 30 cases, plus about 200 demo and test analyses before 12 Nov.

- **Order of trial:** `gpt-5-nano`, then `gpt-5-mini` if nano misses the acceptance gate. The `gpt-4.1` pair is the fallback if the gpt-5 models' reasoning-token output costs more than estimated.
- **Spending limit:** set **$10** on the API project. That covers the worst case (gpt-5-mini) with margin.
- **gpt-5 models are reasoning models:**
  - Do not send `temperature` (guardrail 4).
  - Set `reasoning_effort` low (`SAL_LLM_REASONING_EFFORT`) to keep output tokens down.
- **Re-runs:** the evaluation can use the Batch API at half price, but synchronous calls are simpler and cheap enough at this volume. Not worth building.

## Options considered

### A. OpenAI API (chosen)
| Dimension | Assessment |
|---|---|
| Complexity | Low. The adapter exists; this is a configuration change plus small hardening. |
| Cost | Paid per token. About 2 calls and a few thousand tokens per analysis, so cents per day at demo volume. A spending limit is set on the API project. |
| Reliability | Paid tier, so no 20-requests-a-day ceiling. Structured Outputs with a strict JSON schema means fewer parse failures. |
| Team familiarity | High. The SDK is already used. |

**Pros**
- The SDK the adapter was written for.
- Strict schema adherence.
- Predictable limits.
- Easy to explain to judges.

**Cons**
- Costs money.
- Dispute text, which contains buyer names and addresses, leaves our system.
- Some newer models reject parameters such as `temperature`.

### B. Gemini free tier via the OpenAI-compatible endpoint (current wiring)
| Dimension | Assessment |
|---|---|
| Complexity | Low (already wired) |
| Cost | Free |
| Reliability | **Poor for us.** The 20-requests-a-day quota was exhausted while evaluating 24 cases; the compatibility layer differs in edge cases. |

**Pros:** free.
**Cons:**
- Cannot run a full evaluation in a day.
- A free-tier data-use policy is unsuitable for real merchant data.

### C. Stay on the baseline (no LLM)
| Dimension | Assessment |
|---|---|
| Complexity | None |
| Cost | Free |
| Quality on real documents | **Fails.** It recognises golden templates only. |

**Pros:** deterministic, free, perfect on the synthetic set.
**Cons:**
- Useless on real PDFs.
- Weak "Best Use of AI" story.

### D. Local model (e.g. Ollama)
| Dimension | Assessment |
|---|---|
| Complexity | Medium. Another runtime to install, and a GPU or slow CPU inference. |
| Cost | Free per call |
| Quality | Lower schema adherence on small models; hard to deploy for judges. |

**Pros:** data stays local.
**Cons:**
- Deploying it for judges is impractical.
- Extra setup for every machine.

## Trade-off analysis

- **The cost of A is small next to its benefit.** The deciding factor is that the evaluation harness has to run end to end, repeatedly, before 10 Nov. Only A allows that.
- **Data exposure is acceptable for the hackathon:** sandbox and synthetic data only. It must be revisited before any real merchant uses SAL.
- **Grounding contains the model risk.** A model that hallucinates produces *rejected* facts, which show up as missing evidence. It cannot produce false statements in the reply. The worst case is "less helpful", not "wrong reply sent to PayPal".

## Guardrails (part of the decision)

1. **Opt-in and isolated.** The LLM runs only with `SAL_AGENT_ROLES=llm`. Tests force `baseline` (`conftest.py`), so CI never spends money.
2. **The key lives only in `apps/api/.env`** (`SAL_LLM_API_KEY`). Use a project-scoped key, with a monthly spending limit set in the OpenAI dashboard.
3. **Input and output caps.**
   - At most 10 documents and 200 lines per document per call; anything longer is truncated and recorded.
   - Each call sets `max_completion_tokens`.
   - The 60 s timeout and 2 retries stay as they are.
4. **Only send parameters the model accepts.**
   - `temperature` is sent only when `SAL_LLM_TEMPERATURE` is set. Reasoning models such as gpt-5 reject it.
   - `reasoning_effort` is sent only when `SAL_LLM_REASONING_EFFORT` is set.
5. **Degrade, never block.**
   - If OpenAI fails after the SDK's retries, the run falls back to the baseline roles. The stored roles are labelled `baseline (LLM unavailable)`.
   - The operator still gets missing-evidence checks, which are computed from document types.
6. **Traceability.** `agent_runs.roles` stores `llm:<model>`, so every draft shows which model produced its candidates. Prompts and the rule version are versioned in code.
7. **Untrusted text stays data.** Documents are passed as JSON fields, never concatenated into instructions. Injection text is still flagged by the rules. The model has no tools to act on it.

## Acceptance gate (before the LLM is used in the demo)

Run `python -m app.agent.evaluate --roles llm` on the **development** split (24 cases) and on a new **real-format set**.

| Metric | Must be |
|---|---|
| Unsupported / prohibited claims | **0 / 0** (hard stop) |
| Fact precision after grounding | ≥ 0.95 |
| Fact recall | ≥ 0.90 |
| Missing-evidence and conflict recall | 1.00 (rule-based; must not regress) |
| Real-format set: cases where the baseline finds no facts but the LLM does | ≥ 5 of 6 |

The **real-format set** is about 6 synthetic documents in realistic, varied layouts: a shop invoice, a courier email, a tracking-page PDF, a signed delivery slip, a payment receipt and a buyer chat. They are labelled like the golden cases and stored as `data/golden/v1.1.0/real_format/`. Without it, the LLM's value cannot be shown, because the baseline already scores 1.00 on templates.

The holdout split stays locked (`--final`) until prompts are frozen.

## Consequences

**Easier**
- Real PDFs produce facts and a reply.
- Evaluation can run as often as needed.
- The demo shows a genuine AI step with a visible tool and grounding trail.

**Harder**
- A paid key to manage.
- Per-token cost.
- Model deprecations need a re-run of the gate.

**Revisit when**
- **A real merchant uses SAL:** check OpenAI's current data-retention terms (zero-retention options), or redact names and addresses before sending.
- **Cases with many documents:** consider an LLM planner (agentic gather, already bounded to 8 read-only steps).
- **The free option improves, or costs matter:** the adapter is endpoint-agnostic, so switching back is configuration only.

## Action items

1. [x] `llm.py`
   - The default endpoint is now OpenAI.
   - `SAL_LLM_MODEL` is required.
   - `temperature` and `reasoning_effort` are sent only when set.
   - `max_completion_tokens` is set, and input is capped at 10 documents / 200 lines.
   - The prompt states value formats.
2. [x] `runner.py`: when the LLM call fails (after the SDK's 2 retries), the run falls back to the baseline roles. It is stored as `baseline:… (LLM unavailable: <error>)`.
3. [x] `.env.example`: OpenAI values. In the owner's `.env`, the non-secret LLM settings were switched to `gpt-5-nano` / `low`. The owner has since replaced the key with an OpenAI key.
4. [x] Owner: create a project-scoped OpenAI key with a $10 limit and put it in `apps/api/.env`. Never in chat or git.
5. [x] Real-format set: `data/golden/v1.1.0/real_format/` (6 cases, generated by `data/golden/make_real_format.py`).
   - Scored with `--split real_format`.
   - A perfect-extractor test confirms that every label survives grounding and that the rules reproduce the labelled findings.
6. [x] Run the gate with gpt-5-nano. Results below; Status set to Accepted.
7. [ ] Run one live sandbox case end to end with `SAL_AGENT_ROLES=llm`, using a real-looking PDF.

## Findings during implementation (2026-10-14)

**Grounding rejected real formats.** It required the normalized value to appear literally, so a correct `2026-09-04` was rejected against "Delivered On: September 4, 2026". The model would have been blamed for a grounding limitation. `validation.value_in_line` now also accepts the *same* value written differently:
- Dates with the month in words, or year-first dates.
- Amounts with currency marks or thousands separators.
- Statuses regardless of case.
- References without the `TXN-/ORD-/TRK-` prefix.

It still rejects:
- Ambiguous numeric dates (08/07/2026).
- Bare numbers as money.
- Part of a larger amount or reference.
- European decimal commas (58,90). These are a known gap: the fact is lost, not wrongly accepted.

Tests are in `tests/test_grounding_formats.py`. The golden baseline is unchanged at 1.00.

**Baseline on the real-format set:** fact recall 0.00 (0 of 50 facts).
- Missing-evidence and injection findings still work, because they come from rules.
- The two conflicts that depend on extracted facts (date mismatch, amount vs dispute) are missed.

This is the gap the LLM has to close.

**Local database port.** Windows had reserved TCP 54329–54428 (a Hyper-V/WinNAT dynamic exclusion), so Postgres could not start. The dev database moved to `127.0.0.1:15432`, below the 49152+ range those reservations come from.

## Gate results (2026-10-14, gpt-5-nano, `reasoning_effort=low`)

**Final configuration**
- Extractor: `UnionExtractor(RuleExtractor, LLM)`. Rules run first.
- Drafter: LLM, limited to the facts a reply may state (`CLAIM_FIELDS`).
- Grounding, rules and claim verification are unchanged in role.

| Metric | Gate | Golden development (24) | Real-format (6) |
|---|---|---|---|
| Unsupported / prohibited claims | 0 / 0 | **0 / 0** | **0 / 0** |
| Fact precision | ≥ 0.95 | **1.00** | **1.00** |
| Fact recall | ≥ 0.90 | **1.00** | **0.98** |
| Missing-evidence recall | 1.00 | **1.00** | **1.00** |
| Conflict recall | 1.00 | **1.00** | **1.00** |
| review_required accuracy | — | 0.96 | 1.00 |
| Real-format cases where the baseline finds no facts but the LLM does | ≥ 5 of 6 | — | **6 of 6** (baseline 0 of 50 facts) |

### What it took to get there (measured, in order)

1. **LLM alone (extractor + drafter).**
   - Real-format: precision 0.98, recall 0.90.
   - **Run-to-run variance was large.** Conflict recall went 0.67 → 1.00 between identical runs.
   - On the golden set, a missed date silently hid a delivery-date conflict: conflict recall **0.71** in one run. This is the dangerous failure, because the reply could then state a delivery date without a warning.
2. **Prompt: field meanings and exact-value claims.**
   - The prompt now says which date belongs in which field and that totals include shipping.
   - The drafter may list a field only if its exact value is written in the statement.
   - Result: unsupported claims dropped to 0, but the variance remained.
3. **Rules first, then the model (`UnionExtractor`).**
   - Known layouts are read deterministically every time; the model covers the rest.
   - Golden set: 1.00 across the board.
4. **The drafter only states claimable facts.**
   - Two claims about `ship_date` were grounded in the documents but are outside the labelled claim scope. They now stay as facts and are not asserted to PayPal.
5. **`reasoning_effort=medium` rejected.**
   - 3 of 6 real-format cases spent all 4000 output tokens on reasoning and returned nothing (`LengthFinishReasonError`).
   - It was also 2–3× slower.

**Also fixed:** the status normalizer now keeps the leading status of carrier detail ("Delivered, In/At Mailbox" → DELIVERED).

### Caveats

- **Six real-format cases is a small sample.** They were written by us and are not real merchant documents. Treat 0.98 as "works on varied layouts", not as a production accuracy figure.
- **gpt-5-nano is non-deterministic even at low effort.** Rules-first and grounding contain the impact: a miss on a real-format document shows as a missing fact or an extra review, never as a false statement.
- **Latency:** about 20–45 s per analysis (two calls). This is fine for a background worker, but the UI must keep showing "SAL is reading your documents…".
- **Cost:** about 15 evaluation runs today, at roughly $0.01–0.04 each. This is well inside the $10 limit.
- **Step up to gpt-5-mini** if a live demo case shows misses that nano keeps repeating.
