-- SAL core schema with tenant isolation (SAL v1.0 §7, v1.1 §5–6).
-- Run as sal_migrator (table owner). Runtime roles sal_app / sal_worker are bound by RLS.

-- ---------------------------------------------------------------- helpers
-- Fail closed: if app.merchant_id is unset (or reset to '' after a pooled transaction),
-- the cast raises and the query errors instead of returning rows.
CREATE FUNCTION current_merchant_id() RETURNS uuid
LANGUAGE sql STABLE AS $$ SELECT current_setting('app.merchant_id')::uuid $$;

CREATE FUNCTION forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;

-- ---------------------------------------------------------------- tables
CREATE TABLE merchants (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE disputes (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id          uuid NOT NULL REFERENCES merchants(id),
  origin               text NOT NULL CHECK (origin IN ('PAYPAL_SANDBOX', 'SYNTHETIC_FIXTURE')),
  provider_dispute_id  text NOT NULL,
  case_ref             text,                       -- e.g. golden case id carried in PayPal `custom`
  reason               text NOT NULL,
  amount               numeric(19,4) NOT NULL CHECK (amount >= 0),
  currency             char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  provider_status      text NOT NULL,
  lifecycle_stage      text,
  internal_state       text NOT NULL DEFAULT 'NEW' CHECK (internal_state IN
                         ('NEW', 'COLLECTING_EVIDENCE', 'ANALYZING', 'NEEDS_REVIEW', 'APPROVED', 'FAILED')),
  deadline_at          timestamptz,                -- nullable: PayPal drops it after the seller responds
  allowed_actions      text[] NOT NULL DEFAULT '{}',  -- HATEOAS rels offered by PayPal at last sync
  provider_payload     jsonb,                      -- redacted snapshot of the last provider response
  provider_updated_at  timestamptz,
  version              integer NOT NULL DEFAULT 1, -- optimistic locking
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (merchant_id, provider_dispute_id),
  UNIQUE (id, merchant_id)                         -- target for composite FKs
);

CREATE TABLE evidence (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id  uuid NOT NULL,
  dispute_id   uuid NOT NULL,
  object_key   text NOT NULL,
  checksum     text NOT NULL,
  mime         text NOT NULL CHECK (mime IN ('application/pdf', 'image/jpeg', 'image/png', 'image/gif')),
  size_bytes   integer NOT NULL CHECK (size_bytes > 0 AND size_bytes < 10485760),  -- PayPal: < 10 MB/file
  uploaded_by  text NOT NULL,
  uploaded_at  timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (dispute_id, merchant_id) REFERENCES disputes (id, merchant_id),
  UNIQUE (dispute_id, checksum)                    -- duplicate upload detection
);

CREATE TABLE drafts (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id   uuid NOT NULL,
  dispute_id    uuid NOT NULL,
  revision      integer NOT NULL CHECK (revision > 0),
  body          text NOT NULL,
  payload_hash  text NOT NULL,
  status        text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'APPROVED', 'SUPERSEDED')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (dispute_id, merchant_id) REFERENCES disputes (id, merchant_id),
  UNIQUE (dispute_id, revision),
  UNIQUE (id, merchant_id)
);

CREATE TABLE approvals (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id    uuid NOT NULL,
  draft_id       uuid NOT NULL UNIQUE,             -- one approval per exact draft revision
  revision       integer NOT NULL,
  payload_hash   text NOT NULL,
  snapshot_hash  text NOT NULL,
  actor          text NOT NULL,
  approved_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (draft_id, merchant_id) REFERENCES drafts (id, merchant_id)
);

CREATE TABLE audit_logs (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  merchant_id  uuid NOT NULL REFERENCES merchants(id),
  actor        text NOT NULL,
  action       text NOT NULL,
  target       text,
  summary      jsonb NOT NULL DEFAULT '{}',
  occurred_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id      uuid NOT NULL REFERENCES merchants(id),
  kind             text NOT NULL,
  target_id        uuid,
  state            text NOT NULL DEFAULT 'QUEUED' CHECK (state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')),
  attempts         integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  max_attempts     integer NOT NULL DEFAULT 5,
  run_after        timestamptz NOT NULL DEFAULT now(),
  lease_until      timestamptz,
  idempotency_key  text NOT NULL UNIQUE,
  last_error       text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Webhooks arrive before the tenant is known; the worker resolves the merchant while processing.
CREATE TABLE webhook_events (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_event_id  text NOT NULL UNIQUE,         -- dedupe
  event_type         text NOT NULL,
  resource_id        text,
  payload            jsonb NOT NULL,
  received_at        timestamptz NOT NULL DEFAULT now(),
  processed_at       timestamptz
);

-- ---------------------------------------------------------------- indexes (led by merchant_id)
CREATE INDEX disputes_queue_idx    ON disputes (merchant_id, deadline_at NULLS LAST, id);
CREATE INDEX disputes_state_idx    ON disputes (merchant_id, internal_state);
CREATE INDEX evidence_dispute_idx  ON evidence (merchant_id, dispute_id);
CREATE INDEX drafts_dispute_idx    ON drafts (merchant_id, dispute_id, revision DESC);
CREATE INDEX audit_merchant_idx    ON audit_logs (merchant_id, occurred_at DESC);
CREATE INDEX jobs_claim_idx        ON jobs (run_after) WHERE state = 'QUEUED';
CREATE INDEX jobs_lease_idx        ON jobs (lease_until) WHERE state = 'RUNNING';
CREATE INDEX webhook_pending_idx   ON webhook_events (received_at) WHERE processed_at IS NULL;

-- ---------------------------------------------------------------- append-only audit
CREATE TRIGGER audit_logs_append_only
  BEFORE UPDATE OR DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ---------------------------------------------------------------- row-level security
-- `(SELECT current_merchant_id())` is evaluated once per query (initPlan), not once per row.
ALTER TABLE merchants  ENABLE ROW LEVEL SECURITY; ALTER TABLE merchants  FORCE ROW LEVEL SECURITY;
ALTER TABLE disputes   ENABLE ROW LEVEL SECURITY; ALTER TABLE disputes   FORCE ROW LEVEL SECURITY;
ALTER TABLE evidence   ENABLE ROW LEVEL SECURITY; ALTER TABLE evidence   FORCE ROW LEVEL SECURITY;
ALTER TABLE drafts     ENABLE ROW LEVEL SECURITY; ALTER TABLE drafts     FORCE ROW LEVEL SECURITY;
ALTER TABLE approvals  ENABLE ROW LEVEL SECURITY; ALTER TABLE approvals  FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY; ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs       ENABLE ROW LEVEL SECURITY; ALTER TABLE jobs       FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON merchants
  USING (id = (SELECT current_merchant_id())) WITH CHECK (id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON disputes
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON evidence
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON drafts
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON approvals
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY tenant_isolation ON audit_logs
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));

-- Jobs: the API enqueues within its tenant; the worker claims across tenants, then switches
-- into the job's tenant before touching business rows.
CREATE POLICY jobs_tenant ON jobs TO sal_app
  USING (merchant_id = (SELECT current_merchant_id())) WITH CHECK (merchant_id = (SELECT current_merchant_id()));
CREATE POLICY jobs_worker ON jobs TO sal_worker USING (true) WITH CHECK (true);

-- ---------------------------------------------------------------- grants (least privilege)
GRANT SELECT                         ON merchants TO sal_app, sal_worker;
GRANT SELECT, INSERT, UPDATE         ON disputes, evidence, drafts TO sal_app, sal_worker;
GRANT SELECT, INSERT                 ON approvals, audit_logs TO sal_app, sal_worker;  -- no UPDATE/DELETE
GRANT SELECT, INSERT                 ON jobs TO sal_app;
GRANT SELECT, INSERT, UPDATE         ON jobs TO sal_worker;
GRANT INSERT                         ON webhook_events TO sal_app;                     -- ingest only
GRANT SELECT, UPDATE (processed_at)  ON webhook_events TO sal_worker;
