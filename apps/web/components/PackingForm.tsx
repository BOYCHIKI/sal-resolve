"use client";

import { useState } from "react";
import { createPacking } from "@/app/actions";

const FIELD = "rounded-xl border border-(--lp-line) bg-(--lp-well) px-3 py-2.5 text-[15px] text-ink";

/** Step 1: tell SAL which order the parcel belongs to. One reference is enough. */
export function PackingForm() {
  const [order, setOrder] = useState("");
  const [txn, setTxn] = useState("");
  const [resi, setResi] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await createPacking(order, txn, resi);
    setBusy(false);
    if (r.ok) { setOrder(""); setTxn(""); setResi(""); } else setError(r.message);
  }

  return (
    <form onSubmit={submit} className="lp-card flex flex-col gap-4 p-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-xl font-semibold">Record a parcel</h2>
        <p className="muted text-[15px]">Fill in at least one. SAL uses it to find this parcel if the buyer complains later.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1.5 text-sm text-ink-soft">
          Order number
          <input className={FIELD} value={order} onChange={(e) => setOrder(e.target.value)} maxLength={64} disabled={busy} />
        </label>
        <label className="flex flex-col gap-1.5 text-sm text-ink-soft">
          PayPal transaction id
          <input className={FIELD} value={txn} onChange={(e) => setTxn(e.target.value)} maxLength={17} disabled={busy} />
        </label>
        <label className="flex flex-col gap-1.5 text-sm text-ink-soft">
          Tracking number (resi)
          <input className={FIELD} value={resi} onChange={(e) => setResi(e.target.value)} maxLength={60} disabled={busy} />
        </label>
      </div>
      {error && <p role="alert" className="text-sm text-red-ink">{error}</p>}
      <button type="submit" className={`lp-btn self-start text-[16px] ${busy ? "opacity-60" : ""}`} disabled={busy}>
        {busy ? "Saving…" : "Create packing record"}
      </button>
    </form>
  );
}
