"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { checkPayPalInvoice } from "@/app/actions";

const REFUSED: Record<string, string> = {
  PAYPAL_NOT_CONNECTED: "This business has no PayPal account connected.",
  PAYPAL_INVOICE_NOT_FOUND: "PayPal has no invoice with that ID in this account.",
  PAYPAL_UNAVAILABLE: "PayPal didn’t answer. Please try again in a moment.",
  DEAL_NOT_FOUND: "That order is no longer in SAL.",
};

/** Checks the seller's invoice straight from PayPal (Invoicing API) against the order, before they send it. */
export function PayPalInvoiceCheck({ dealRef }: { dealRef: string }) {
  const router = useRouter();
  const inputId = useId();
  const [open, setOpen] = useState(false);
  const [invoiceId, setInvoiceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function check() {
    setBusy(true);
    setError("");
    const result = await checkPayPalInvoice(dealRef, invoiceId.trim());
    setBusy(false);
    if (!result.ok) return setError(REFUSED[result.code] ?? result.message);
    setOpen(false);
    setInvoiceId("");
    router.refresh();
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="muted whitespace-nowrap text-[15px] font-semibold hover:text-(--lp-ink) hover:underline">
        or check a PayPal invoice
      </button>
    );
  }
  return (
    <div className="flex w-full flex-col gap-2">
      <label htmlFor={inputId} className="text-[14px] font-semibold">PayPal invoice ID</label>
      <div className="flex flex-wrap items-center gap-2">
        <input id={inputId} value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)} placeholder="INV2-XXXX-XXXX-XXXX-XXXX"
          autoFocus maxLength={40} className="min-h-11 w-72 max-w-full rounded-xl border border-(--lp-line-strong) bg-white px-3 font-mono text-[14px]" />
        <button type="button" onClick={check} disabled={busy || invoiceId.trim().length < 4} className="lp-btn text-[15px]">
          {busy ? "Reading from PayPal…" : "Check it"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="muted px-2 text-[14px] hover:underline">Cancel</button>
      </div>
      <p className="muted text-[13px]">SAL reads the invoice from PayPal and checks it against this order before you send it. Name each PayPal item with its item code.</p>
      {error && <p role="alert" className="text-[14px] text-red-ink">{error}</p>}
    </div>
  );
}
