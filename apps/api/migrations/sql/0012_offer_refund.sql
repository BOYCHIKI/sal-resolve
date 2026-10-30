-- OFFER_REFUND card: for a "not as described" case PayPal lets the seller offer a refund. The seller types the
-- amount; SAL sends the offer through PayPal's make-offer only after they approve.
ALTER TABLE agent_actions DROP CONSTRAINT agent_actions_kind_check;
ALTER TABLE agent_actions ADD CONSTRAINT agent_actions_kind_check
  CHECK (kind IN ('SEND_EVIDENCE', 'ADD_DOCUMENT', 'REPLY_BEFORE_DEADLINE', 'EXPLAIN_HELD_FUNDS', 'EXPLAIN_DISPUTE',
                  'OFFER_REFUND'));
