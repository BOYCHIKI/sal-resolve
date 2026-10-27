-- Tracking numbers the seller types in (a claim, not proof: it names the parcel, it never shows it moved), and the
-- EXPLAIN_DISPUTE card for disputes SAL does not argue (e.g. "not as described").
ALTER TABLE evidence DROP CONSTRAINT evidence_origin_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_origin_check
  CHECK (origin IN ('UPLOAD', 'PAYPAL_API', 'SEED', 'SELLER_INPUT'));

ALTER TABLE evidence DROP CONSTRAINT evidence_mime_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_mime_check
  CHECK (mime IN ('application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'text/plain'));

ALTER TABLE agent_actions DROP CONSTRAINT agent_actions_kind_check;
ALTER TABLE agent_actions ADD CONSTRAINT agent_actions_kind_check
  CHECK (kind IN ('SEND_EVIDENCE', 'ADD_DOCUMENT', 'REPLY_BEFORE_DEADLINE', 'EXPLAIN_HELD_FUNDS', 'EXPLAIN_DISPUTE'));
