-- Submission safety (ADR-003). Run as sal_migrator.
-- approvals.evidence_hash: the exact set of documents the operator approved; submit refuses if it changed.
ALTER TABLE approvals ADD COLUMN evidence_hash text;
-- When the PayPal call started (bounds the reconciliation check) and why a send ended where it did
-- (e.g. NEEDS_MANUAL_CHECK). Tables keep their existing grants.
ALTER TABLE drafts ADD COLUMN submit_started_at timestamptz;
ALTER TABLE drafts ADD COLUMN submit_note text;
