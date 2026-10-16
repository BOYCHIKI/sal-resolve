-- Operations (2026-10-15). Run as sal_migrator.
-- Upload checks "is an analysis already queued for this dispute?" on every file; keep that lookup indexed.
CREATE INDEX jobs_queued_target_idx ON jobs (target_id, kind) WHERE state = 'QUEUED';

-- Worker liveness for /api/health. Holds no tenant data, so no row-level security.
CREATE TABLE worker_heartbeats (
  worker_id  text PRIMARY KEY,
  seen_at    timestamptz NOT NULL DEFAULT now(),
  jobs_done  bigint NOT NULL DEFAULT 0
);
GRANT SELECT ON worker_heartbeats TO sal_app;
GRANT SELECT, INSERT, UPDATE ON worker_heartbeats TO sal_worker;

-- OpenAI usage per agent run, so cost is visible (ADR-004 budget).
ALTER TABLE agent_runs ADD COLUMN llm_input_tokens integer;
ALTER TABLE agent_runs ADD COLUMN llm_output_tokens integer;
