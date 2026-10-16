// Turns system codes into words an operations or finance person reads without a glossary.
// The API keeps its codes; only the UI speaks plainly.
import type { Analysis, Dispute, Fact, Finding, Proposition, Readiness } from "@/lib/api";

const REASONS: Record<string, string> = {
  ITEM_NOT_RECEIVED: "Says it never arrived",
  MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED: "Says it wasn’t as described",
  UNAUTHORISED: "Says they didn’t make this payment",
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

export function dueText(iso: string | null): { text: string; short: string; urgent: boolean } {
  if (!iso) return { text: "Nothing due", short: "", urgent: false };
  const days = Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return { text: `Reply was due ${date(iso)}`, short: "Overdue", urgent: true };
  const left = `${days} day${days === 1 ? "" : "s"} left`;
  return { text: `Reply by ${date(iso)} · ${left}`, short: left, urgent: days <= 3 };
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
  const headline = d.reason === "ITEM_NOT_RECEIVED"
    ? `The customer says their ${item} never arrived.`
    : `The customer disputes their ${item} payment.`;
  const paidOn = a ? factValue(a.facts, "order_date") : undefined;
  const paid = `They paid ${d.amount.value} ${d.amount.currency}${paidOn ? ` on ${date(paidOn)}` : ""} and asked PayPal for a refund.`;
  if (!a) return { headline, detail: `${paid} SAL is still reading your documents.` };
  const missing = a.findings.filter((f) => f.kind === "missing").length;
  const conflicts = a.findings.filter((f) => f.kind === "conflict").length;
  if (missing) return { headline, detail: `${paid} Some proof is missing. Add it before you reply.` };
  const delivered = factValue(a.facts, "carrier_status") === "DELIVERED";
  if (conflicts)
    return { headline, detail: `${paid} ${delivered ? "Your documents show it was delivered, but " : ""}${conflicts === 1 ? "one detail needs" : `${conflicts} details need`} a quick check before you reply.` };
  return { headline, detail: `${paid} Your documents back this up. Read the reply and approve it.` };
}
