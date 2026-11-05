"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { dealDocumentProgress, discardDealDocument, uploadDealDocument } from "@/app/actions";
import { Working } from "@/components/Working";
import type { DealDocument } from "@/lib/api";

const MAX_FILE = 10 * 1024 * 1024;
const ACCEPT = "application/pdf,image/jpeg,image/png,image/gif";
const POLL_MS = 2000;
const SLOW_AFTER_S = 120;   // reading usually takes 10 to 40 seconds

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

type Phase =
  | { step: "pick" }
  | { step: "uploading" }
  | { step: "reading"; id: string; since: string }
  | { step: "ready"; doc: DealDocument }
  | { step: "unreadable"; id: string }
  | { step: "gone" };

function size(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** What SAL couldn't find on the page. Two or more of these usually means the wrong file was chosen. */
function missing(doc: DealDocument): string[] {
  const p = doc.proposal;
  const number = doc.kind === "INVOICE" ? "the invoice number" : "the PO number";
  return [
    !p?.reference.value ? number : "",
    !p?.total.value ? "the total" : "",
    !p?.items.length ? "any items" : "",
  ].filter(Boolean);
}

/** Sends one file to SAL in a dialog and stays open while SAL reads it, so the seller sees each step. Without
 *  `dealRef` it is a purchase order that starts a deal; with it, that deal's invoice. When the reading is done, one
 *  button opens the document to check and confirm. */
export function DealDocumentUpload({ dealRef }: { dealRef?: string }) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const inputId = useId();
  const titleId = useId();
  const kind = dealRef ? "INVOICE" : "PURCHASE_ORDER";
  const need = NEEDS[kind];
  const name = kind === "INVOICE" ? "invoice" : "purchase order";
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>({ step: "pick" });
  const [error, setError] = useState("");
  const [slow, setSlow] = useState(false);

  // Follow the reading until the worker has an answer. A missed poll is simply tried again.
  const readingId = phase.step === "reading" ? phase.id : null;
  useEffect(() => {
    if (!readingId) return;
    const started = Date.now();
    let stopped = false;
    const timer = setInterval(async () => {
      if (Date.now() - started > SLOW_AFTER_S * 1000) setSlow(true);
      const progress = await dealDocumentProgress(readingId);
      if (stopped) return;
      if (progress.status === "NEEDS_CONFIRMATION" && progress.doc) setPhase({ step: "ready", doc: progress.doc });
      else if (progress.status === "UNREADABLE") setPhase({ step: "unreadable", id: readingId });
      else if (progress.status === "GONE") setPhase({ step: "gone" });
    }, POLL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [readingId]);

  function pick(f: File | null) {
    setError(f && f.size >= MAX_FILE ? "This file is over 10 MB. Try a smaller photo or PDF." : "");
    setFile(f && f.size < MAX_FILE ? f : null);
  }

  function reset() {
    setFile(null);
    setError("");
    setSlow(false);
    setPhase({ step: "pick" });
  }

  // Closing never loses the document: it waits under "To confirm", so that is where the page goes.
  function close() {
    const sent = phase.step !== "pick" && phase.step !== "uploading";
    dialog.current?.close();
    reset();
    if (sent) router.push("/deals?view=confirm", { scroll: false });
  }

  async function send() {
    if (!file) return;
    setError("");
    setPhase({ step: "uploading" });
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("deal_ref", dealRef ?? "");
    const result = await uploadDealDocument(form);
    if (!result.ok) {
      setPhase({ step: "pick" });
      return setError(result.code === "DEAL_NOT_FOUND" ? "That order is no longer in SAL." : result.message);
    }
    if (!result.id) {
      setPhase({ step: "pick" });
      return setError("SAL couldn’t start reading. Please try again.");
    }
    setPhase({ step: "reading", id: result.id, since: new Date().toISOString() });
  }

  async function tryAnother(id: string) {
    await discardDealDocument(id);   // the copy SAL couldn't use would only sit in the list
    reset();
    router.refresh();
  }

  function review(doc: DealDocument) {
    dialog.current?.close();
    reset();
    router.push(`/deals?view=confirm&open=${encodeURIComponent(doc.id)}`, { scroll: false });
  }

  return (
    <>
      <button type="button" onClick={() => dialog.current?.showModal()}
        className={dealRef ? "lp-btn-ghost whitespace-nowrap text-[15px]" : "lp-btn text-[16px]"}>
        {dealRef ? "Add invoice" : "Add a document"}
      </button>

      <dialog ref={dialog} aria-labelledby={titleId} onCancel={(e) => { e.preventDefault(); close(); }}
        className="m-auto max-h-[calc(100dvh-32px)] w-[min(640px,calc(100vw-32px))] overflow-y-auto rounded-3xl border border-(--lp-line) bg-white p-0 text-(--lp-ink) shadow-2xl backdrop:bg-slate-900/40 backdrop:backdrop-blur-sm">
        <div className="flex flex-col gap-5 p-6 sm:p-8">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-1">
              <h2 id={titleId} className="text-[24px] font-semibold tracking-tight">{need.title}</h2>
              {dealRef && <p className="muted text-[15px]">For order {dealRef}</p>}
            </div>
            <button type="button" onClick={close} aria-label="Close" className="muted -mr-2 grid h-10 w-10 place-items-center rounded-full text-[22px] hover:bg-(--lp-card-2)">×</button>
          </div>

          {(phase.step === "pick" || phase.step === "uploading") && (
            <>
              <div className="flex flex-col gap-3 rounded-2xl bg-(--lp-card-2) p-4 sm:p-5">
                <p className="text-[15px]">{need.what}</p>
                <div className="flex flex-col gap-1.5">
                  <span className="text-[14px] font-semibold">It should show</span>
                  <ul className="grid gap-x-5 gap-y-1.5 text-[15px] sm:grid-cols-2">
                    {need.shows.map((s) => (
                      <li key={s} className="flex gap-2"><Done /><span className="muted">{s}</span></li>
                    ))}
                  </ul>
                </div>
              </div>

              <input id={inputId} type="file" accept={ACCEPT} className="peer sr-only" disabled={phase.step === "uploading"}
                onChange={(e) => pick(e.target.files?.[0] ?? null)} />
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
                  Documents are read by our AI provider, OpenAI. You check each value before anything is saved.
                </p>
                <div className="flex items-center gap-2">
                  <button type="button" onClick={close} className="muted px-3 py-2 text-[15px] hover:underline">Cancel</button>
                  <button type="button" onClick={send} disabled={phase.step === "uploading" || !file} className="lp-btn text-[15px]">
                    {phase.step === "uploading" ? <Working label="Sending" /> : "Let SAL read it"}
                  </button>
                </div>
              </div>
            </>
          )}

          {phase.step === "reading" && (
            <div className="flex flex-col gap-4">
              <ol className="flex flex-col gap-3 rounded-2xl bg-(--lp-card-2) p-5 text-[15px]">
                <li className="flex items-center gap-2.5"><Done /> Sent to SAL</li>
                <li><Working label={`Reading the ${name}`} since={phase.since} /></li>
                <li className="muted flex items-center gap-2.5"><Pending /> You check what SAL read</li>
              </ol>
              <p className="muted text-[14px]">
                {slow ? "This is taking longer than usual. " : "Usually 10 to 40 seconds. "}
                You can close this; the document waits under To confirm.
              </p>
            </div>
          )}

          {phase.step === "ready" && <Ready doc={phase.doc} name={name} onReview={review} onAnother={tryAnother} />}

          {phase.step === "unreadable" && (
            <div className="flex flex-col gap-4">
              <p role="alert" className="rounded-2xl bg-red-bg p-4 text-[15px] text-red-ink">
                SAL couldn’t read this file. A sharp photo taken straight on, or the original PDF, usually works.
              </p>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <button type="button" onClick={close} className="muted px-3 py-2 text-[15px] hover:underline">Close</button>
                <button type="button" onClick={() => tryAnother(phase.id)} className="lp-btn text-[15px]">Try another file</button>
              </div>
            </div>
          )}

          {phase.step === "gone" && (
            <div className="flex flex-col gap-4">
              <p className="text-[15px]">This document was already handled.</p>
              <div className="flex justify-end"><button type="button" onClick={close} className="lp-btn text-[15px]">Close</button></div>
            </div>
          )}
        </div>
      </dialog>
    </>
  );
}

/** The reading is done: what SAL found, a warning when it looks like the wrong file, and the way to check it. */
function Ready({ doc, name, onReview, onAnother }: {
  doc: DealDocument; name: string; onReview: (doc: DealDocument) => void; onAnother: (id: string) => void;
}) {
  const gaps = missing(doc);
  const p = doc.proposal;
  const items = p?.items.length ?? 0;
  const wrongFile = gaps.length > 1;
  return (
    <div className="flex flex-col gap-4">
      <ol className="flex flex-col gap-3 rounded-2xl bg-(--lp-card-2) p-5 text-[15px]">
        <li className="flex items-center gap-2.5"><Done /> Sent to SAL</li>
        <li className="flex items-center gap-2.5">
          <Done /> Read {p?.reference.value ? <strong>{p.reference.value}</strong> : `the ${name}`}
          {items ? `, ${items} item${items === 1 ? "" : "s"}` : ""}
        </li>
        <li className="flex items-center gap-2.5 font-semibold"><Next /> Check each value, then confirm</li>
      </ol>
      {gaps.length > 0 && (
        <p role="alert" className="rounded-2xl bg-amber-bg p-4 text-[15px] text-amber-ink">
          SAL couldn’t find {gaps.join(", ")}. {wrongFile ? `Is this the right file? It may not be a ${name}.` : "You can type it in the next step."}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {wrongFile && (
          <button type="button" onClick={() => onAnother(doc.id)} className="muted px-3 py-2 text-[15px] hover:underline">Use another file</button>
        )}
        <button type="button" onClick={() => onReview(doc)} className="lp-btn text-[15px]">Check what SAL read</button>
      </div>
    </div>
  );
}

const Done = () => (
  <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--lp-blue)" strokeWidth="2.4"
    strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0"><path d="M5 12l5 5 9-10" /></svg>
);
const Pending = () => <span aria-hidden="true" className="h-[18px] w-[18px] shrink-0 rounded-full border-2 border-(--lp-line-strong)" />;
const Next = () => <span aria-hidden="true" className="h-[18px] w-[18px] shrink-0 rounded-full border-[5px] border-(--lp-blue)" />;
