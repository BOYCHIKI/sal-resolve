-- Evidence copilot (ADR-005). Run as sal_migrator.
-- Where a document came from: a merchant upload, PayPal's own API, or seeded practice data.
-- Only PAYPAL_API (or SEED, for practice cases) may prove a payment.
ALTER TABLE evidence ADD COLUMN origin text NOT NULL DEFAULT 'UPLOAD'
  CHECK (origin IN ('UPLOAD', 'PAYPAL_API', 'SEED'));
-- Documents fetched from PayPal are stored as text lines; there is no file behind them.
ALTER TABLE evidence ALTER COLUMN object_key DROP NOT NULL;
-- Mark existing seeded documents. FORCE RLS would hide every row from the owner here, so lift it only inside
-- this migration's transaction (same pattern as 0003).
ALTER TABLE evidence NO FORCE ROW LEVEL SECURITY;
UPDATE evidence SET origin = 'SEED' WHERE uploaded_by = 'seed';
ALTER TABLE evidence FORCE ROW LEVEL SECURITY;
-- The ASSESS result: propositions, readiness, next action. NULL for analyses made before ADR-005.
ALTER TABLE analyses ADD COLUMN assessment jsonb;
