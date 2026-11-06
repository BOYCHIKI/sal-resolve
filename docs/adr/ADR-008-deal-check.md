# ADR-008: Deal Check before delivery

**Status:** Accepted, implemented 2026-11-02
**Date:** 2026-11-02
**Scope:** Checking B2B deals in every category before delivery, for people and for AI agents.
**Constraint:** No new infrastructure. Postgres, the existing job queue and the existing model client only.

## 1. Why

Replying to disputes is already served by other products, and evidence cannot be created after the fact. A wrong item, amount or address is cheapest to catch before delivery. SAL therefore compares what was ordered with what was invoiced, and keeps the record for a later dispute.

## 2. Decisions

### D1: Exact data, and no model in the verdict

`app/deals.py` takes orders and invoices as strict models:

- Money is a decimal string. JSON numbers and `1,200.00` are refused.
- Dates carry a time zone.
- Unknown fields are refused.
- Item codes match exactly, apart from case and surrounding spaces.

The check is plain code, so the same input always gives the same verdict and no document text can steer it. Every difference holds the deal; SAL never settles one by itself.

### D2: The verdict belongs to the worker

The API records what arrived and marks the deal `CHECKING`, which drops any earlier verdict at once. Only `sal_worker` writes `HOLD` or `CLEAR`, in one transaction with the row locked. Each invoice gets a new `invoice_revision`, so returning to an earlier invoice is checked again. The watch round finishes any check whose job failed.

### D3: A hold lives inside SAL

`HOLD` raises a `REVIEW_DEAL_HOLD` card. Nothing in this flow calls PayPal: no client is passed to it, and tests fail if one is used. Pressing the card only acknowledges it. The hold ends when a corrected invoice matches.

### D4: Each agent has its own identity

Agents reach `/agent/v1/` with their own bearer token instead of the web server's internal token.

- The token reads `salagent.<merchant id>.<secret>`. The merchant id only picks the tenant, so the lookup runs under RLS. It proves nothing until the secret's SHA-256 is found there.
- A credential has one role. A buyer's agent orders and sees only its own deals; a seller's agent invoices.
- `approved_by` must equal the verified agent's name.
- Credentials expire after 90 days and can be revoked.
- `/api/deals` only reads.

### D5: The model reads, code proves, a person confirms

Files pass through three stages in `app/deal_documents.py`:

1. A PDF with text is read directly. A photo goes through the vision model, which copies it into lines.
2. The model proposes values, each naming its line. `ground_document` keeps a value only if it is written on that line, so a misread leaves a blank and never a wrong number. Blanks in required fields trigger up to two more reads, which may only fill blanks.
   A photo is copied twice, and the values a deal is compared on must appear in both copies. This reduces misread characters but does not end them: both copies can repeat the same misreading of an alphanumeric code.
3. The seller checks the values beside the page and confirms. No deal or invoice exists before that, and the confirmed form passes through the D1 models.

### D6: A clear deal becomes evidence

An invoice may name its PayPal transaction. When a dispute arrives on that transaction, the worker attaches a `deal_record` document. Only `CLEAR` deals are attached. As with packing proof, the record supports the case but grounds no fact.

### D7: A correction request is prepared, not sent

The seller presses **Request a correction** on a held deal. Code writes the message from the findings, one per invoice revision, and the deal's agents can read it from the agent API. SAL has no channel to the other side and sends nothing: the seller passes the message on. A new invoice retires the request.

### D8: An invoice can come straight from PayPal (added 2026-11-06)

`POST /api/deals/{ref}/paypal-invoice` reads the seller's invoice from the PayPal Invoicing API (Sandbox) and records
it like any other invoice, so it gets the same check before the seller sends it.

- Each PayPal line's item name must be its item code, because PayPal invoices have no code field and Deal Check
  matches lines by code. Anything else is refused with that explanation.
- SAL holds one set of PayPal credentials, owned by the demo business. Only that business may read invoices with
  them; any other business is refused before PayPal is called (`PAYPAL_NOT_CONNECTED`).
- SAL only reads the invoice. Sending it stays in PayPal, with the seller.

## 3. Alternatives rejected

- **SAL as a buying agent.** It would hold spending authority and money, and compete with the platforms themselves. SAL stays the checker between two agents.
- **A model deciding the verdict.** Its answers vary, and it would read attacker-written text at the moment of decision.
- **Auto-confirming read documents.** The test model returned empty or broken values in about half of six reads. Proof stops those values, but only a person can supply a blank.
- **A service account with cross-tenant lookup for tokens.** The token naming its tenant keeps RLS intact.

## 4. Limits

- SAL compares documents. It cannot tell whether an order was right in the first place, or whether a part fits.
- `/agent/v1/` slows repeated bad tokens per address, counted in each API process. A public deployment behind a proxy needs the real client address and a shared counter.
- Credentials are issued from the command line for the demo merchant only.
- Agents reach SAL over MCP (`app/mcp_server.py`, a thin stdio wrapper over `/agent/v1/`). `app/ai_agents.py` runs a
  buyer's and a seller's agent on the configured OpenAI model; they choose their own tool calls. On 2026-11-04 two runs
  in a row ended the same way: order, HOLD on the wrong item code, the seller's agent corrected it, CLEAR, PAY. On the
  first try the buyer's agent sent the wrong `approved_by` and SAL refused it with `AGENT_NAME_MISMATCH`. There is
  no ACP or AP2 integration.
- Photos and PO text go to OpenAI. A seller must be told before real documents are used.
- Scanned PDFs are read through Pillow (pinned in `requirements.lock`); no real scanned document has been tried yet.
- First real public documents, 2026-11-03 (four City of San Diego POs, three Bradenton Beach timesheet invoices):
  - PO number, total and tax were right on all four POs.
  - On one PO the model swapped quantity and unit price (70,000 × 1.00 read as 1 × 70,000). Both numbers are on the line, so proof cannot catch it; the seller's check has to.
  - Line numbers were taken as item codes, and invoices that show only "$" left the currency blank.
  - Long timesheet invoices (180 to 400 lines) gave only part of their items, and twice used up the model's answer. Such a read now comes back blank instead of failing. The partial items then fail the invoice total check and hold the deal.
- Accuracy is still measured on a handful of real documents, so no rate is claimed.
