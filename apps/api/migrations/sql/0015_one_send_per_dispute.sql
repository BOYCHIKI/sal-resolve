-- At most one send to PayPal per dispute at a time, whichever draft it comes from. A newer draft waits until the
-- open send is settled, because that send may already have reached PayPal.
CREATE UNIQUE INDEX drafts_one_send_per_dispute ON drafts (dispute_id) WHERE status = 'SUBMITTING';
