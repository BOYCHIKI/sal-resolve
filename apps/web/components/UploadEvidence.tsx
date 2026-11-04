"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { uploadEvidence } from "@/app/actions";
import { DOCS } from "@/lib/plain";

const MAX_BYTES = 10 * 1024 * 1024;

const MESSAGES: Record<string, string> = {
  AUTH_REQUIRED: "Your session ended. Sign in again to continue.",
  UNSUPPORTED_TYPE: "Only PDF, JPG, PNG or GIF files can be added.",
  DUPLICATE_FILE: "This file is already attached.",
  FILE_TOO_LARGE: "This file is larger than 10 MB.",
  CASE_TOO_LARGE: "This case already holds 50 MB of documents.",
  EMPTY_FILE: "This file is empty.",
  PDF_UNREADABLE: "This PDF can’t be opened. Try saving it again or add a picture instead.",
  API_UNREACHABLE: "SAL can’t reach its server right now. Please try again in a moment.",
};

type Result = { name: string; ok: boolean; text: string };

export function UploadEvidence({ disputeId, analysisId }: { disputeId: string; analysisId: string | null }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [docType, setDocType] = useState("delivery_proof");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const [waitingFor, setWaitingFor] = useState<string | null | undefined>(undefined);

  // After an upload SAL re-reads every document; refresh until the new analysis shows up (max ~60 s).
  useEffect(() => {
    if (waitingFor === undefined) return;
    if (analysisId !== waitingFor) { setWaitingFor(undefined); return; }
    let ticks = 0;
    const timer = setInterval(() => {
      ticks += 1;
      router.refresh();
      if (ticks >= 20) { clearInterval(timer); setWaitingFor(undefined); }
    }, 3000);
    return () => clearInterval(timer);
  }, [waitingFor, analysisId, router]);

  async function send(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    const done: Result[] = [];
    for (const file of Array.from(files)) {  // one file per call keeps each request under the size limit
      if (file.size >= MAX_BYTES) {
        done.push({ name: file.name, ok: false, text: MESSAGES.FILE_TOO_LARGE });
        setResults([...done]);
        continue;
      }
      const form = new FormData();
      form.append("doc_type", docType);
      form.append("file", file);
      const r = await uploadEvidence(disputeId, form);
      done.push({ name: file.name, ok: r.ok, text: r.ok ? "Added" : MESSAGES[r.code] ?? "Couldn’t add this file. Please try again." });
      setResults([...done]);
    }
    setBusy(false);
    if (input.current) input.current.value = "";
    if (done.some((r) => r.ok)) setWaitingFor(analysisId);
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-3 rounded-2xl bg-grey-bg p-4">
      <p className="font-medium">Add a document</p>
      <label className="flex flex-col gap-1.5 text-sm text-ink-soft">
        What is it?
        <select className="rounded-xl border border-(--lp-line) bg-(--lp-well) px-3 py-2.5 text-[15px] text-ink"
          value={docType} onChange={(e) => setDocType(e.target.value)} disabled={busy}>
          {Object.entries(DOCS).filter(([value]) => value !== "seller_shipment" && value !== "packing_proof" && value !== "deal_record")  // added elsewhere
            .map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <input ref={input} id="evidence-file" type="file" multiple className="sr-only" disabled={busy}
        accept="application/pdf,image/png,image/jpeg,image/gif" onChange={(e) => send(e.target.files)} />
      <label htmlFor="evidence-file" aria-disabled={busy}
        className={`lp-btn w-full cursor-pointer text-center text-[16px] ${busy ? "pointer-events-none opacity-60" : ""}`}>
        {busy ? "Adding…" : "Choose files"}
      </label>
      <p className="text-xs text-ink-muted">PDF, JPG, PNG or GIF, up to 10 MB each. Files stay private and are only sent to PayPal when you press “Send to PayPal”.</p>
      {results.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm" aria-live="polite">
          {results.map((r, i) => (
            <li key={i} className={r.ok ? "text-green-ink" : "text-red-ink"}>
              <span className="font-medium">{r.name}</span>: {r.text}
            </li>
          ))}
        </ul>
      )}
      {waitingFor !== undefined && <p className="text-sm text-ink-soft" role="status">SAL is reading your documents and will update the reply…</p>}
    </div>
  );
}
