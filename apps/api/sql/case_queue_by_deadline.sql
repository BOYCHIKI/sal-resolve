-- Case queue by deadline: every dispute the merchant still has to act on, most urgent first.
-- PostgreSQL 16. Run as sal_app inside one transaction so row-level security scopes it to one merchant:
--   BEGIN;
--   SELECT set_config('app.merchant_id', '<merchant-uuid>', true);
--   \i apps/api/sql/case_queue_by_deadline.sql
--   COMMIT;
-- Without the set_config line the query fails (fail-closed RLS), it never returns another merchant's cases.

WITH latest_analysis AS (
    -- Only the newest analysis per dispute counts; older ones are history.
    SELECT DISTINCT ON (a.dispute_id)
           a.dispute_id,
           a.assessment ->> 'readiness'   AS readiness,
           a.assessment ->> 'next_action' AS next_action,
           a.findings,
           a.assessment -> 'propositions' AS propositions,
           a.created_at                   AS analyzed_at
    FROM analyses a
    ORDER BY a.dispute_id, a.created_at DESC
),
latest_draft AS (
    SELECT DISTINCT ON (dr.dispute_id)
           dr.dispute_id,
           dr.status      AS draft_status,
           dr.submit_note
    FROM drafts dr
    ORDER BY dr.dispute_id, dr.revision DESC
),
evidence_count AS (
    SELECT e.dispute_id, count(*) AS documents
    FROM evidence e
    GROUP BY e.dispute_id
),
open_cases AS (
    -- Open = PayPal has not resolved it and SAL has not sent (or is not sending) the reply.
    SELECT d.id, d.provider_dispute_id, d.origin, d.reason, d.amount, d.currency,
           d.provider_status, d.internal_state, d.deadline_at
    FROM disputes d
    LEFT JOIN latest_draft ld ON ld.dispute_id = d.id
    WHERE d.provider_status <> 'RESOLVED'
      AND coalesce(ld.draft_status, 'NONE') NOT IN ('SUBMITTING', 'SUBMITTED')
)
SELECT
    oc.provider_dispute_id,
    oc.origin,
    oc.reason,
    oc.amount,
    oc.currency,
    oc.deadline_at,
    -- Hours left; negative means the PayPal deadline has passed.
    round(extract(epoch FROM oc.deadline_at - now()) / 3600)::int AS hours_left,
    CASE
        WHEN oc.deadline_at IS NULL                    THEN 'NO_DEADLINE'
        WHEN oc.deadline_at <  now()                   THEN 'OVERDUE'
        WHEN oc.deadline_at <  now() + interval '48 hours' THEN 'URGENT'
        WHEN oc.deadline_at <  now() + interval '7 days'   THEN 'THIS_WEEK'
        ELSE 'LATER'
    END                                                AS urgency,
    coalesce(la.readiness, 'NOT_ANALYZED')             AS readiness,
    la.next_action,
    coalesce(ld.draft_status, 'NONE')                  AS draft_status,
    ld.submit_note,
    coalesce(ec.documents, 0)                          AS documents,
    -- What is missing or contradictory, in the analysis' own words.
    (SELECT count(*) FROM jsonb_array_elements(la.findings) f WHERE f ->> 'kind' = 'missing')  AS missing_items,
    (SELECT count(*) FROM jsonb_array_elements(la.findings) f WHERE f ->> 'kind' = 'conflict') AS conflicts,
    (SELECT string_agg(p ->> 'id', ', ' ORDER BY p ->> 'id')
       FROM jsonb_array_elements(la.propositions) p
      WHERE p ->> 'status' IN ('missing', 'contradicted', 'flagged'))                         AS not_proven,
    oc.provider_status,
    la.analyzed_at
FROM open_cases oc
LEFT JOIN latest_analysis la ON la.dispute_id = oc.id
LEFT JOIN latest_draft    ld ON ld.dispute_id = oc.id
LEFT JOIN evidence_count  ec ON ec.dispute_id = oc.id
ORDER BY
    oc.deadline_at ASC NULLS LAST,          -- PayPal's clock first
    CASE coalesce(la.readiness, 'NOT_ANALYZED')  -- then the cases that need the merchant's hands most
        WHEN 'WEAK'            THEN 1
        WHEN 'NEEDS_DOCUMENTS' THEN 2
        WHEN 'NEEDS_CHECK'     THEN 3
        WHEN 'NOT_ANALYZED'    THEN 4
        ELSE 5                              -- READY: only approve and send left
    END,
    oc.amount DESC
LIMIT 50;
