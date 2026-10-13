"use server";

import { revalidatePath } from "next/cache";
import { api, type ActionResult } from "@/lib/api";

export async function startSync(): Promise<{ jobId: string } | { error: string }> {
  try {
    const job = await api.sync();
    return job ? { jobId: job.job_id } : { error: "Sync could not be queued." };
  } catch {
    return { error: "SAL API is not reachable." };
  }
}

export async function jobState(jobId: string): Promise<{ state: string; error: string | null }> {
  const job = await api.getJob(jobId);
  if (job && (job.state === "SUCCEEDED" || job.state === "FAILED")) revalidatePath("/disputes");
  return { state: job?.state ?? "UNKNOWN", error: job?.error ?? null };
}

export async function approveDraft(disputeId: string, draftId: string, revision: number, snapshotHash: string): Promise<ActionResult> {
  try {
    const result = await api.approveDraft(draftId, revision, snapshotHash);
    revalidatePath(`/disputes/${disputeId}`);
    return result;
  } catch {
    return { ok: false, code: "API_UNREACHABLE", message: "SAL API is not reachable." };
  }
}

export async function submitDraft(disputeId: string, draftId: string): Promise<ActionResult> {
  try {
    const result = await api.submitDraft(draftId);
    revalidatePath(`/disputes/${disputeId}`);
    return result;
  } catch {
    return { ok: false, code: "API_UNREACHABLE", message: "SAL API is not reachable." };
  }
}
