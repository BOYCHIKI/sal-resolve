-- Packing proof vault (ADR-007). Run as sal_migrator. Same tenant pattern as 0001/0009.
-- The seller records the parcel before shipping (photos or a short video); SAL keeps the files with their SHA-256
-- and the server time, and issues a random code for the QR label. The worker later attaches a matching record to a
-- dispute as the seller's evidence. It never proves delivery.

CREATE TABLE packing_proofs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id      uuid NOT NULL REFERENCES merchants(id),
  code             text NOT NULL UNIQUE CHECK (code ~ '^[A-Z2-7]{26}$'),   -- 128 random bits, base32, on the QR
  order_ref        text CHECK (char_length(order_ref) BETWEEN 1 AND 64),
  transaction_id   text CHECK (transaction_id ~ '^[A-Z0-9]{17}$'),          -- PayPal transaction id
  tracking_number  text CHECK (tracking_number ~ '^[A-Z0-9-]{6,40}$'),
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL DEFAULT now() + interval '180 days', -- PayPal's dispute window
  UNIQUE (id, merchant_id),
  CHECK (order_ref IS NOT NULL OR transaction_id IS NOT NULL OR tracking_number IS NOT NULL)
);
CREATE INDEX packing_proofs_match_idx ON packing_proofs (merchant_id, transaction_id, tracking_number, order_ref);

CREATE TABLE packing_files (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id  uuid NOT NULL,
  packing_id   uuid NOT NULL,
  object_key   text NOT NULL,
  mime         text NOT NULL CHECK (mime IN ('image/jpeg', 'image/png', 'image/gif', 'video/mp4', 'video/quicktime',
                                             'video/webm')),
  sha256       text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes   integer NOT NULL CHECK (size_bytes > 0 AND size_bytes < 52428800),   -- < 50 MB
  created_at   timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (packing_id, merchant_id) REFERENCES packing_proofs (id, merchant_id) ON DELETE CASCADE,
  UNIQUE (packing_id, sha256)
);

ALTER TABLE packing_proofs ENABLE ROW LEVEL SECURITY; ALTER TABLE packing_proofs FORCE ROW LEVEL SECURITY;
ALTER TABLE packing_files  ENABLE ROW LEVEL SECURITY; ALTER TABLE packing_files  FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON packing_proofs
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON packing_files
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));

-- The API records parcels and files (append-only for it: no UPDATE, no DELETE); the worker reads them to match
-- disputes and deletes them after the retention period.
GRANT SELECT, INSERT ON packing_proofs, packing_files TO sal_app;
GRANT SELECT, DELETE ON packing_proofs, packing_files TO sal_worker;
