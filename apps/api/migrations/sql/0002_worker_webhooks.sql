-- Worker + webhook support. Run as sal_migrator.

-- Maps a PayPal seller account to a SAL merchant. Webhooks arrive without tenant context, so the
-- worker resolves the merchant here. No RLS: it holds no business data, and only the worker
-- (and the migrator, for onboarding) can read it — the API role has no access at all.
CREATE TABLE paypal_connections (
  merchant_id         uuid NOT NULL REFERENCES merchants(id),
  paypal_merchant_id  text NOT NULL UNIQUE,
  environment         text NOT NULL DEFAULT 'sandbox' CHECK (environment IN ('sandbox')),
  created_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (merchant_id, paypal_merchant_id)
);
GRANT SELECT ON paypal_connections TO sal_worker;

-- Why a webhook could not be routed (unknown seller, malformed payload). Kept for operators.
ALTER TABLE webhook_events ADD COLUMN error text;

-- Jobs carry small typed inputs (payload) and keep a small result for GET /api/jobs/{id}.
ALTER TABLE jobs ADD COLUMN payload jsonb NOT NULL DEFAULT '{}';
ALTER TABLE jobs ADD COLUMN result jsonb;

-- ON CONFLICT ... RETURNING needs SELECT on the arbiter and returned columns; nothing else.
GRANT SELECT (id, provider_event_id) ON webhook_events TO sal_app;
GRANT UPDATE (error) ON webhook_events TO sal_worker;
