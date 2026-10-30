// Turns system codes into words an operations or finance person reads without a glossary.
// The API keeps its codes; only the UI speaks plainly.
import type { Analysis, Dispute, Fact, Finding, Proposition, Readiness } from "@/lib/api";

const REASONS: Record<string, string> = {
  ITEM_NOT_RECEIVED: "Says it never arrived",
  MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED: "Says it wasn’t as described",
  UNAUTHORISED: "Says they didn’t make this payment",
  CREDIT_NOT_PROCESSED: "Says a promised refund never came",
  DUPLICATE_TRANSACTION: "Says they were charged twice",
  INCORRECT_AMOUNT: "Says they were charged the wrong amount",
  PAYMENT_BY_OTHER_MEANS: "Says they already paid another way",
  CANCELED_RECURRING_BILLING: "Says they cancelled this subscription",
};

export function reason(code: string): string {
  return REASONS[code] ?? "Asked for their money back";
}

export function origin(code: string): string {
  return code === "PAYPAL_SANDBOX" ? "PayPal test account" : "Practice case";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-08-19" or an ISO timestamp -> "19 Aug 2026". Anything else is returned unchanged. */
export function date(value: string | null | undefined): string {
  if (!value) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : value;
}

/** PayPal's deadline with its time, in UTC, so it reads the same wherever the page is rendered. */
function deadlineStamp(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${hh}:${mm} UTC`;
}

/** Time left, rounded down: 3 hours left never reads as "1 day left". */
export function dueText(iso: string | null, now: number = Date.now()): { text: string; short: string; urgent: boolean } {
  if (!iso) return { text: "Nothing due", short: "", urgent: false };
  const ms = new Date(iso).getTime() - now;
  if (Number.isNaN(ms)) return { text: "Nothing due", short: "", urgent: false };
  if (ms < 0) return { text: `Reply was due ${deadlineStamp(iso)}`, short: "Overdue", urgent: true };
  const hours = Math.floor(ms / 3_600_000);
  const days = Math.floor(hours / 24);
  const left = hours < 1 ? "Less than 1 hour left"
    : hours < 24 ? `${hours} hour${hours === 1 ? "" : "s"} left`
    : `${days} day${days === 1 ? "" : "s"} left`;
  return { text: `Reply by ${deadlineStamp(iso)} · ${left}`, short: left, urgent: hours < 72 };
}

export function orderNumber(ref: string | null | undefined): string | null {
  return ref ? ref.replace(/^ORD-(SYN-)?/, "") : null;
}

export type Tone = "red" | "amber" | "blue" | "green" | "grey";

/** The one thing to do next, in words. */
export function nextStep(d: Dispute): { label: string; tone: Tone } {
  const s = d.summary;
  if (d.provider_status === "RESOLVED") return { label: "Closed by PayPal", tone: "grey" };
  if (s?.draft_status === "SUBMITTING") return { label: "Sending to PayPal…", tone: "blue" };
  const evidenceStep = s?.readiness && s.readiness !== "READY" ? READINESS[s.readiness] : null;
  if (d.internal_state === "SUBMITTED")
    return { label: d.provider_status === "UNDER_REVIEW" ? "PayPal is reviewing your reply" : "Sent, waiting for PayPal", tone: "grey" };
  if (d.provider_status === "WAITING_FOR_BUYER_RESPONSE") return { label: "Waiting for the customer", tone: "grey" };
  if (d.internal_state === "APPROVED") return { label: "Approved, ready to send", tone: "blue" };
  if (!s || s.draft_status === null) return { label: "Being prepared", tone: "grey" };
  if (s.readiness === "WEAK") return READINESS.WEAK;
  if (s.missing > 0) return { label: s.missing === 1 ? "Missing 1 document" : `Missing ${s.missing} documents`, tone: "red" };
  if (s.conflicts > 0) return { label: s.conflicts === 1 ? "Check 1 detail first" : `Check ${s.conflicts} details first`, tone: "amber" };
  if (evidenceStep) return evidenceStep;  // e.g. no PayPal transaction record yet
  return { label: "Review the reply", tone: "amber" };
}

export const DOCS: Record<string, string> = {
  order_invoice: "Invoice",
  payment_record: "Payment receipt",
  carrier_tracking: "Courier tracking",
  delivery_proof: "Delivery receipt",
  support_message: "Customer message",
  seller_shipment: "Tracking number you entered",
  packing_proof: "Packing photos",
  other: "Other document",
};

export function docName(type: string | null | undefined, from?: string): string {
  if (from === "PAYPAL_API" && type === "payment_record") return "PayPal transaction record";
  return (type && DOCS[type]) || "Document";
}

/** A document's name inside a sentence ("See invoice"), keeping brand capitals ("See PayPal transaction record"). */
export function docRef(type: string | null | undefined, from?: string): string {
  const name = docName(type, from);
  return name.startsWith("PayPal") ? name : name.toLowerCase();
}

// ---------------------------------------------------------------- what the evidence proves (ADR-005)
const PROPOSITION_TITLES: Record<string, string> = {
  payment_matches: "The PayPal payment matches the dispute",
  shipped: "The parcel was shipped",
  delivered: "The parcel was delivered",
  delivery_date_consistent: "The delivery dates agree",
  delivered_to_paypal_address: "It went to the address on the PayPal payment",
  buyer_messages_clean: "The buyer's messages are clean",
  paypal_request_covered: "What PayPal asked for is covered",
};

export function propositionTitle(id: string): string {
  return PROPOSITION_TITLES[id] ?? id;
}

export function propositionLook(status: Proposition["status"]): { mark: string; word: string; tone: Tone } {
  switch (status) {
    case "proven": return { mark: "✓", word: "Proven", tone: "green" };
    case "missing": return { mark: "✕", word: "Missing", tone: "red" };
    case "contradicted": return { mark: "!", word: "Doesn’t match", tone: "amber" };
    case "flagged": return { mark: "!", word: "Check this", tone: "amber" };
    default: return { mark: "–", word: "Not needed", tone: "grey" };
  }
}

const READINESS: Record<Readiness, { label: string; tone: Tone }> = {
  READY: { label: "Ready to reply", tone: "green" },
  NEEDS_DOCUMENTS: { label: "Documents missing", tone: "red" },
  NEEDS_CHECK: { label: "Check details first", tone: "amber" },
  WEAK: { label: "Weak evidence", tone: "red" },
};

export function readiness(r: Readiness): { label: string; tone: Tone } {
  return READINESS[r];
}

const FIELDS: Record<string, string> = {
  order_id: "Order number",
  transaction_id: "PayPal transaction",
  order_amount: "Order amount",
  order_date: "Ordered on",
  payment_amount: "Paid",
  ship_date: "Shipped on",
  tracking_id: "Tracking number",
  carrier_status: "Courier status",
  carrier_event_date: "Courier’s last update",
  delivery_date: "Delivered on",
  reported_payment_amount: "Amount the customer mentions",
};

const STATUS_WORDS: Record<string, string> = { DELIVERED: "Delivered", IN_TRANSIT: "On the way" };

/** Facts worth showing a person, labelled and formatted; codes and duplicates left out. */
export function readableFacts(facts: Fact[], currency: string): { label: string; value: string; doubtful: boolean; source: string }[] {
  const seen = new Set<string>();
  const out = [];
  for (const f of facts) {
    if (f.status === "rejected" || !FIELDS[f.field] || seen.has(f.field)) continue;
    seen.add(f.field);
    let value = f.value;
    if (f.field.endsWith("_date")) value = date(value);
    if (f.field.endsWith("amount")) value = `${value} ${currency}`;
    if (f.field === "carrier_status") value = STATUS_WORDS[value] ?? value;
    if (f.field === "order_id") value = orderNumber(value) ?? value;
    out.push({ label: FIELDS[f.field], value, doubtful: f.status === "conflicted", source: f.source.evidence_id });
  }
  return out;
}

function factValue(facts: Fact[], field: string): string | undefined {
  return facts.find((f) => f.field === field && f.status !== "rejected")?.value;
}

/** A finding as a title, a sentence and the documents to look at. */
export function explain(f: Finding, facts: Fact[], currency: string): { title: string; body: string; tone: Tone } {
  if (f.kind === "missing" && f.field === "carrier_tracking")
    return { title: "No courier tracking yet", body: "Add the tracking page or shipping label so PayPal can see the parcel was sent.", tone: "red" };
  if (f.kind === "missing" && f.field === "delivery_proof")
    return { title: "No proof of delivery yet", body: "Add the courier’s delivery confirmation. Without it, PayPal often sides with the customer.", tone: "red" };
  if (f.field === "delivery_date")
    return {
      title: "The delivery dates don’t match",
      body: `The courier’s tracking says ${date(factValue(facts, "carrier_event_date"))}, the delivery receipt says ${date(factValue(facts, "delivery_date"))}. The reply won’t mention a delivery date until you confirm which one is right.`,
      tone: "amber",
    };
  if (f.field === "reported_payment_amount")
    return {
      title: "The customer mentions a different amount",
      body: `They wrote ${factValue(facts, "reported_payment_amount")} ${currency}, but the payment received was ${factValue(facts, "payment_amount")} ${currency}. The reply uses the amount from the payment record.`,
      tone: "amber",
    };
  if (f.field === "untrusted_instruction")
    return { title: "A message contains instructions", body: "Some text tries to tell SAL what to do. SAL ignored it. Please read that message yourself.", tone: "amber" };
  if (f.field.endsWith("_vs_dispute"))
    return { title: "An amount doesn’t match the dispute", body: "A document shows a different amount or currency than PayPal’s case. Check it before replying.", tone: "amber" };
  return { title: "Something to check", body: f.description, tone: "amber" };
}

export function summarySentence(d: Dispute, a: Analysis | null): { headline: string; detail: string } {
  const item = d.summary?.item ?? "order";
  const headline = d.reason === "ITEM_NOT_RECEIVED" ? `The customer says their ${item} never arrived.`
    : d.reason === "UNAUTHORISED" ? `The customer says they didn’t make the payment for this ${item}.`
    : `The customer disputes their ${item} payment.`;
  const paidOn = a ? factValue(a.facts, "order_date") : undefined;
  const paid = `They paid ${d.amount.value} ${d.amount.currency}${paidOn ? ` on ${date(paidOn)}` : ""} and asked PayPal for a refund.`;
  if (d.internal_state === "SUBMITTED") {
    const waiting = d.provider_status === "WAITING_FOR_BUYER_RESPONSE" ? "PayPal is waiting for the buyer to answer."
      : d.provider_status === "RESOLVED" ? "PayPal has closed the case." : "PayPal is reviewing it.";
    return { headline, detail: `${paid} You sent your evidence to PayPal. ${waiting} SAL keeps checking for you.` };
  }
  if (!a) return { headline, detail: `${paid} SAL is still reading your documents.` };
  const missing = a.findings.filter((f) => f.kind === "missing").length;
  const conflicts = a.findings.filter((f) => f.kind === "conflict").length;
  if (missing) return { headline, detail: `${paid} Some proof is missing. Add it before you reply.` };
  const delivered = factValue(a.facts, "carrier_status") === "DELIVERED";
  if (conflicts)
    return { headline, detail: `${paid} ${delivered ? "Your documents show it was delivered, but " : ""}${conflicts === 1 ? "one detail needs" : `${conflicts} details need`} a quick check before you reply.` };
  return { headline, detail: `${paid} Your documents back this up. Read the reply and approve it.` };
}

// ---------------------------------------------------------------- case types (PayPal's 10 dispute reasons)
// Sellers can't know which kind of case comes next, so every type is listed with what SAL does for it.
export type CaseType = { key: string; title: string; buyer: string; sal: string; tone: Tone };

export const CASE_TYPES: CaseType[] = [
  { key: "not_received", title: "Not received", tone: "amber",
    buyer: "The buyer says the parcel never arrived.",
    sal: "SAL checks your payment, tracking and delivery proof, names what’s missing and drafts the reply you approve." },
  { key: "not_as_described", title: "Not as described", tone: "blue",
    buyer: "The buyer says the item is wrong, damaged or different.",
    sal: "SAL explains your options, adds your packing photos and can send a refund offer of an amount you choose." },
  { key: "bank_chargeback", title: "Bank chargeback", tone: "red",
    buyer: "The buyer asked their bank or card company for the money back.",
    sal: "The bank decides and Seller Protection may not cover it, so SAL asks for proof of delivery before you send." },
  { key: "unauthorized", title: "Unauthorized payment", tone: "red",
    buyer: "The buyer says they didn’t make this payment.",
    sal: "PayPal protects you if the parcel went to the address on the payment. SAL checks exactly that and drafts the reply you approve." },
  { key: "refund_missing", title: "Refund not received", tone: "grey",
    buyer: "The buyer says you promised a refund that never came.",
    sal: "SAL flags it so it isn’t missed; check your refunds and answer it in PayPal." },
  { key: "billing", title: "Billing problem", tone: "grey",
    buyer: "Charged twice, the wrong amount, paid another way, or a cancelled subscription.",
    sal: "SAL flags it so it isn’t missed; check the payment and answer it in PayPal." },
  { key: "other", title: "Other", tone: "grey",
    buyer: "A reason PayPal doesn’t list.",
    sal: "SAL flags it so it isn’t missed; read the buyer’s message in PayPal." },
];

const TYPE_BY_REASON: Record<string, string> = {
  ITEM_NOT_RECEIVED: "not_received",
  MERCHANDISE_OR_SERVICE_NOT_RECEIVED: "not_received",
  MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED: "not_as_described",
  UNAUTHORISED: "unauthorized",
  CREDIT_NOT_PROCESSED: "refund_missing",
  DUPLICATE_TRANSACTION: "billing",
  INCORRECT_AMOUNT: "billing",
  PAYMENT_BY_OTHER_MEANS: "billing",
  CANCELED_RECURRING_BILLING: "billing",
  PROBLEM_WITH_REMITTANCE: "billing",
};

/** The case type a seller would name it by. A bank chargeback is its own type whatever the reason. */
export function caseTypeOf(d: Dispute): CaseType {
  const key = d.channel === "EXTERNAL" ? "bank_chargeback" : TYPE_BY_REASON[d.reason] ?? "other";
  return CASE_TYPES.find((t) => t.key === key)!;
}

/** Where the case is in PayPal's process. PayPal's CHARGEBACK stage on its own channel is a claim PayPal decides. */
export function stageOf(d: Dispute): { label: string; tone: Tone } | null {
  if (d.channel === "EXTERNAL") return { label: "The bank decides", tone: "red" };
  if (d.lifecycle_stage === "INQUIRY") return { label: "Talking with the buyer", tone: "blue" };
  if (d.lifecycle_stage === "CHARGEBACK") return { label: "Claim: PayPal decides", tone: "amber" };
  if (d.lifecycle_stage === "PRE_ARBITRATION" || d.lifecycle_stage === "ARBITRATION") return { label: "Appeal", tone: "amber" };
  return null;
}