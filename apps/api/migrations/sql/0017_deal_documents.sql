-- PO and invoice files. Run as sal_migrator. Same tenant pattern as 0001/0009.
-- The worker reads a file into a proposal; a deal or invoice exists only after a person confirms it.

-- DocumentKind: PURCHASE_ORDER, INVOICE
-- DocumentStatus: READING, NEEDS_CONFIRMATION, UNREADABLE, CONFIRMED, DISCARDED
CREATE TABLE deal_documents (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id  uuid NOT NULL REFERENCES merchants(id),
  kind         text NOT NULL CHECK (kind IN ('PURCHASE_ORDER', 'INVOICE')),
  deal_ref     text CHECK (char_length(deal_ref) BETWEEN 1 AND 64),   -- the deal an invoice belongs to
  status       text NOT NULL DEFAULT 'READING'
               CHECK (status IN ('READING', 'NEEDS_CONFIRMATION', 'UNREADABLE', 'CONFIRMED', 'DISCARDED')),
  object_key   text NOT NULL,
  mime         text NOT NULL CHECK (mime IN ('application/pdf', 'image/jpeg', 'image/png', 'image/gif')),
  sha256       text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  lines        jsonb,      -- the page as numbered lines, so the seller can compare
  proposal     jsonb,      -- only values proven on their cited line
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (kind = 'PURCHASE_ORDER' OR deal_ref IS NOT NULL)
);
CREATE INDEX deal_documents_recent_idx ON deal_documents (merchant_id, created_at DESC);

ALTER TABLE deal_documents ENABLE ROW LEVEL SECURITY; ALTER TABLE deal_documents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON deal_documents
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));

GRANT SELECT, INSERT ON deal_documents TO sal_app;
GRANT UPDATE (status) ON deal_documents TO sal_app;
GRANT SELECT ON deal_documents TO sal_worker;
GRANT UPDATE (status, lines, proposal) ON deal_documents TO sal_worker;
