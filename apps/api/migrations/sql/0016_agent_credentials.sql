-- Agent identity. Run as sal_migrator. Same tenant pattern as 0001/0009.
-- Each agent has its own credential. Only a SHA-256 of the token is stored: the token is shown once, at issue.
-- The token names its merchant, so looking it up needs no cross-tenant access and RLS stays in force.

-- AgentRole: BUYER_AGENT, SELLER_AGENT
CREATE TABLE agent_credentials (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id  uuid NOT NULL REFERENCES merchants(id),
  name         text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
  role         text NOT NULL CHECK (role IN ('BUYER_AGENT', 'SELLER_AGENT')),
  token_hash   text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL DEFAULT now() + interval '90 days',
  revoked_at   timestamptz,
  UNIQUE (id, merchant_id)
);

ALTER TABLE agent_credentials ENABLE ROW LEVEL SECURITY; ALTER TABLE agent_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON agent_credentials
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));

GRANT SELECT, INSERT ON agent_credentials TO sal_app;
GRANT UPDATE (revoked_at, expires_at) ON agent_credentials TO sal_app;

-- Which verified agent sent each side of a deal. NULL on deals made before this migration.
-- NOT VALID: every existing row is NULL, and checking them would run RLS with no tenant set. New rows are enforced.
ALTER TABLE deals ADD COLUMN ordered_by uuid, ADD COLUMN invoiced_by uuid,
  ADD FOREIGN KEY (ordered_by, merchant_id) REFERENCES agent_credentials (id, merchant_id) NOT VALID,
  ADD FOREIGN KEY (invoiced_by, merchant_id) REFERENCES agent_credentials (id, merchant_id) NOT VALID;
GRANT UPDATE (invoiced_by) ON deals TO sal_app;
