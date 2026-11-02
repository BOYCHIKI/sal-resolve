"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { uploadDealDocument } from "@/app/actions";

const MAX_FILE = 10 * 1024 * 1024;

/** Sends one PO or invoice file. The worker reads it, and it comes back below for the seller to confirm. */
export function DealDocumentUpload() {
  const router = useRouter();
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
    router.refresh();
  }

  return (
    <section className="lp-card flex flex-wrap items-end gap-4 px-6 py-5">
      <label className="flex flex-col gap-1 text-[15px] font-semibold">
        Document
        <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded-lg border bg-white px-3 py-2 font-normal">
          <option value="PURCHASE_ORDER">Purchase order</option>
          <option value="INVOICE">Invoice</option>
        </select>
      </label>
      {kind === "INVOICE" && (
        <label className="flex flex-col gap-1 text-[15px] font-semibold">
          PO number
          <input value={dealRef} onChange={(e) => setDealRef(e.target.value)} className="rounded-lg border bg-white px-3 py-2 font-normal" />
        </label>
      )}
      <label className="flex flex-col gap-1 text-[15px] font-semibold">
        PDF or photo
        <input type="file" accept="application/pdf,image/jpeg,image/png,image/gif" className="font-normal"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <button type="button" onClick={send} disabled={busy} className="lp-btn text-[15px]">{busy ? "Sending…" : "Let SAL read it"}</button>
      {error && <p role="alert" className="w-full text-[15px] text-red-ink">{error}</p>}
    </section>
  );
}
