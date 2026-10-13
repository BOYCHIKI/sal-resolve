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
      {status && <span className="text-xs text-zinc-500 dark:text-zinc-400" aria-live="polite">{status}</span>}
      <button
        onClick={onClick}
        disabled={busy}
        className="rounded-lg bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
      >
        {busy ? "Syncing…" : "Sync PayPal"}
      </button>
    </div>
  );
}
