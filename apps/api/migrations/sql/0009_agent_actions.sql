-- Agent action proposals (ADR-006). Run as sal_migrator. Same tenant pattern as 0001/0003.
-- The worker proposes; the merchant approves or dismisses; only SEND_EVIDENCE writes to PayPal, and it does so
-- through the existing submission path (ADR-003).

CREATE TABLE agent_actions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id   uuid NOT NULL,
  dispute_id    uuid,
  kind          text NOT NULL CHECK (kind IN ('SEND_EVIDENCE', 'ADD_DOCUMENT', 'REPLY_BEFORE_DEADLINE',
                                              'EXPLAIN_HELD_FUNDS')),
  status        text NOT NULL DEFAULT 'PROPOSED' CHECK (status IN ('PROPOSED', 'APPROVED', 'DONE', 'FAILED',
                                                                    'DISMISSED', 'SUPERSEDED')),
  subject_key   text NOT NULL,                 -- what the card is about: dispute:<uuid> | hold:<transaction id>
  title         text NOT NULL,
  rationale     text NOT NULL,
  sources       jsonb NOT NULL DEFAULT '[]',   -- evidence line refs or PayPal transaction ids the card rests on
  payload       jsonb NOT NULL DEFAULT '{}',   -- exactly what approval would act on
  payload_hash  text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  due_at        timestamptz,                   -- PayPal's deadline, when there is one
  created_at    timestamptz NOT NULL DEFAULT now(),
  decided_by    text,
  decided_at    timestamptz,
  result        jsonb,
  FOREIGN KEY (dispute_id, merchant_id) REFERENCES disputes (id, merchant_id)
);
-- One open card per subject and kind: a newer proposal supersedes the old one instead of piling up.
CREATE UNIQUE INDEX agent_actions_open_idx ON agent_actions (merchant_id, subject_key, kind) WHERE status = 'PROPOSED';
CREATE INDEX agent_actions_inbox_idx ON agent_actions (merchant_id, status, due_at);
CREATE INDEX agent_actions_dispute_idx ON agent_actions (merchant_id, dispute_id);

ALTER TABLE agent_actions ENABLE ROW LEVEL SECURITY; ALTER TABLE agent_actions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON agent_actions
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));

-- The API records the merchant's decision and the outcome; it never proposes or rewrites a card.
GRANT SELECT ON agent_actions TO sal_app;
GRANT UPDATE (status, decided_by, decided_at, result) ON agent_actions TO sal_app;
GRANT SELECT, INSERT, UPDATE ON agent_actions TO sal_worker;

-- Grants cannot restrict values: the API may only move a card to a decision, never back to PROPOSED.
CREATE FUNCTION agent_actions_app_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF current_user = 'sal_app' AND NEW.status NOT IN ('APPROVED', 'DONE', 'FAILED', 'DISMISSED') THEN
    RAISE EXCEPTION 'the API cannot set an action to %', NEW.status USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER agent_actions_app_guard BEFORE UPDATE ON agent_actions
  FOR EACH ROW EXECUTE FUNCTION agent_actions_app_guard();
