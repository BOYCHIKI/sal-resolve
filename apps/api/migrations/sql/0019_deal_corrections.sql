-- A seller's request to correct a held deal, one per invoice revision. It stays in SAL: the seller passes the
-- message on, and the deal's agents read it. Same tenant pattern as 0001/0009.
CREATE TABLE deal_corrections (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id       uuid NOT NULL,
  deal_id           uuid NOT NULL,
  invoice_revision  integer NOT NULL,
  message           text NOT NULL CHECK (char_length(message) BETWEEN 1 AND 4000),
  requested_by      text NOT NULL,
  requested_at      timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (deal_id, merchant_id) REFERENCES deals (id, merchant_id),
  UNIQUE (deal_id, invoice_revision)
);

ALTER TABLE deal_corrections ENABLE ROW LEVEL SECURITY; ALTER TABLE deal_corrections FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON deal_corrections
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));

GRANT SELECT, INSERT ON deal_corrections TO sal_app;
