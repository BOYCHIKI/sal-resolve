"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { addTracking } from "@/app/actions";

const MESSAGES: Record<string, string> = {
  BAD_TRACKING_NUMBER: "Enter the tracking number (resi) as printed: 6–40 letters and digits.",
  BAD_COURIER: "Enter the courier’s name, for example JNE, J&T or LBC.",
  DUPLICATE_TRACKING: "This tracking number is already on the case.",
  API_UNREACHABLE: "SAL can’t reach its server right now. Please try again in a moment.",
};

/** The seller types the resi. SAL records it as their word: it names the parcel for PayPal, but only the
 *  courier's own page can show the parcel moved or arrived. */
export function AddTracking({ disputeId }: { disputeId: string }) {
  const router = useRouter();
  const [resi, setResi] = useState("");
  const [courier, setCourier] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    const r = await addTracking(disputeId, resi, courier);
    setMessage(r.ok ? { ok: true, text: "Saved. SAL is checking the case again." }
      : { ok: false, text: MESSAGES[r.code] ?? "Couldn’t save this. Please try again." });
    if (r.ok) { setResi(""); setCourier(""); }
    setBusy(false);
    router.refresh();
  }

  const field = "rounded-xl border border-(--lp-line) bg-(--lp-well) px-3 py-2.5 text-[15px] text-ink";
  return (
    <form onSubmit={save} className="flex flex-col gap-3 rounded-2xl bg-grey-bg p-4">
      <p className="font-medium">Add the tracking number</p>
      <div className="flex flex-wrap gap-2.5">
        <label className="flex min-w-0 flex-[2_1_200px] flex-col gap-1.5 text-sm text-ink-soft">
          Tracking number (resi)
          <input className={field} value={resi} onChange={(e) => setResi(e.target.value)} disabled={busy}
            placeholder="e.g. 1102846637184921" autoComplete="off" required maxLength={60} />
        </label>
        <label className="flex min-w-0 flex-[1_1_140px] flex-col gap-1.5 text-sm text-ink-soft">
          Courier
          <input className={field} value={courier} onChange={(e) => setCourier(e.target.value)} disabled={busy}
            placeholder="JNE, J&T, LBC…" autoComplete="off" maxLength={60} />
        </label>
      </div>
      <button className="lp-btn w-full" disabled={busy || !resi.trim()}>{busy ? "Saving…" : "Save tracking number"}</button>
      <p className="text-sm text-ink-muted">
        This tells PayPal which parcel it is. To prove it arrived, also add the courier’s tracking page or delivery receipt.
      </p>
      {message && <p role={message.ok ? "status" : "alert"} className={`text-[15px] ${message.ok ? "text-green-ink" : "text-red-ink"}`}>{message.text}</p>}
    </form>
  );
}
