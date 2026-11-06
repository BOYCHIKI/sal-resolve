import "server-only";

import { cookies, headers as requestHeaders } from "next/headers";
import { SESSION_COOKIE } from "@/lib/session";

// Server-side only: the browser never talks to the API directly, so no CORS and no exposed API URL.
const API_URL = process.env.SAL_API_URL ?? "http://127.0.0.1:8000";
// Shared secret between this server and the API (required when the API runs with SAL_ENV=prod).
const INTERNAL = process.env.SAL_INTERNAL_TOKEN ? { "x-sal-internal-token": process.env.SAL_INTERNAL_TOKEN } : undefined;

/** Headers for every API call: the internal token, the signed-in seller's session from the httpOnly cookie, and the
 *  browser's address for the API's rate limits (trusted there only with the internal token). */
async function apiHeaders(): Promise<Record<string, string>> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  const address = (await requestHeaders()).get("x-forwarded-for")?.split(",")[0]?.trim();
  return { ...INTERNAL, ...(session ? { "x-sal-session": session } : {}), ...(address ? { "x-sal-client-ip": address } : {}) };
}

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
  | "EXPLAIN_DISPUTE" | "OFFER_REFUND" | "REVIEW_DEAL_HOLD";

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

/** One deal: what was ordered and invoiced, as exact data, and the worker's verdict. Values match app/deals.py. */
export type DealStatus = "WAITING_INVOICE" | "CHECKING" | "HOLD" | "CLEAR";
export type DealFindingCode = "CURRENCY_DIFFERS" | "ITEM_NOT_ORDERED" | "ITEM_NOT_INVOICED" | "QUANTITY_DIFFERS"
  | "UNIT_PRICE_DIFFERS" | "TOTAL_DOES_NOT_ADD_UP" | "OVER_APPROVED_LIMIT" | "APPROVAL_EXPIRED" | "ADDRESS_DIFFERS";
export type DealFinding = { code: DealFindingCode; field: string; ordered: string | null; invoiced: string | null };
export type Deal = {
  deal_ref: string;
  category: "GOODS" | "DIGITAL" | "SERVICE";
  status: DealStatus;
  purchase_order: { currency: string; max_total: string; approved_by: string };
  invoice: { invoice_ref: string; total: string; currency: string } | null;
  findings: DealFinding[];
  correction: { message: string; requested_at: string } | null;
  updated_at: string;
};

/** Two AI agents making one deal through SAL's MCP server, run by the worker (app/ai_agents.py). */
export type AgentStep = { actor: string; text: string; sal: string | null };
export type AgentRun = {
  id: string;
  state: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  error: string | null;
  result: { deal_ref: string; steps: AgentStep[] } | null;
  started_at: string;
};

/** A PO or invoice file. A proposal value is either proven on its line or blank. Values match app/deal_documents.py. */
export type ProvenValue = { value: string | null; line: number | null };
export type ProposedItem = { item_code: ProvenValue; description: ProvenValue; quantity: ProvenValue; unit_price: ProvenValue };
export type DocumentProposal = {
  reference: ProvenValue; party: ProvenValue; issued_on: ProvenValue; currency: ProvenValue; total: ProvenValue;
  shipping: ProvenValue; tax: ProvenValue; ship_country: ProvenValue; ship_city: ProvenValue;
  ship_postal_code: ProvenValue; items: ProposedItem[];
};
export type DealDocument = {
  id: string;
  kind: "PURCHASE_ORDER" | "INVOICE";
  deal_ref: string | null;
  status: "READING" | "NEEDS_CONFIRMATION" | "UNREADABLE";
  lines: { line: number; text: string }[] | null;
  proposal: DocumentProposal | null;
  created_at: string;
};

async function call<T>(path: string, init?: RequestInit): Promise<T | null> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers: { ...(await apiHeaders()), ...init?.headers } });
  if (res.status === 404 || res.status === 422) return null; // unknown or malformed id
  if (!res.ok) throw new Error(`SAL API ${res.status} on ${path}`);
  return (await res.json()) as T;
}

/** For actions whose error codes the UI should show (409 stale, 502 PayPal rejected, ...). */
export type ActionResult = { ok: true } | { ok: false; code: string; message: string };

const SESSION_ENDED = "Your session ended. Sign in again to continue.";

async function result(res: Response, fallback: string): Promise<ActionResult> {
  if (res.ok) return { ok: true };
  if (res.status === 401) return { ok: false, code: "AUTH_REQUIRED", message: SESSION_ENDED };
  const detail = (await res.json().catch(() => ({})))?.detail ?? {};
  return { ok: false, code: detail.code ?? `HTTP_${res.status}`, message: detail.message ?? fallback };
}

async function action(path: string, body?: unknown): Promise<ActionResult> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST", cache: "no-store",
    headers: { ...(await apiHeaders()), ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  return result(res, "Request failed");
}

/** Multipart upload of one document; the API checks type, size, duplicates and ownership. */
async function upload(path: string, form: FormData): Promise<ActionResult> {
  const res = await fetch(`${API_URL}${path}`, { method: "POST", cache: "no-store", body: form, headers: await apiHeaders() });
  return result(res, "Upload failed");
}

/** Like upload, but keeps the id of the new document so the page can follow its reading. */
async function uploadWithId(path: string, form: FormData): Promise<ActionResult & { id?: string }> {
  const res = await fetch(`${API_URL}${path}`, { method: "POST", cache: "no-store", body: form, headers: await apiHeaders() });
  if (!res.ok) return result(res, "Upload failed");
  const body = (await res.json().catch(() => ({}))) as { id?: string };
  return { ok: true, id: body.id };
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
  latestAgentRun: async () => (await call<{ run: AgentRun | null }>("/api/agent-runs/latest"))?.run ?? null,
  startAgentRun: () => action("/api/agent-runs"),
  listDeals: async () => (await call<{ items: Deal[] }>("/api/deals"))?.items ?? [],
  requestDealCorrection: (dealRef: string) => action(`/api/deals/${encodeURIComponent(dealRef)}/request-correction`),
  checkPayPalInvoice: (dealRef: string, invoiceId: string) =>
    action(`/api/deals/${encodeURIComponent(dealRef)}/paypal-invoice`, { invoice_id: invoiceId }),
  listDealDocuments: async () => (await call<{ items: DealDocument[] }>("/api/deal-documents"))?.items ?? [],
  uploadDealDocument: (form: FormData) => uploadWithId("/api/deal-documents", form),
  confirmDealDocument: (id: string, kind: DealDocument["kind"], body: unknown) =>
    action(`/api/deal-documents/${encodeURIComponent(id)}/confirm-${kind === "INVOICE" ? "invoice" : "order"}`, body),
  discardDealDocument: (id: string) => action(`/api/deal-documents/${encodeURIComponent(id)}/discard`),
  listPacking: async () => (await call<{ items: PackingRecord[] }>("/api/packing"))?.items ?? [],
  createPacking: (orderRef: string, transactionId: string, trackingNumber: string) =>
    action("/api/packing", {
      order_ref: orderRef || null, transaction_id: transactionId || null, tracking_number: trackingNumber || null,
    }),
  uploadPacking: (packingId: string, form: FormData) =>
    upload(`/api/packing/${encodeURIComponent(packingId)}/files`, form),
  /** The printable QR label, streamed back to the browser by app/packing/[id]/label/route.ts. */
  packingLabel: async (packingId: string) =>
    fetch(`${API_URL}/api/packing/${encodeURIComponent(packingId)}/label.pdf`, { cache: "no-store", headers: await apiHeaders() }),
};

// ---------------------------------------------------------------- accounts (ADR-009)
export type AuthStage = "ACTIVE" | "MFA_PENDING";
export type AuthReply<T> = ({ ok: true } & T) | { ok: false; code: string; message: string };
export type Account = {
  email: string; business: string; totp_enabled: boolean; recovery_codes_left: number; paypal_connected: boolean;
  sessions: { id: string; this_one: boolean; user_agent: string | null; signed_in_at: string; last_seen_at: string }[];
};

/** A POST to /api/auth/*. `session` overrides the cookie, for the pending token during the second step. */
async function authPost<T>(path: string, body?: unknown, session?: string): Promise<AuthReply<T>> {
  const base = await apiHeaders();
  const userAgent = (await requestHeaders()).get("user-agent") ?? "";
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST", cache: "no-store",
    headers: { ...base, ...(session ? { "x-sal-session": session } : {}), "user-agent": userAgent.slice(0, 300),
               ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({}));
  if (res.ok) return { ok: true, ...(json as T) };
  const detail = json?.detail;
  // FastAPI's own 422 (a field too long or missing) has a list here, not our {code, message}.
  if (Array.isArray(detail) || !detail) return { ok: false, code: `HTTP_${res.status}`, message: "Check the form and try again." };
  return { ok: false, code: detail.code ?? `HTTP_${res.status}`, message: detail.message ?? "Something went wrong. Try again." };
}

export const auth = {
  signUp: (business_name: string, email: string, password: string) =>
    authPost<{ stage: AuthStage; token: string }>("/api/auth/signup", { business_name, email, password }),
  signIn: (email: string, password: string) =>
    authPost<{ stage: AuthStage; token: string }>("/api/auth/login", { email, password }),
  finishSignIn: (pending: string, code: string) =>
    authPost<{ stage: AuthStage; token: string }>("/api/auth/mfa", { code }, pending),
  signOut: () => authPost<{ signed_out: boolean }>("/api/auth/logout"),
  signOutOthers: () => authPost<{ signed_out: number }>("/api/auth/logout-others"),
  changePassword: (current: string, next: string) => authPost<{ changed: boolean }>("/api/auth/password", { current, new: next }),
  startTwoStep: () => authPost<{ secret: string; otpauth_uri: string; qr_svg: string }>("/api/auth/mfa/setup"),
  enableTwoStep: (code: string) => authPost<{ recovery_codes: string[] }>("/api/auth/mfa/enable", { code }),
  disableTwoStep: (password: string, code: string) => authPost<{ two_step: boolean }>("/api/auth/mfa/disable", { password, code }),
  me: () => call<Account>("/api/auth/me"),
};
