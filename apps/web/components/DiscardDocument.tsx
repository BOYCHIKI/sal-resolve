"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { discardDealDocument } from "@/app/actions";

/** Removes a document SAL couldn't read from the list, so it doesn't wait there for ever. */
export function DiscardDocument({ id }: { id: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function discard() {
    setBusy(true);
    await discardDealDocument(id);
    setBusy(false);
    router.refresh();
  }
  return (
    <button type="button" onClick={discard} disabled={busy} className="lp-btn-ghost whitespace-nowrap text-[15px]">
      {busy ? "Removing…" : "Remove"}
    </button>
  );
}
