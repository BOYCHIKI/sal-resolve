# SAL Resolve

**The evidence copilot for PayPal disputes.** Evidence intelligence for merchants: know what your documents prove
before you reply. SAL reads your documents and PayPal's own transaction record, shows what they prove and what's missing,
and drafts a reply only from verified facts. You decide. (PayPal AI Hackathon, submission due 12 Nov 2026 12:00 PT;
positioning in [ADR-005](docs/adr/ADR-005-evidence-copilot.md).)
Design docs live in Notion: SAL v1.0 Final Blueprint and SAL v1.1 System Design.

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

## License

MIT — see [LICENSE](LICENSE). The golden dataset in `data/golden/` is synthetic test data; it contains no real PayPal customer data.
