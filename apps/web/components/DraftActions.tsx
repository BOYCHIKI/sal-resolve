"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { approveDraft, submitDraft } from "@/app/actions";

type Props = {
  disputeId: string;
  draftId: string;
  revision: number;
  snapshotHash: string;
  status: string;
  sandbox: boolean;
  canProvideEvidence: boolean;
  openItems: number;
  note: string | null;
};

const MESSAGES: Record<string, string> = {
  STALE_REVISION: "SAL wrote a newer version of this reply. Please read that one.",
  STALE_SNAPSHOT: "Something changed since you opened this page. Reload it and read the reply again.",
  DISPUTE_CHANGED: "PayPal updated this case. SAL is preparing a new reply.",
  DRAFT_NOT_PENDING: "This reply was already approved.",
  NOT_SUBMITTABLE: "This reply was already sent, or is being sent.",
  EVIDENCE_CHANGED: "Documents were added after you approved. SAL is updating the reply; please read and approve it again.",
  SUBMIT_UNCONFIRMED: "PayPal didn’t answer in time. SAL will check with PayPal in a few minutes whether it arrived. Don’t send it again yet.",
  PAYPAL_REJECTED: "PayPal didn’t accept the documents right now. You can try again.",
  API_UNREACHABLE: "SAL can’t reach its server right now. Please try again in a moment.",
};

type Message = { ok: boolean; text: string } | null;

function Feedback({ message }: { message: Message }) {
  if (!message) return null;
  return message.ok
    ? <p role="status" className="text-[15px] text-green-ink">{message.text}</p>
    : <p role="alert" className="text-[15px] text-red-ink">{message.text}</p>;
}

export function DraftActions(p: Props) {
  const router = useRouter();
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message>(null);

  async function run(fn: () => ReturnType<typeof approveDraft>, success: string) {
    setBusy(true);
    setMessage(null);
    const r = await fn();
    setMessage(r.ok ? { ok: true, text: success } : { ok: false, text: MESSAGES[r.code] ?? "Something went wrong. Please try again." });
    setBusy(false);
    router.refresh();
  }

  if (p.status === "SUBMITTED") {
    return <p className="rounded-2xl bg-green-bg p-4 text-green-ink">Sent to PayPal. You’ll see PayPal’s answer here when it arrives.</p>;
  }

  if (p.status === "SUBMITTING") {
    return (
      <p className="rounded-2xl bg-grey-bg p-4 text-ink-soft" role="status">
        Sending to PayPal. If PayPal doesn’t confirm, SAL checks with PayPal within a few minutes and shows the result here.
      </p>
    );
  }

  if (p.status === "DRAFT") {
    return (
      <div className="flex flex-col gap-3">
        <label className="flex items-start gap-3 rounded-2xl bg-grey-bg px-4 py-3.5">
          <input type="checkbox" className="mt-1 h-5 w-5 shrink-0 accent-[var(--lp-mint)]" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
          <span>I’ve read the reply{p.openItems > 0 ? ` and checked the ${p.openItems === 1 ? "detail" : `${p.openItems} details`} above` : ""}.</span>
        </label>
        <button className="lp-btn w-full" disabled={!reviewed || busy}
          onClick={() => run(() => approveDraft(p.disputeId, p.draftId, p.revision, p.snapshotHash), "Approved. You can now send it to PayPal.")}>
          {busy ? "Approving…" : "Approve reply"}
        </button>
        <p className="text-sm text-ink-muted">Nothing is sent until you approve and then press “Send to PayPal”.</p>
        <Feedback message={message} />
      </div>
    );
  }

  if (p.status === "APPROVED" || p.status === "SUBMIT_FAILED") {
    const blocked = !p.sandbox
      ? "This is a practice case, so there’s no real PayPal case to send it to."
      : !p.canProvideEvidence ? "PayPal isn’t accepting documents for this case right now." : null;
    return (
      <div className="flex flex-col gap-3">
        <p className={p.note === "NEEDS_MANUAL_CHECK" ? "text-amber-ink" : "text-green-ink"}>
          {p.status === "APPROVED" ? "You approved this reply."
            : p.note === "NEEDS_MANUAL_CHECK" ? "SAL couldn’t confirm the last send, and PayPal has moved the case on. Check the case in PayPal before sending again."
            : p.note === "NOT_RECEIVED" ? "PayPal never received the last send. You can send it again."
            : "The last send didn’t go through. You can try again."}
        </p>
        <button className="lp-btn w-full" disabled={busy || blocked !== null}
          onClick={() => run(() => submitDraft(p.disputeId, p.draftId), "Sent to PayPal.")}>
          {busy ? "Sending…" : "Send to PayPal"}
        </button>
        {blocked && <p className="text-sm text-ink-muted">{blocked}</p>}
        <Feedback message={message} />
      </div>
    );
  }

  return <p className="text-ink-muted">An older version of this reply. A newer one is above.</p>;
}
