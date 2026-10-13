-- Agent persistence (SAL v1.0 §7, v1.1 §5.1). Run as sal_migrator. Same tenant pattern as 0001.

-- Parsed evidence text, as untrusted data with line numbers. Filled by the parser/upload path.
ALTER TABLE evidence ADD COLUMN doc_type text;
ALTER TABLE evidence ADD COLUMN content_lines jsonb;
ALTER TABLE evidence ADD COLUMN source_ref text;      -- e.g. golden evidence_id for seeded demo docs

CREATE TABLE agent_runs (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id  uuid NOT NULL,
  dispute_id   uuid NOT NULL,
  job_id       uuid,
  roles        text NOT NULL,                  -- which planner/extractor/drafter (model + version)
  status       text NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
  steps        integer NOT NULL DEFAULT 0,
  error        text,
  started_at   timestamptz NOT NULL DEFAULT now(),
  ended_at     timestamptz,
  FOREIGN KEY (dispute_id, merchant_id) REFERENCES disputes (id, merchant_id),
  UNIQUE (id, merchant_id)
);

CREATE TABLE tool_calls (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  merchant_id   uuid NOT NULL,
  agent_run_id  uuid NOT NULL,
  step          integer NOT NULL,
  tool          text NOT NULL,
  args          jsonb NOT NULL DEFAULT '{}',
  ok            boolean NOT NULL,
  summary       text NOT NULL,
  at            timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (agent_run_id, merchant_id) REFERENCES agent_runs (id, merchant_id)
);

CREATE TABLE analyses (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id      uuid NOT NULL,
  dispute_id       uuid NOT NULL,
  agent_run_id     uuid NOT NULL,
  dispute_version  integer NOT NULL,           -- the dispute version this analysis was made from
  rule_version     text NOT NULL,
  facts            jsonb NOT NULL,
  findings         jsonb NOT NULL,
  review_required  boolean NOT NULL,
  snapshot_hash    text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (dispute_id, merchant_id) REFERENCES disputes (id, merchant_id),
  FOREIGN KEY (agent_run_id, merchant_id) REFERENCES agent_runs (id, merchant_id),
  UNIQUE (id, merchant_id)
);

ALTER TABLE drafts ADD COLUMN analysis_id uuid;
ALTER TABLE drafts ADD COLUMN claims jsonb NOT NULL DEFAULT '[]';
-- FK validation scans existing rows as the owner; under FORCE RLS that scan would be tenant-filtered
-- (and error without a tenant). Lift FORCE only inside this migration transaction so every row is checked.
ALTER TABLE drafts NO FORCE ROW LEVEL SECURITY;
ALTER TABLE drafts ADD CONSTRAINT drafts_analysis_fk
  FOREIGN KEY (analysis_id, merchant_id) REFERENCES analyses (id, merchant_id);
ALTER TABLE drafts FORCE ROW LEVEL SECURITY;

CREATE INDEX agent_runs_dispute_idx ON agent_runs (merchant_id, dispute_id, started_at DESC);
CREATE INDEX tool_calls_run_idx     ON tool_calls (merchant_id, agent_run_id, step);
CREATE INDEX analyses_dispute_idx   ON analyses (merchant_id, dispute_id, created_at DESC);

CREATE TRIGGER tool_calls_append_only
  BEFORE UPDATE OR DELETE ON tool_calls FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER analyses_append_only
  BEFORE UPDATE OR DELETE ON analyses FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY; ALTER TABLE agent_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE tool_calls ENABLE ROW LEVEL SECURITY; ALTER TABLE tool_calls FORCE ROW LEVEL SECURITY;
ALTER TABLE analyses   ENABLE ROW LEVEL SECURITY; ALTER TABLE analyses   FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON agent_runs
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON tool_calls
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON analyses
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));

-- The API reads agent output; only the worker writes it. Snapshots and tool calls are append-only.
GRANT SELECT                 ON agent_runs, tool_calls, analyses TO sal_app;
GRANT SELECT, INSERT, UPDATE ON agent_runs TO sal_worker;
GRANT SELECT, INSERT         ON tool_calls, analyses TO sal_worker;
