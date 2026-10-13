# SAL Resolve

AI-assisted payment-dispute operations copilot for PayPal merchants (PayPal AI Hackathon, submission due 12 Nov 2026 12:00 PT).
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

## How the golden splits are used

| Split | Cases | Use in MVP |
|---|---|---|
| `development` | 24 | Pipeline iteration and the only split that may be seeded into the PayPal Sandbox. |
| `calibration` | 8 | **Not used in MVP** — SAL v1.1 (D5) keeps C/P scores as uncalibrated demo constants. Kept intact for post-hackathon threshold tuning. Offline only. |
| `holdout` | 8 | Final evaluation only, after rules are frozen. Offline only. |

## Quick start

```
docker compose up -d --wait                       # Postgres
cd apps/api && pip install -r requirements.txt && copy .env.example .env
alembic upgrade head && python -m app.seed_demo   # put the printed id in SAL_DEMO_MERCHANT_ID
uvicorn app.main:app --port 8000                  # API
python -m app.worker                              # worker (second terminal)
cd apps/web && npm install && npm run dev         # UI on http://localhost:3000
```

Note: `pytest` in `apps/api` resets the local database schema, which removes seeded demo data.

## License

MIT — see [LICENSE](LICENSE). The golden dataset in `data/golden/` is synthetic test data; it contains no real PayPal customer data.
