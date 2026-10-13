"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { jobState, startSync } from "@/app/actions";

export function SyncButton() {
  const router = useRouter();
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onClick() {
    setBusy(true);
    setStatus("Starting…");
    const started = await startSync();
    if ("error" in started) {
      setStatus(started.error);
      setBusy(false);
      return;
    }
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const job = await jobState(started.jobId);
      if (job.state === "SUCCEEDED") {
        setStatus("Up to date.");
        router.refresh();
        break;
      }
      if (job.state === "FAILED") {
        setStatus("PayPal didn’t answer. Please try again in a minute.");
        break;
      }
      setStatus(job.state === "RUNNING" ? "Checking PayPal…" : "Waiting to start…");
    }
    setBusy(false);
  }

  return (
    <div className="flex items-center gap-3">
      {status && <span className="text-sm text-ink-soft" aria-live="polite">{status}</span>}
      <button onClick={onClick} disabled={busy} className="btn-primary">
        {busy ? "Checking PayPal…" : "Check PayPal for new cases"}
      </button>
    </div>
  );
}
