-- Submission states. Run as sal_migrator.
-- SUBMITTING is a short-lived lock taken atomically before the PayPal call, so a double click
-- or a retry can never send the same evidence twice.
ALTER TABLE drafts DROP CONSTRAINT drafts_status_check;
ALTER TABLE drafts ADD CONSTRAINT drafts_status_check
  CHECK (status IN ('DRAFT', 'APPROVED', 'SUPERSEDED', 'SUBMITTING', 'SUBMITTED', 'SUBMIT_FAILED'));

ALTER TABLE disputes DROP CONSTRAINT disputes_internal_state_check;
ALTER TABLE disputes ADD CONSTRAINT disputes_internal_state_check
  CHECK (internal_state IN ('NEW', 'COLLECTING_EVIDENCE', 'ANALYZING', 'NEEDS_REVIEW', 'APPROVED', 'SUBMITTED', 'FAILED'));
