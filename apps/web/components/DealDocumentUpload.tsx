"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";
import { uploadDealDocument } from "@/app/actions";

const MAX_FILE = 10 * 1024 * 1024;
const ACCEPT = "application/pdf,image/jpeg,image/png,image/gif";

// What SAL compares, so the seller knows which document to pick before choosing a file.
const NEEDS = {
  PURCHASE_ORDER: {
    title: "Add a purchase order",
    what: "The buyer’s purchase order (PO): the document where they say what they want to buy. A signed quote or an order confirmation also works if it shows the same details.",
    shows: ["PO number and the buyer’s name", "Each item: code or name, quantity and unit price", "The total and the currency", "The delivery address, for goods"],
  },
  INVOICE: {
    title: "Add the invoice",
    what: "The invoice you are sending the buyer for this order. SAL checks it line by line against the purchase order.",
    shows: ["Invoice number and date", "Each item: code or name, quantity and unit price", "Shipping, tax and the total", "The delivery address, for goods"],
  },
} as const;

function size(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Sends one file to SAL in a dialog. Without `dealRef` it is a purchase order that starts a deal; with it, that
 *  deal's invoice. The worker reads it, and it comes back for the seller to confirm. */
export function DealDocumentUpload({ dealRef }: { dealRef?: string }) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const inputId = useId();
  const titleId = useId();
  const kind = dealRef ? "INVOICE" : "PURCHASE_ORDER";
  const need = NEEDS[kind];
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function pick(f: File | null) {
    setError(f && f.size >= MAX_FILE ? "This file is over 10 MB. Try a smaller photo or PDF." : "");
    setFile(f && f.size < MAX_FILE ? f : null);
  }

  function close() {
    dialog.current?.close();
    setFile(null);
    setError("");
  }

  async function send() {
    if (!file) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("deal_ref", dealRef ?? "");
    const result = await uploadDealDocument(form);
    setBusy(false);
    if (!result.ok) return setError(result.code === "DEAL_NOT_FOUND" ? "That order is no longer in SAL." : result.message);
    close();
    router.refresh();
  }

  return (
    <>
      <button type="button" onClick={() => dialog.current?.showModal()}
        className={dealRef ? "lp-btn-ghost whitespace-nowrap text-[15px]" : "lp-btn text-[16px]"}>
        {dealRef ? "Add invoice" : "Add a document"}
      </button>

      <dialog ref={dialog} aria-labelledby={titleId} onClose={() => { setFile(null); setError(""); }}
        className="m-auto max-h-[calc(100dvh-32px)] w-[min(640px,calc(100vw-32px))] overflow-y-auto rounded-3xl border border-(--lp-line) bg-white p-0 text-(--lp-ink) shadow-2xl backdrop:bg-slate-900/40 backdrop:backdrop-blur-sm">
        <div className="flex flex-col gap-5 p-6 sm:p-8">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-1">
              <h2 id={titleId} className="text-[24px] font-semibold tracking-tight">{need.title}</h2>
              {dealRef && <p className="muted text-[15px]">For order {dealRef}</p>}
            </div>
            <button type="button" onClick={close} aria-label="Close" className="muted -mr-2 grid h-10 w-10 place-items-center rounded-full text-[22px] hover:bg-(--lp-card-2)">×</button>
          </div>

          <div className="flex flex-col gap-3 rounded-2xl bg-(--lp-card-2) p-4 sm:p-5">
            <p className="text-[15px]">{need.what}</p>
            <div className="flex flex-col gap-1.5">
              <span className="text-[14px] font-semibold">It should show</span>
              <ul className="grid gap-x-5 gap-y-1.5 text-[15px] sm:grid-cols-2">
                {need.shows.map((s) => (
                  <li key={s} className="flex gap-2">
                    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--lp-blue)" strokeWidth="2.2"
                      strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0"><path d="M5 12l5 5 9-10" /></svg>
                    <span className="muted">{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <input id={inputId} type="file" accept={ACCEPT} className="peer sr-only" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
          {/* The input is hidden, so the drop area is its label and shows its keyboard focus. */}
          <label htmlFor={inputId}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0] ?? null); }}
            className={`flex cursor-pointer flex-col items-center gap-1.5 rounded-2xl border-2 border-dashed px-4 py-9 text-center transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-(--action-focus) peer-focus-visible:outline-solid ${dragging ? "border-(--lp-blue) bg-blue-bg" : "border-(--lp-line-strong) hover:border-(--lp-blue)"}`}>
            {file ? (
              <>
                <span className="font-semibold [overflow-wrap:anywhere]">{file.name}</span>
                <span className="muted text-[14px]">{size(file.size)} · <span className="text-(--lp-blue) underline underline-offset-2">Choose another</span></span>
              </>
            ) : (
              <>
                <svg aria-hidden="true" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--lp-blue)" strokeWidth="1.8"
                  strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></svg>
                <span className="text-[16px] font-semibold">Drop the file here, or <span className="text-(--lp-blue) underline underline-offset-2">choose one</span></span>
                <span className="muted text-[14px]">PDF or a photo (JPG, PNG), up to 10 MB</span>
              </>
            )}
          </label>

          {error && <p role="alert" className="text-[15px] text-red-ink">{error}</p>}

          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="muted text-[13px] sm:max-w-[300px]">
              SAL reads it with an AI model (OpenAI) and shows you each value to check. Nothing is saved until you confirm.
            </p>
            <div className="flex items-center gap-2">
              <button type="button" onClick={close} className="muted px-3 py-2 text-[15px] hover:underline">Cancel</button>
              <button type="button" onClick={send} disabled={busy || !file} className="lp-btn text-[15px]">
                {busy ? "Sending…" : "Let SAL read it"}
              </button>
            </div>
          </div>
        </div>
      </dialog>
    </>
  );
}
