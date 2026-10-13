"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { jobState, startSync } from "@/app/actions";
import { primaryButton } from "@/components/ui";

export function SyncButton() {
  const router = useRouter();
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onClick() {
    setBusy(true);
    setStatus("Queued…");
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
        setStatus("Synced with PayPal Sandbox.");
        router.refresh();
        break;
      }
      if (job.state === "FAILED") {
        setStatus(`Sync failed: ${job.error ?? "unknown error"}`);
        break;
      }
      setStatus(job.state === "RUNNING" ? "Syncing…" : "Queued… (is the worker running?)");
    }
    setBusy(false);
  }

  return (
    <div className="flex items-center gap-3">
      {status && <span className="text-xs text-ink-muted" aria-live="polite">{status}</span>}
      <button onClick={onClick} disabled={busy} className={primaryButton}>
        {busy ? "Syncing…" : "Sync PayPal"}
      </button>
    </div>
  );
}
