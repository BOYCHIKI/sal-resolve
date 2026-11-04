"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { decideAction } from "@/app/actions";
import type { ActionKind, AgentAction } from "@/lib/api";
import { amount as formatAmount } from "@/lib/format";

const LOOK: Record<ActionKind, { eyebrow: string; primary: string }> = {
  SEND_EVIDENCE: { eyebrow: "Ready to send", primary: "Send to PayPal" },
  REPLY_BEFORE_DEADLINE: { eyebrow: "Deadline", primary: "Done" },
  ADD_DOCUMENT: { eyebrow: "Missing document", primary: "I added it" },
  EXPLAIN_HELD_FUNDS: { eyebrow: "Money on hold", primary: "" },
  EXPLAIN_DISPUTE: { eyebrow: "From SAL", primary: "Got it" },
  OFFER_REFUND: { eyebrow: "Settle it", primary: "Send offer to PayPal" },
  REVIEW_DEAL_HOLD: { eyebrow: "Before you deliver", primary: "I’ve seen it" },
};

const MESSAGES: Record<string, string> = {
  AUTH_REQUIRED: "Your session ended. Sign in again to continue.",
  STALE_ACTION: "SAL updated this suggestion. Reload the page and read it again.",
  ACTION_NOT_OPEN: "This suggestion was already handled.",
  DISPUTE_CHANGED: "PayPal updated this case. SAL is preparing a new suggestion.",
  EVIDENCE_CHANGED: "Documents changed since SAL wrote this. SAL is preparing a new suggestion.",
  DRAFT_OUT_OF_DATE: "This case changed since SAL wrote this reply. SAL is preparing a new one.",
  DOCUMENT_MISSING: "A document on this case is no longer stored, so nothing was sent. Add it again.",
  SEND_IN_PROGRESS: "An earlier reply is still being confirmed with PayPal. Try again in a few minutes.",
  SUBMIT_UNCONFIRMED: "PayPal didn’t answer in time. SAL will check whether it arrived. Don’t send it again yet.",
  PAYPAL_REJECTED: "PayPal didn’t accept it right now. You can try again from the case page.",
  OFFER_NOT_AVAILABLE: "PayPal no longer takes a refund offer on this case. Nothing was sent.",
  OFFER_UNCONFIRMED: "PayPal didn’t answer in time. SAL will check whether the offer arrived. Don’t send it again yet.",
  PAYPAL_UNREACHABLE: "PayPal can’t be reached right now. Nothing was sent.",
  API_UNREACHABLE: "SAL can’t reach its server right now. Please try again in a moment.",
};

function dueLabel(iso: string | null): string | null {
  if (!iso) return null;
  const hours = Math.floor((new Date(iso).getTime() - Date.now()) / 3_600_000);
  if (Number.isNaN(hours)) return null;
  if (hours < 0) return "Overdue";
  return hours < 48 ? `${hours} hour${hours === 1 ? "" : "s"} left` : `${Math.floor(hours / 24)} days left`;
}

/** One suggestion from SAL's agent. Nothing reaches PayPal unless the merchant presses the send button. */
export function ActionCard({ action, caseLink = true }: { action: AgentAction; caseLink?: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const look = LOOK[action.kind];
  const due = dueLabel(action.due_at);
  const offer = action.kind === "OFFER_REFUND";
  const sends = action.kind === "SEND_EVIDENCE" || offer;
  const max = String(action.payload.max_amount ?? "");
  const currency = String(action.payload.currency ?? "");
  const [amount, setAmount] = useState("");
  // Money on hold is information, not a task: it stays until PayPal releases the money, and there is nothing to press.
  const info = action.kind === "EXPLAIN_HELD_FUNDS";

  async function decide(decision: "approve" | "dismiss") {
    setBusy(true);
    setError(null);
    const r = await decideAction(action.id, decision, action.payload_hash, action.dispute_id,
      offer && decision === "approve" ? amount : undefined);
    if (!r.ok) setError(r.code === "BAD_OFFER_AMOUNT" ? r.message : MESSAGES[r.code] ?? "Something went wrong. Please try again.");
    setBusy(false);
    router.refresh();
  }

  return (
    <article className="lp-card flex flex-wrap items-center gap-x-6 gap-y-4 p-5 sm:p-6">
      <div className="flex min-w-0 flex-[999_1_320px] flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="muted text-[13px] font-semibold uppercase tracking-wide">{look.eyebrow}</span>
          {due && <span className={`text-[13px] ${due === "Overdue" || due.includes("hour") ? "font-semibold text-red-ink" : "muted"}`}>{due}</span>}
        </div>
        <h3 className="text-[18px] font-semibold">
          {info && action.payload.amount ? `${formatAmount(String(action.payload.amount), currency)} is on hold` : action.title}
        </h3>
        <p className="muted text-[15px] leading-relaxed">{action.rationale}</p>
        {offer && (
          <label className="mt-1 flex flex-wrap items-center gap-2 text-[15px]">
            Refund amount
            <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} disabled={busy}
              placeholder={`up to ${max}`} maxLength={12}
              className="w-32 rounded-xl border border-(--lp-line) bg-(--lp-well) px-3 py-2 tabular-nums" />
            <span className="muted">{currency}</span>
          </label>
        )}
        {sends && <p className="muted text-sm">
          {offer ? "Sends only this offer, with the amount you typed, and only when you press the button."
            : "Sends only this exact reply, and only when you press the button."}</p>}
        {error && <p role="alert" className="text-[15px] text-red-ink">{error}</p>}
      </div>
      {/* Fixed widths, so the buttons sit in the same columns on every card. */}
      {!info && <div className="flex max-w-full flex-wrap items-center gap-2 sm:w-[392px] sm:flex-none sm:flex-nowrap sm:justify-end">
        {caseLink && action.dispute_id && !sends && (
          <Link href={`/disputes/${action.dispute_id}`} className="lp-btn whitespace-nowrap sm:w-[176px]">Open the case</Link>
        )}
        {action.kind === "REVIEW_DEAL_HOLD" && <Link href="/deals" className="lp-btn whitespace-nowrap sm:w-[176px]">Open Deal Check</Link>}
        <button className={sends ? "lp-btn whitespace-nowrap sm:w-[312px]" : "lp-btn-ghost whitespace-nowrap sm:w-[128px]"} disabled={busy || (offer && !amount.trim())}
          onClick={() => decide("approve")}>
          {busy ? "Working…" : look.primary}
        </button>
        <button className="muted px-2 py-2 text-sm whitespace-nowrap hover:underline sm:w-[72px]" disabled={busy} onClick={() => decide("dismiss")}>
          Not now
        </button>
      </div>}
    </article>
  );
}
