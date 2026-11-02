-- Deal Check. Run as sal_migrator. Same tenant pattern as 0001/0009.
-- What was ordered and what was invoiced, as exact structured data, and each result of comparing them.
-- SAL writes nothing to PayPal from here: a HOLD lives only in SAL.

-- DealCategory: GOODS, DIGITAL, SERVICE
-- DealStatus: WAITING_INVOICE, CHECKING, HOLD, CLEAR
CREATE TABLE deals (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id       uuid NOT NULL REFERENCES merchants(id),
  deal_ref          text NOT NULL CHECK (char_length(deal_ref) BETWEEN 1 AND 64),
  category          text NOT NULL CHECK (category IN ('GOODS', 'DIGITAL', 'SERVICE')),
  status            text NOT NULL DEFAULT 'WAITING_INVOICE'
                    CHECK (status IN ('WAITING_INVOICE', 'CHECKING', 'HOLD', 'CLEAR')),
  purchase_order    jsonb NOT NULL,
  invoice           jsonb,
  invoice_revision  integer NOT NULL DEFAULT 0,   -- every invoice gets a new revision, so it is always checked
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, merchant_id),
  UNIQUE (merchant_id, deal_ref),
  CHECK ((invoice IS NULL) = (status = 'WAITING_INVOICE')),
  CHECK ((invoice IS NULL) = (invoice_revision = 0))
);

CREATE TABLE deal_checks (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id       uuid NOT NULL,
  deal_id           uuid NOT NULL,
  invoice_revision  integer NOT NULL,
  rule_version      text NOT NULL,
  status            text NOT NULL CHECK (status IN ('HOLD', 'CLEAR')),
  findings          jsonb NOT NULL,
  checked_at        timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (deal_id, merchant_id) REFERENCES deals (id, merchant_id),
  UNIQUE (deal_id, invoice_revision, rule_version)
);

ALTER TABLE deals       ENABLE ROW LEVEL SECURITY; ALTER TABLE deals       FORCE ROW LEVEL SECURITY;
ALTER TABLE deal_checks ENABLE ROW LEVEL SECURITY; ALTER TABLE deal_checks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON deals
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON deal_checks
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));

-- The API records what agents send and marks a deal CHECKING; only the worker reaches a verdict.
GRANT SELECT, INSERT ON deals TO sal_app;
GRANT UPDATE (invoice, invoice_revision, status, updated_at) ON deals TO sal_app;
GRANT SELECT ON deal_checks TO sal_app;
GRANT SELECT ON deals TO sal_worker;
GRANT UPDATE (status, updated_at) ON deals TO sal_worker;
GRANT SELECT, INSERT ON deal_checks TO sal_worker;
