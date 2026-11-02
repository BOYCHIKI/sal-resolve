-- REVIEW_DEAL_HOLD card: Deal Check found a difference, so the seller's main page says so.
ALTER TABLE agent_actions DROP CONSTRAINT agent_actions_kind_check;
ALTER TABLE agent_actions ADD CONSTRAINT agent_actions_kind_check
  CHECK (kind IN ('SEND_EVIDENCE', 'ADD_DOCUMENT', 'REPLY_BEFORE_DEADLINE', 'EXPLAIN_HELD_FUNDS', 'EXPLAIN_DISPUTE',
                  'OFFER_REFUND', 'REVIEW_DEAL_HOLD')) NOT VALID;
