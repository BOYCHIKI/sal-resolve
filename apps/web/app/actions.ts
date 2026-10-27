"use server";

import { revalidatePath } from "next/cache";
import { api, type ActionResult } from "@/lib/api";

export async function startSync(): Promise<{ jobId: string } | { error: string }> {
  try {
    const job = await api.sync();
    return job ? { jobId: job.job_id } : { error: "Sync could not be queued." };
  } catch {
    return { error: "SAL can’t reach its server right now." };
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
    return { ok: false, code: "API_UNREACHABLE", message: "SAL can’t reach its server right now." };
  }
}

export async function submitDraft(disputeId: string, draftId: string): Promise<ActionResult> {
  try {
    const result = await api.submitDraft(draftId);
    revalidatePath(`/disputes/${disputeId}`);
    return result;
  } catch {
    return { ok: false, code: "API_UNREACHABLE", message: "SAL can’t reach its server right now." };
  }
}

export async function uploadEvidence(disputeId: string, form: FormData): Promise<ActionResult> {
  const file = form.get("file");
  const docType = form.get("doc_type");
  if (!(file instanceof File) || typeof docType !== "string") {
    return { ok: false, code: "BAD_REQUEST", message: "Choose a file and a document type." };
  }
  const outgoing = new FormData();
  outgoing.append("doc_type", docType);
  outgoing.append("file", file, file.name);
  try {
    const result = await api.uploadEvidence(disputeId, outgoing);
    revalidatePath(`/disputes/${disputeId}`);
    return result;
  } catch {
    return { ok: false, code: "API_UNREACHABLE", message: "SAL can’t reach its server right now." };
  }
}

export async function decideAction(id: string, decision: "approve" | "dismiss", payloadHash: string,
  disputeId: string | null): Promise<ActionResult> {
  try {
    const result = decision === "approve" ? await api.approveAction(id, payloadHash) : await api.dismissAction(id);
    revalidatePath("/disputes");
    if (disputeId) revalidatePath(`/disputes/${disputeId}`);
    return result;
  } catch {
    return { ok: false, code: "API_UNREACHABLE", message: "SAL can’t reach its server right now." };
  }
}
