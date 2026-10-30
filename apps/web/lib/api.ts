import "server-only";

// Server-side only: the browser never talks to the API directly, so no CORS and no exposed API URL.
const API_URL = process.env.SAL_API_URL ?? "http://127.0.0.1:8000";
// Shared secret between this server and the API (required when the API runs with SAL_ENV=prod).
const INTERNAL = process.env.SAL_INTERNAL_TOKEN ? { "x-sal-internal-token": process.env.SAL_INTERNAL_TOKEN } : undefined;

export type Money = { value: string; currency: string };

export type Dispute = {
  id: string;
  origin: "PAYPAL_SANDBOX" | "SYNTHETIC_FIXTURE";
  provider_dispute_id: string;
  case_ref: string | null;
  reason: string;
  amount: Money;
  provider_status: string;
  lifecycle_stage: string | null;
  channel?: string | null;   // INTERNAL: filed with PayPal; EXTERNAL: a bank chargeback
  seller_protection_eligible?: boolean | null;   // as PayPal marks the payment; null when it says nothing
  internal_state: string;
  deadline_at: string | null;
  allowed_actions: string[];
  version: number;
  summary: {
    item: string | null;
    order_ref: string | null;
    missing: number;
    conflicts: number;
    draft_status: string | null;
    readiness?: Readiness | null;
  } | null;
};

export type SourceRef = { evidence_id: string; line: number };

export type Fact = {
  field: string;
  value: string;
  source: SourceRef;
  status: "supported" | "conflicted" | "rejected";
  reason: string | null;
};

export type Finding = {
  kind: "missing" | "conflict";
  field: string;
  source_refs: SourceRef[];
  description: string;
};

export type Readiness = "READY" | "NEEDS_DOCUMENTS" | "NEEDS_CHECK" | "WEAK";

export type Proposition = {
  id: string;
  status: "proven" | "missing" | "contradicted" | "flagged" | "not_applicable";
  reason: string;
  sources: SourceRef[];
};

export type Assessment = { propositions: Proposition[]; readiness: Readiness; next_action: string };

export type Analysis = {
  analysis_id: string;
  dispute_version: number;
  rule_version: string;
  review_required: boolean;
  snapshot_hash: string;
  facts: Fact[];
  findings: Finding[];
  assessment: Assessment | null;
  draft: {
    id: string;
    revision: number;
    status: string;
    claims: { text: string; fact_fields: string[] }[];
    submit_note: string | null;
  } | null;
  agent: {
    roles: string;
    steps: number;
    tool_calls: { step: number; tool: string; args: Record<string, unknown>; ok: boolean; summary: string }[];
  };
};

export type EvidenceDoc = {
  evidence_id: string;
  type: string | null;
  lines: { line: number; text: string }[];
  origin?: "UPLOAD" | "PAYPAL_API" | "SEED" | "SELLER_INPUT";
};

export type ActionKind = "SEND_EVIDENCE" | "ADD_DOCUMENT" | "REPLY_BEFORE_DEADLINE" | "EXPLAIN_HELD_FUNDS"
  | "EXPLAIN_DISPUTE" | "OFFER_REFUND";

/** A suggestion SAL's agent made (ADR-006). The merchant approves the exact card it read, by payload_hash. */
export type AgentAction = {
  id: string;
  dispute_id: string | null;
  kind: ActionKind;
  status: string;
  title: string;
  rationale: string;
  payload: Record<string, unknown>;
  payload_hash: string;
  due_at: string | null;
  created_at: string;
};

export type Job = { id: string; kind: string; state: string; attempts: number; error: string | null };

/** Photos/video of a parcel recorded before shipping (ADR-007). SAL matches it to a dispute later. */
export type PackingRecord = {
  id: string;
  code: string;
  order_ref: string | null;
  transaction_id: string | null;
  tracking_number: string | null;
  created_at: string;
  expires_at: string;
  files: { id: string; mime: string; sha256: string; size_bytes: number }[];
};

async function call<T>(path: string, init?: RequestInit): Promise<T | null> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers: { ...INTERNAL, ...init?.headers } });
  if (res.status === 404 || res.status === 422) return null; // unknown or malformed id
  if (!res.ok) throw new Error(`SAL API ${res.status} on ${path}`);
  return (await res.json()) as T;
}

/** For actions whose error codes the UI should show (409 stale, 502 PayPal rejected, ...). */
export type ActionResult = { ok: true } | { ok: false; code: string; message: string };

async function action(path: string, body?: unknown): Promise<ActionResult> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST", cache: "no-store",
    headers: { ...INTERNAL, ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.ok) return { ok: true };
  const detail = (await res.json().catch(() => ({})))?.detail ?? {};
  return { ok: false, code: detail.code ?? `HTTP_${res.status}`, message: detail.message ?? "Request failed" };
}

/** Multipart upload of one document; the API checks type, size, duplicates and ownership. */
async function upload(path: string, form: FormData): Promise<ActionResult> {
  const res = await fetch(`${API_URL}${path}`, { method: "POST", cache: "no-store", body: form, headers: INTERNAL });
  if (res.ok) return { ok: true };
  const detail = (await res.json().catch(() => ({})))?.detail ?? {};
  return { ok: false, code: detail.code ?? `HTTP_${res.status}`, message: detail.message ?? "Upload failed" };
}

export type Health = { status: "ok" | "degraded" | "down"; worker: { alive: boolean; seconds_since: number | null } | null };

export const api = {
  health: async (): Promise<Health | null> => {
    try {
      return await call<Health>("/api/health");
    } catch {
      return null;
    }
  },
  listDisputes: async () => (await call<{ items: Dispute[] }>("/api/disputes?limit=100"))?.items ?? [],
  getDispute: (id: string) => call<Dispute>(`/api/disputes/${encodeURIComponent(id)}`),
  getAnalysis: (id: string) => call<Analysis>(`/api/disputes/${encodeURIComponent(id)}/analysis`),
  getEvidence: async (id: string) =>
    (await call<{ items: EvidenceDoc[] }>(`/api/disputes/${encodeURIComponent(id)}/evidence`))?.items ?? [],
  sync: () => call<{ job_id: string }>("/api/disputes/sync", { method: "POST" }),
  approveDraft: (id: string, revision: number, snapshotHash: string) =>
    action(`/api/drafts/${encodeURIComponent(id)}/approve`, { revision, snapshot_hash: snapshotHash }),
  submitDraft: (id: string) => action(`/api/drafts/${encodeURIComponent(id)}/submit`),
  addTracking: (disputeId: string, trackingNumber: string, courier: string) =>
    action(`/api/disputes/${encodeURIComponent(disputeId)}/tracking`,
      { tracking_number: trackingNumber, courier: courier || null }),
  uploadEvidence: (disputeId: string, form: FormData) =>
    upload(`/api/disputes/${encodeURIComponent(disputeId)}/evidence`, form),
  listActions: async (disputeId?: string) =>
    (await call<{ items: AgentAction[] }>(`/api/actions${disputeId ? `?dispute_id=${encodeURIComponent(disputeId)}` : ""}`))?.items ?? [],
  approveAction: (id: string, payloadHash: string, offerAmount?: string) =>
    action(`/api/actions/${encodeURIComponent(id)}/approve`, { payload_hash: payloadHash, offer_amount: offerAmount ?? null }),
  dismissAction: (id: string) => action(`/api/actions/${encodeURIComponent(id)}/dismiss`),
  getJob: (id: string) => call<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  listPacking: async () => (await call<{ items: PackingRecord[] }>("/api/packing"))?.items ?? [],
  createPacking: (orderRef: string, transactionId: string, trackingNumber: string) =>
    action("/api/packing", {
      order_ref: orderRef || null, transaction_id: transactionId || null, tracking_number: trackingNumber || null,
    }),
  uploadPacking: (packingId: string, form: FormData) =>
    upload(`/api/packing/${encodeURIComponent(packingId)}/files`, form),
  /** The printable QR label, streamed back to the browser by app/packing/[id]/label/route.ts. */
  packingLabel: (packingId: string) =>
    fetch(`${API_URL}/api/packing/${encodeURIComponent(packingId)}/label.pdf`, { cache: "no-store", headers: INTERNAL }),
};
