# ADR-006: SAL Agent proposes actions; the merchant approves each one

**Status:** Proposed (2026-10-27). For the PayPal AI Hackathon, deadline 12 Nov 2026 (internal target 10 Nov).
**Builds on:** ADR-002 (agent architecture), ADR-003 (approval bound to evidence, at-most-once send), ADR-005 (evidence copilot).

## Context

The agent today works on one kind of problem (a dispute) and produces one kind of output (a draft reply). The merchant has to open the case page to find out what to do. We want SAL to work behind the merchant's PayPal account:
- notice problems on its own;
- say what to do next and why;
- turn each step into one approval.

None of this weakens the rule that nothing is written to PayPal without the merchant.

What PayPal Sandbox gives us (checked live, 2026-10-27):

| Capability | Status |
|---|---|
| Disputes API (read, provide-evidence) | Works (in use since ADR-001) |
| Transaction Search `/v1/reporting/transactions` | Works. Shows hold codes; a live `T1110` (funds held for a dispute) with status `P` was found |
| Balances `/v1/reporting/balances` | Works (`withheld_balance` readable) |
| Tracking `/v1/shipping/trackers` | **403**. We cannot add tracking to a transaction. Tracking keeps going inside provide-evidence (`tracking_info`, with the PayPal carrier code from `app/carriers.py`) |

## Decision

The agent emits **action proposals** ("action cards"). Each card states:
- what SAL wants to do;
- why, with source references;
- the deadline;
- the exact payload it would send.

The merchant approves or dismisses each card. Approval executes it through the API, never through the agent.

### Action kinds in scope

| Kind | When proposed | On approval | Writes to PayPal |
|---|---|---|---|
| `SEND_EVIDENCE` | Assessment READY (or NEEDS_CHECK with the check acknowledged) and PayPal offers `provide_evidence` | The existing `submission.submit()`. It is the same send, now reached from a card | Yes (provide-evidence) |
| `ADD_DOCUMENT` | Assessment NEEDS_DOCUMENTS or WEAK | Nothing is sent. The card names the missing proposition and the document that proves it, and links to upload | No |
| `REPLY_BEFORE_DEADLINE` | An open dispute whose `deadline_at` is less than 72 h away and has no approved send yet | Opens the case | No |
| `EXPLAIN_HELD_FUNDS` | Transaction Search shows a hold code (T1110/T1111 dispute hold, T2107/T2108 payment hold, T2103/T2104 reserve) with no release yet | Nothing is sent. The card explains the hold in plain words and links to the dispute when it is a dispute hold | No |
| `EXPLAIN_DISPUTE` (migration 0010) | The dispute is not "item not received" (e.g. "not as described") | Nothing is sent. SAL explains it does not argue this kind of case and names the realistic choices in PayPal (partial refund, refund, return) | No |

Only `SEND_EVIDENCE` writes to PayPal. The others are guidance, which keeps the write surface the same as today.

**Seller-entered tracking numbers (migration 0010).** The seller can type a resi and courier on the case page
(`POST /api/disputes/{id}/tracking`). It is stored as a small `seller_shipment` document with origin
`SELLER_INPUT`. It is the seller's word, not proof: grounding accepts only `tracking_id` from it, so it names the
parcel and the PayPal carrier code for `tracking_info` and exposes a resi that differs from the courier page,
but it never shows the parcel moved or arrived. It is not attached to the PayPal reply as a file.

### Out of scope (stated in the README as roadmap)

- Adding tracking to a transaction: Tracking API returns 403 in our sandbox.
- Messaging the buyer, accepting a claim, refunds and offers. These are PayPal writes that would each need their own approval design.
- Account limitations: there is no API for ordinary merchants.
- An MCP server exposing SAL to other agents (part C) and PayPal Agent Toolkit read tools (part B). These come after A if time allows.

## Design

### Flow

```
trigger (webhook / sync / upload / hold scan)
  └─ worker job  propose_actions(merchant, dispute?)          read-only, deterministic
        reads: latest analysis + assessment, dispute deadline & allowed_actions, hold events
        writes: agent_actions rows (PROPOSED), superseding older PROPOSED cards for the same subject
merchant ── approve(card_id, payload_hash) ──► API
        SEND_EVIDENCE → submission.approve() + submission.submit()   (existing ADR-003 guarantees)
        other kinds   → DONE (they only guide)
```

**Proposals are deterministic code over the assessment, not free LLM output.** The LLM's part stays where it is: extraction and drafting, both verified. This keeps every card explainable and testable, and it is the same split as ADR-002: "LLM proposes facts, code decides, human approves".

### Data: migration 0009 `agent_actions` (tenant table, same pattern as 0003)

| Column | Notes |
|---|---|
| `id` uuid, `merchant_id` uuid, `dispute_id` uuid null | Composite FK `(dispute_id, merchant_id)` to `disputes` |
| `kind` text | CHECK in the four kinds above |
| `status` text | `PROPOSED` / `APPROVED` / `DONE` / `FAILED` / `DISMISSED` / `SUPERSEDED` |
| `subject_key` text | E.g. `dispute:<id>` or `hold:<transaction_id>`. Unique among open cards: `UNIQUE (merchant_id, subject_key, kind) WHERE status = 'PROPOSED'` |
| `title`, `rationale` text | Plain language, from `lib/plain`-style templates in Python |
| `sources` jsonb | The `SourceRef`s / transaction ids the card rests on |
| `payload` jsonb, `payload_hash` text | What would be sent (SEND_EVIDENCE: draft id, revision, snapshot hash, evidence hash) |
| `due_at` timestamptz null | PayPal's deadline, when there is one |
| `decided_by`, `decided_at`, `result` jsonb | Filled on approve, dismiss or execute |

**Grants:**
- `sal_app`: SELECT, plus UPDATE of `status`, `decided_*` and `result` only.
- `sal_worker`: SELECT, INSERT, UPDATE.
- A trigger like the one in 0005-era approvals stops `sal_app` setting `PROPOSED`. Only the worker proposes.

**RLS:** FORCE, `tenant_isolation`.

### Approval binding

Approving a card sends `payload_hash` back. The API rejects with 409 (`STALE_ACTION`) if:
- the card is no longer `PROPOSED`;
- its hash differs;
- for `SEND_EVIDENCE`, the draft revision, snapshot or evidence hash moved since the card was made.

This is the ADR-003 check again. It is not a new mechanism.

### API

- `GET /api/actions?status=PROPOSED`: the merchant's inbox, ordered by `due_at` then created.
- `POST /api/actions/{id}/approve` with `{payload_hash}`.
- `POST /api/actions/{id}/dismiss`.
- `GET /api/disputes/{id}` gains `actions` (open cards for that case).

### Worker

- New job `propose_actions`. It is enqueued after `analyze_dispute` succeeds, after `sync_dispute`, and by a periodic `scan_holds` (Transaction Search, last 31 days, `balance_affecting_records_only=N`). Idempotency key: `actions:<subject_key>:<analysis_id or txn status>`.
- `scan_holds` pairs hold and release codes per transaction id. It deduplicates on `(transaction_id, event_code)`, because one id can appear twice.
- **Autonomous watch (as built).** Every `SAL_WATCH_MINUTES` (default 10, `0` = off) the worker queues one round per
  watched merchant (each connected PayPal account, plus the demo merchant): `sync_disputes`, `scan_holds` and
  `refresh_actions`. `refresh_actions` re-proposes every open dispute, because cards also change with time: a
  deadline that comes within 72 hours needs a reply card even when nothing else happened. The job key names the
  time window (`watch:<kind>:<merchant>:<window>`), so a restart or a second worker never queues a round twice.
  The round only reads and proposes; nothing is written to PayPal without an approval.
- A card the merchant answered (DONE or DISMISSED) is not proposed again while its payload is unchanged.
- Money on hold is information, not a task: the card has no button and closes itself when PayPal releases the money.

### Web

- **Header and dashboard:** an "SAL suggests" inbox showing the count and the top 3 cards by deadline.
- **Case page:** the card replaces the bare "Approve reply" block. It shows the action, why (with the existing source links), the deadline, and Approve / Dismiss.
- **Wording:** plain language with no jargon. For example: *"SAL wants to send your 5 documents to PayPal. They prove payment, shipping and delivery. PayPal needs them by 10 Nov, 23:59 UTC."*

## Tests (written first)

- **Proposals by state:**
  - READY with `provide_evidence` offered gives exactly one `SEND_EVIDENCE`.
  - NEEDS_DOCUMENTS gives `ADD_DOCUMENT` naming the missing proposition.
  - A deadline under 72 h gives `REPLY_BEFORE_DEADLINE`.
  - SUBMITTED gives no new send card.
- **Re-analysis** supersedes the old open card and does not duplicate it (partial unique index).
- **Approving `SEND_EVIDENCE`:**
  - reaches PayPal once, with an existing fake;
  - a stale `payload_hash` returns 409;
  - documents changed since the card return 409 (`EVIDENCE_CHANGED`);
  - two simultaneous approvals send once.
- **Guidance cards** never call the PayPal sink.
- **Hold scan:**
  - T1110 without T1111 gives one `EXPLAIN_HELD_FUNDS`;
  - T1110 followed by T1111 gives none;
  - a duplicate transaction id gives one card.
- **Tenancy:** another merchant cannot list, approve or dismiss a card (404). `sal_app` cannot insert or propose.

## Demo script (for the video)

1. A PayPal dispute arrives (webhook or Check PayPal), and the worker analyses it.
2. The inbox shows two cards:
   - "Add proof of delivery" for case A (NEEDS_DOCUMENTS);
   - "Money held: 45.00 USD for a dispute", from a live T1110.
3. The merchant uploads the courier PDF. The card turns into "Send 5 documents to PayPal, due in 2 days".
4. The merchant approves, PayPal Sandbox accepts, and the status moves to UNDER_REVIEW.

## Plan (working days)

| Day | Work |
|---|---|
| 1 | Migration 0009, `app/actions.py` (propose rules, tests first) |
| 2 | `propose_actions` job wired after analyze/sync; approve/dismiss API with hash binding; tests |
| 3 | `scan_holds` with Transaction Search + EXPLAIN_HELD_FUNDS; tests with recorded payloads |
| 4 | Web: inbox and case-page card; plain-language texts; browser check |
| 5 | End-to-end on PayPal Sandbox with 2–4 new disputes; fix what it finds |
| + | Autonomous watch: periodic sync, held-funds scan and card refresh (as built, see Worker) |

## Consequences

- **The agent becomes visibly proactive** (cards appear without the merchant asking) while writes stay exactly as narrow as today: one kind, through ADR-003.
- **One more table and job.** The web case page changes its approval block, and existing approve/submit endpoints stay for compatibility and tests.
- **Risk: Transaction Search lags up to 3 hours,** so a hold card can lag the PayPal dashboard. The card says "as of <time>".
