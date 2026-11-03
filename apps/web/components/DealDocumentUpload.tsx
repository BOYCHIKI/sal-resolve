"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { uploadDealDocument } from "@/app/actions";

const MAX_FILE = 10 * 1024 * 1024;
const FIELD = "min-h-11 rounded-xl border border-(--lp-line-strong) bg-(--lp-well) px-3 py-2 font-normal";

/** Sends one PO or invoice file. The worker reads it, and it comes back for the seller to confirm. */
export function DealDocumentUpload() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("PURCHASE_ORDER");
  const [dealRef, setDealRef] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function send() {
    if (!file) return setError("Choose a PDF or photo.");
    if (file.size >= MAX_FILE) return setError("Files must be smaller than 10 MB.");
    if (kind === "INVOICE" && !dealRef.trim()) return setError("Enter the PO number this invoice belongs to.");
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("deal_ref", dealRef.trim());
    const result = await uploadDealDocument(form);
    setBusy(false);
    if (!result.ok) return setError(result.code === "DEAL_NOT_FOUND" ? "No deal has that PO number." : result.message);
    setFile(null);
    setOpen(false);
    router.refresh();
  }

  if (!open) {
    return <button type="button" onClick={() => setOpen(true)} className="lp-btn text-[16px]">Add a document</button>;
  }
  return (
    <section aria-label="Add a document" className="lp-card flex w-full flex-col gap-4 p-5 sm:max-w-md">
      <label className="flex flex-col gap-1 text-[15px] font-semibold">
        What is it?
        <select value={kind} onChange={(e) => setKind(e.target.value)} className={FIELD}>
          <option value="PURCHASE_ORDER">Purchase order</option>
          <option value="INVOICE">Invoice</option>
        </select>
      </label>
      {kind === "INVOICE" && (
        <label className="flex flex-col gap-1 text-[15px] font-semibold">
          PO number
          <input value={dealRef} onChange={(e) => setDealRef(e.target.value)} className={FIELD} />
        </label>
      )}
      <div className="flex flex-col gap-1">
        <input id="deal-file" type="file" className="peer sr-only" accept="application/pdf,image/jpeg,image/png,image/gif"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        {/* the input is hidden, so its keyboard focus is drawn on the label */}
        <label htmlFor="deal-file" className="lp-btn-ghost cursor-pointer text-center text-[15px] peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-(--action-focus) peer-focus-visible:outline-solid">
          {file ? "Choose a different file" : "Choose a PDF or take a photo"}
        </label>
        {file && <span className="muted text-[14px] [overflow-wrap:anywhere]">{file.name}</span>}
      </div>
      {error && <p role="alert" className="text-[15px] text-red-ink">{error}</p>}
      <div className="flex items-center gap-3">
        <button type="button" onClick={send} disabled={busy} className="lp-btn text-[15px]">{busy ? "Sending…" : "Let SAL read it"}</button>
        <button type="button" onClick={() => setOpen(false)} className="muted px-2 py-2 text-[15px] hover:underline">Cancel</button>
      </div>
    </section>
  );
}
