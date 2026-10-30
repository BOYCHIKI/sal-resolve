# Agent evaluation

How SAL's evidence agent is measured, what the numbers are today, and what they do not prove.

## How to run

```
cd apps/api
python -m app.agent.evaluate                                   # development split, no model (deterministic floor)
python -m app.agent.evaluate --split real_format --roles llm   # realistic layouts (v1.1.0)
python -m app.agent.evaluate --split sea_dev --roles llm       # Indonesian and Philippine sellers (v1.2.0)
python -m app.agent.evaluate --split sea_holdout --final --roles llm   # only after rules and prompts are frozen
```

The model only proposes facts. Grounding, the rules and ASSESS decide what is true, so the metrics that matter most
are `fact P` (nothing wrong accepted), `ready acc` (READY only when the evidence really proves the case) and
`unsupported` (no claim without a source).

## Datasets

| Split | Cases | What it covers |
|---|---|---|
| development (v1.0.0) | 24 | Uniform templates; the regex baseline must stay perfect here |
| real_format (v1.1.0) | 6 | Dates in words, symbols, e-mails, OCR-like scans, ambiguous dates, an injected instruction |
| sea_dev (v1.2.0) | 18 | JNE, J&T, SiCepat, Pos Indonesia, LBC, Ninja Van, DHL; Indonesian dates and amounts; WhatsApp chats; traps. D13–D16 (rule version 3): delivery address vs PayPal's ship-to, and a proof dated before the ship date. D17–D18: unauthorized payments |
| sea_holdout (v1.2.0) | 8 | Same families, different documents; scored only with `--final` |

All cases are synthetic, with invented names and numbers. `data/golden/make_sea_format.py` writes v1.2.0; edit there,
not in the JSONL. A dataset test (`test_real_format_labels_are_groundable_and_consistent_with_rules`) checks that
every label survives grounding and that the rules find exactly the labelled conflicts.

## Results (gpt-5-nano, reasoning effort low, 2026-10-27)

| Split | fact P | fact R | missing R/P | conflict R/P | review acc | ready acc | unsupported |
|---|---|---|---|---|---|---|---|
| development (no model) | 1.00 | 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 | 1.00 | 0 |
| real_format | 1.00 | 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 | 1.00 | 0 |
| sea_dev | 1.00 | 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 | 1.00 | 0 |
| sea_holdout | 1.00 | 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.88 | 1.00 | 0 |

Before this round, on sea_dev, three seller-side tricks were rated READY (ready to send to PayPal): a proof of
delivery for a different tracking number, a Rupiah invoice for a USD dispute, and an instruction hidden in Indonesian.
All three are now NEEDS_CHECK. The one holdout miss is on the safe side: a complete case was flagged for human review
because one model-written sentence failed claim verification and was dropped.

### What changed to get there

- Grounding reads Indonesian months (Okt, Agt, Mei, Des), decimal commas (USD 120,00), Rupiah (Rp 1.250.000),
  slashed order numbers and dates with a time.
- Courier statuses: Terkirim, Selesai antar and "diterima oleh" are delivered; "diterima di Gateway" (a warehouse scan)
  and negated statuses are not.
- A fact is accepted only from the document type that can prove it (`DOC_FIELDS`): a buyer chat or an "other" upload
  never proves delivery or payment.
- New rule: the proof of delivery must carry the same tracking number as the courier page.
- `LabelExtractor`: a deterministic reader for labelled lines, so what is plainly written is read the same way on every
  run instead of depending on the model.
- Documents reach the model as UTF-8 (`₱` was being sent as `₱`, so no quote ever matched).

### Rule version 3 (2026-10-30): the address PayPal checks, and the order of events

PayPal's proof of delivery for an item-not-received case must show the delivery address and match the address on
the transaction. SAL now copies city and postal code (never name or street) from PayPal's record and compares them
with where the courier delivered. A second rule requires ordered, then shipped, then delivered.

sea_dev with four new cases (D13 ZIP+4 of the ship-to ZIP, D14 delivered to another postcode, D15 a proof with no
address, D16 received before it was shipped), gpt-5-nano, 2026-10-30:

| Split | fact P | fact R | missing R/P | conflict R/P | review acc | ready acc | unsupported |
|---|---|---|---|---|---|---|---|
| sea_dev (16) | 1.00 | 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.94 | 1.00 | 0 |

All four new cases get the right readiness, with the deterministic reader alone as well. The review miss is a
complete case flagged for review in one run because a model-written sentence failed claim verification (the safe
side); a rerun of the complete cases flagged none. The holdout was not touched, so it is still unscored for rule
version 3.

### Unauthorized payments (2026-10-30)

An unauthorized-payment dispute is argued with the same evidence: PayPal's Seller Protection covers it when the
parcel provably went to the address on the transaction, so for this reason the address is required (missing when
PayPal's record has none) instead of skipped. D17 (delivered to the ship-to postal code) is READY and D18 (PayPal's
record has no ship-to) is NEEDS_DOCUMENTS, with the deterministic reader and with gpt-5-nano (all facts found, no
unsupported claims). So far this is tested on synthetic cases only. A sandbox buyer can open a real one (see
https://developer.paypal.com/disputes/test-go-live): expect `reason` UNAUTHORISED and stage CHARGEBACK.

## What these numbers do not prove

- The data is synthetic and small (50 cases in total), and the same author wrote the cases and the fixes.
- The holdout was scored once before a later fix (the carrier delivery-date label rule) and once after; the second run
  is not blind.
- Model output varies between runs. The label reader narrows this, it does not remove it. Treat a single run as one
  sample, not a guarantee.
- The next step for stronger evidence is a set of real, anonymised seller documents.
