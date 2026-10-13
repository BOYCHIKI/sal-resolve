"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { approveDraft, submitDraft } from "@/app/actions";
import { primaryButton } from "@/components/ui";

type Props = {
  disputeId: string;
  draftId: string;
  revision: number;
  snapshotHash: string;
  status: string;
  sandbox: boolean;
  canProvideEvidence: boolean;
  reviewRequired: boolean;
};

const MESSAGES: Record<string, string> = {
  STALE_REVISION: "A newer draft exists. Review it before approving.",
  STALE_SNAPSHOT: "The analysis changed since this page loaded. Reload and review again.",
  DISPUTE_CHANGED: "PayPal updated this dispute. Wait for the new analysis.",
  DRAFT_NOT_PENDING: "This draft is no longer awaiting approval.",
  NOT_SUBMITTABLE: "This draft has already been sent or is not approved.",
};

export function DraftActions(p: Props) {
  const router = useRouter();
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function run(fn: () => ReturnType<typeof approveDraft>, success: string) {
    setBusy(true);
    setMessage(null);
    const r = await fn();
    setMessage(r.ok ? { ok: true, text: success } : { ok: false, text: MESSAGES[r.code] ?? r.message });
    setBusy(false);
    router.refresh();
  }

  if (p.status === "SUBMITTED") {
    return <p className="mt-4 rounded-xl bg-good-bg p-3 text-sm text-good-ink">Sent to PayPal as evidence. Status will refresh on the next sync.</p>;
  }

  if (p.status === "DRAFT") {
    return (
      <div className="mt-4 space-y-3">
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1 accent-[var(--action)]" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
          <span>
            I reviewed every statement against its source
            {p.reviewRequired && <span className="text-warn-ink"> and the open items under “Needs your attention”</span>}.
          </span>
        </label>
        <button
          className={`w-full ${primaryButton}`}
          disabled={!reviewed || busy}
          onClick={() => run(() => approveDraft(p.disputeId, p.draftId, p.revision, p.snapshotHash), "Approved.")}
        >
          {busy ? "Approving…" : `Approve revision ${p.revision}`}
        </button>
        <Feedback message={message} />
      </div>
    );
  }

  if (p.status === "APPROVED" || p.status === "SUBMIT_FAILED") {
    const blocked = !p.sandbox
      ? "Synthetic fixture: approved, but there is no PayPal dispute to send it to."
      : !p.canProvideEvidence ? "PayPal does not currently accept evidence for this dispute." : null;
    return (
      <div className="mt-4 space-y-3">
        <p className="text-sm text-good-ink">
          {p.status === "APPROVED" ? `Revision ${p.revision} approved.` : "The last send failed. You can retry."}
        </p>
        <button
          className={`w-full ${primaryButton}`}
          disabled={busy || blocked !== null}
          onClick={() => run(() => submitDraft(p.disputeId, p.draftId), "Sent to PayPal.")}
        >
          {busy ? "Sending…" : "Send to PayPal"}
        </button>
        {blocked && <p className="text-xs text-ink-muted">{blocked}</p>}
        <Feedback message={message} />
      </div>
    );
  }

  return <p className="mt-4 text-sm text-ink-muted">Draft status: {p.status.toLowerCase()}.</p>;
}

function Feedback({ message }: { message: { ok: boolean; text: string } | null }) {
  if (!message) return null;
  return message.ok
    ? <p className="text-sm text-good-ink" role="status">{message.text}</p>
    : <p className="text-sm text-bad-ink" role="alert">{message.text}</p>;
}
