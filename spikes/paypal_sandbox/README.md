# PayPal Sandbox spike (gate G1)

Goal: prove SAL can read, move and answer an Item-Not-Received dispute in the PayPal **sandbox**,
record the real payloads as contract fixtures, and confirm the golden-dataset ↔ PayPal mapping.

Sandbox only — the base URL is hard-coded to `api-m.sandbox.paypal.com` and live URLs are refused.
Only `development` cases from the golden dataset can be seeded; calibration/holdout are refused.

## Setup (you do this, by hand)

1. developer.paypal.com → Apps & Credentials → **Sandbox** → create a REST app.
2. Sandbox accounts: one **Business** (seller, owner of the app) and one **Personal** (buyer) with a card.
3. `copy .env.example .env` and fill `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_SANDBOX_BUYER_EMAIL`.
4. `pip install -r requirements.txt`

## Steps

| Step | Command | Pass when |
|---|---|---|
| S1 | `python spike.py s1` | OAuth token obtained |
| S2 | `python spike.py s2-order --case SAL-INR-001` → approve as buyer → `python spike.py s2-capture` | Capture id printed |
| S3 | `python spike.py s3 --buyer-txn <buyer-side txn id>` | `201`, dispute id saved |
| S3 fallback | open INR dispute in the buyer's sandbox Resolution Center → `python spike.py s3-manual --dispute-id <id>` | Linked |
| S4 | `python spike.py s4` | Payload recorded, golden sync check `OK` |
| S5 | `python spike.py s5 --action SELLER_EVIDENCE --yes` | Status `WAITING_FOR_SELLER_RESPONSE` |
| S6 | `python spike.py s6 --yes` | Evidence (PDFs + tracking) accepted |
| S7 | `python webhook.py` + tunnel + register webhook | Signed events `ACCEPT`, duplicates ignored |
| S8 | `python spike.py s8 --outcome SELLER_FAVOR --yes` | Status `RESOLVED` |

Wait a few minutes after S3 before S5/S6. `s5` and `s8` need status `UNDER_REVIEW` and the matching
HATEOAS link — `s4` prints the available links.

## Known unknowns (what this spike is for)

- **Create-dispute is limited release** and buyer-scoped; it may return 401/403 without the scope.
  That is a valid G1 finding — use the S3 fallback.
  **Finding 2026-10-12:** the app *has* the `disputes/create` scope, but `POST /v1/customer/disputes` with the
  unsigned `PayPal-Auth-Assertion` returns `400 invalid_request: No permissions to set target_client_id`
  (acting on behalf of the buyer needs partner/third-party permission). Use the S3 fallback.
- `PayPal-Auth-Assertion` is built as an unsigned JWT `{iss: client_id, email: buyer}`; not formally documented.
- S3 needs the **buyer-side** transaction id, which differs from the seller capture id.
- Multipart file part name for provide-evidence defaults to `evidence-file` (`--file-field` to change).
- Evidence-type mapping in `mapping.py` is a hypothesis until S6 passes.

## Outputs

- `../../contracts/paypal/*.json` — redacted request/response fixtures (tokens and emails stripped).
- `../../contracts/sandbox_links.csv` — `case_id ↔ sandbox_dispute_id`.
- `.spike_state.json` — local progress (git-ignored).

## Offline tests

`python -m unittest discover -s tests` — mapping, guards (holdout/live URL refused), redaction, PDF, assertion.
