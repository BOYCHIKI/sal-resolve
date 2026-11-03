"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { requestDealCorrection } from "@/app/actions";
import type { Deal } from "@/lib/api";

/** Prepares the message for a held deal. SAL sends nothing: the seller passes it on, and the deal's agents can read it. */
export function RequestCorrection({ deal }: { deal: Deal }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  async function request() {
    setBusy(true);
    setError("");
    const result = await requestDealCorrection(deal.deal_ref);
    setBusy(false);
    if (!result.ok) setError("SAL couldn’t prepare the request. Please try again.");
    router.refresh();
  }

  async function copy(message: string) {
    await navigator.clipboard.writeText(message);
    setCopied(true);
  }

  if (!deal.correction) {
    return (
      <div className="flex flex-col items-start gap-1">
        <button type="button" onClick={request} disabled={busy} className="lp-btn text-[15px]">
          {busy ? "Preparing…" : "Request a correction"}
        </button>
        {error && <p role="alert" className="text-[15px] text-red-ink">{error}</p>}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-start gap-2">
      <p className="muted text-[15px]">Send this to the other side. SAL hasn’t sent it to anyone, and the deal’s agents can read it.</p>
      <pre className="w-full whitespace-pre-wrap rounded-xl bg-(--lp-well) p-3 text-[14px] [overflow-wrap:anywhere]">{deal.correction.message}</pre>
      <button type="button" onClick={() => copy(deal.correction!.message)} className="lp-btn-ghost text-[15px]">
        {copied ? "Copied" : "Copy message"}
      </button>
    </div>
  );
}
