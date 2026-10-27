-- Indexes for queries the API runs on every case page. Run as sal_migrator.
-- The case page loads the newest draft of the newest analysis (main.py get_analysis); drafts had no index
-- on analysis_id, so that lookup scanned the merchant's drafts.
CREATE INDEX drafts_analysis_idx ON drafts (merchant_id, analysis_id, revision DESC);
-- /api/ops counts recent failures per merchant; jobs had only claim/lease indexes.
CREATE INDEX jobs_failed_recent_idx ON jobs (merchant_id, updated_at DESC) WHERE state = 'FAILED';
