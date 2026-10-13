# SAL web (Next.js)

Two pages: `/disputes` (queue + Sync PayPal) and `/disputes/[id]` (Case Workspace: evidence with line
numbers, gaps and conflicts, facts with source links, draft, PayPal actions, agent trail).

The browser never calls the API directly: pages fetch it server-side (`lib/api.ts`), and the Sync button
uses server actions. Set `SAL_API_URL` if the API is not on `http://127.0.0.1:8000`.

```
npm install
npm run dev        # http://localhost:3000
```

Needs the API (`apps/api`) running with `SAL_DEMO_MERCHANT_ID` set; `python -m app.seed_demo` fills demo cases.
