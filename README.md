# SAL Resolve

**The evidence copilot for PayPal disputes.** Evidence intelligence for merchants: know what your documents prove
before you reply. SAL reads your documents and PayPal's own transaction record, shows what they prove and what's missing,
and drafts a reply only from verified facts. You decide. (PayPal AI Hackathon, submission due 12 Nov 2026 12:00 PT;
positioning in [ADR-005](docs/adr/ADR-005-evidence-copilot.md).)
Design docs live in Notion: SAL v1.0 Final Blueprint and SAL v1.1 System Design.

## How the agent works

![The SAL agent: three triggers feed the worker, a read-only agent checks the evidence and proposes cards, and only an approved "Send evidence" card reaches PayPal](docs/images/sal-agent-flow.svg)

- **Runs on its own.** Every `SAL_WATCH_MINUTES` (default 10) the worker syncs PayPal disputes, scans held funds and
  refreshes every open case's suggestion cards. A new document, a typed tracking number or a PayPal change starts a
  fresh analysis.
- **Only reads.** The agent reads documents (a deterministic label reader plus the LLM), keeps a fact only if its value
  is written on the quoted line of a document type that can prove it, runs the rules (tracking numbers, dates,
  currencies, hidden instructions) and rates the case: ready, missing documents, or needs a check.
- **Stops at one gate.** Nothing reaches PayPal until the seller approves the exact card they read. Only the
  "Send evidence" card writes to PayPal, at most once; the other cards (missing document, deadline, money on hold,
  not a delivery case) only inform. Details: [ADR-006](docs/adr/ADR-006-agent-action-proposals.md).

## Layout

| Path | What | Rule |
|---|---|---|
| `data/golden/v1.0.0/` | Golden evaluation dataset (40 synthetic INR cases) | **Frozen.** Never edit in place; changes go to `data/golden/v1.1.0/`. Integrity is checked by `CHECKSUMS.sha256` and a test. |
| `apps/web/` | Next.js UI: dispute queue and Case Workspace | Talks to the API server-side only. |
| `apps/api/` | FastAPI backend, PostgreSQL schema with row-level security, tenant-scoped queries | See its README for the permission model. |
| `spikes/paypal_sandbox/` | Gate G1 spike: PayPal Sandbox Disputes API | Sandbox only. See its README. |
| `contracts/paypal/` | Recorded, redacted sandbox payloads + `sandbox_links.csv` | Source of truth for the PayPal adapter's contract tests. |
| `docs/adr/` | Architecture decision records | |
| `docs/engineering-glossary.md` | How SAL maps to standard engineering patterns, with the code for each | Built vs planned is marked per row. |

## How the golden splits are used

| Split | Cases | Use in MVP |
|---|---|---|
| `development` | 24 | Pipeline iteration and the only split that may be seeded into the PayPal Sandbox. |
| `calibration` | 8 | **Not used in MVP** — SAL v1.1 (D5) keeps C/P scores as uncalibrated demo constants. Kept intact for post-hackathon threshold tuning. Offline only. |
| `holdout` | 8 | Final evaluation only, after rules are frozen. Offline only. |
| `real_format` (v1.1.0) | 6 | Realistic layouts: dates in words, symbols, e-mails, scans, an injected instruction. |
| `sea_dev` (v1.2.0) | 12 | Indonesian and Philippine sellers: JNE, J&T, SiCepat, Pos Indonesia, LBC, Ninja Van, Rupiah, WhatsApp chats, traps. |
| `sea_holdout` (v1.2.0) | 8 | Same families, different documents; scored only with `--final`. |

Latest scores and what they do not prove: [docs/testing/agent-evaluation.md](docs/testing/agent-evaluation.md).

## Quick start

Shortcuts (Windows, needs Docker Desktop, Python 3.12+, Node 20+):

```
.\sal setup     # first time: venv, packages, .env, database, demo cases
.\sal start     # database + API + worker + web, opens http://localhost:3000
.\sal backend   # database + API + worker only (docs: http://127.0.0.1:8000/docs)
.\sal web       # web only (needs the backend)
.\sal stop      # stop API, worker and web
.\sal status    # what is running
.\sal seed      # add demo cases again
.\sal test      # backend tests (separate sal_test database)
.\sal eval --split real_format --roles llm   # score the agent (LLM needs SAL_LLM_* in apps/api/.env)
```

If PowerShell blocks scripts, use `.\sal.cmd start` (same commands). By hand:

```
docker compose up -d --wait                       # Postgres
cd apps/api && pip install -r requirements.lock && copy .env.example .env
alembic upgrade head && python -m app.seed_demo   # put the printed id in SAL_DEMO_MERCHANT_ID
uvicorn app.main:app --port 8000                  # API
python -m app.worker                              # worker (second terminal)
cd apps/web && npm install && npm run dev         # UI on http://localhost:3000
```

Tests run on their own database (`sal_test`) and leave the demo data in `sal` alone.

## Test it locally

Everything below runs on your machine with practice cases; nothing is sent to PayPal. Start with `.\sal setup` once,
then `.\sal start`.

| # | Do | You should see |
|---|---|---|
| 1 | Open http://localhost:3000/disputes | "What SAL found": a one-line summary, **Needs you** cards, your PayPal cases, practice cases folded away |
| 2 | Open **Practice cases**, then a case marked *Missing 1 document* | An **Add courier tracking** card with the deadline, and what the documents prove so far |
| 3 | On a complete practice case, type a tracking number that differs from the courier page (e.g. `JP8812345678`, courier `JNE`) under **Add the tracking number** | After the re-check (about 30 s with the LLM): the case turns to *needs a check*, both tracking numbers are marked as conflicting, and no send card appears |
| 4 | Under **Add a document**, upload a PDF courier page or delivery receipt | A fresh analysis; the card updates or closes on its own |
| 5 | Leave the worker running for 10 minutes (or set `SAL_WATCH_MINUTES=1` in `apps/api/.env` and restart) | `jobs` gets `sync_disputes`, `scan_holds` and `refresh_actions` rounds; with PayPal Sandbox keys, held money shows under **Money on hold** |
| 6 | `.\sal test` | All backend tests pass (PayPal and the LLM are faked) |
| 7 | `.\sal eval --split sea_dev --roles llm` | The agent's scores on Indonesian and Philippine documents (needs `SAL_LLM_*` in `apps/api/.env`) |

There is no delete button for a typed tracking number yet, and `.\sal seed` skips cases that already exist. To start
over with clean practice cases, recreate the local database: `.\sal stop`, `docker compose down -v`, then
`.\sal setup`. Sending to PayPal (the **Send evidence** card) works only on PayPal Sandbox cases where
PayPal still accepts evidence; practice cases can be checked and approved but never sent.

## License

MIT — see [LICENSE](LICENSE). The golden dataset in `data/golden/` is synthetic test data; it contains no real PayPal customer data.
