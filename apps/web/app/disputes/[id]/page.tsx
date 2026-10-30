import { notFound } from "next/navigation";
import { ActionCard } from "@/components/ActionCard";
import { AddTracking } from "@/components/AddTracking";
import { AppHeader } from "@/components/AppHeader";
import { DraftActions } from "@/components/DraftActions";
import { UploadEvidence } from "@/components/UploadEvidence";
import { api } from "@/lib/api";
import { caseTypeOf, docName, docRef, dueText, explain, origin, propositionLook, propositionTitle, readableFacts, readiness,
  stageOf, summarySentence, type Tone } from "@/lib/plain";

export const dynamic = "force-dynamic";

const BOX: Record<Tone, string> = {
  red: "bg-red-bg text-red-ink",
  amber: "bg-amber-bg text-amber-ink",
  blue: "bg-blue-bg text-blue-ink",
  green: "bg-green-bg text-green-ink",
  grey: "bg-grey-bg text-grey-ink",
};

type StepState = "done" | "current" | "todo";

function Progress({ steps }: { steps: { label: string; state: StepState }[] }) {
  return (
    <ol aria-label="Progress" className="grid gap-2.5 sm:grid-cols-4">
      {steps.map((s, i) => {
        const look = s.state === "done" ? "bg-green-bg text-green-ink" : s.state === "current" ? "bg-amber-bg font-semibold text-amber-ink" : "bg-grey-bg text-ink-soft";
        return (
          <li key={s.label} className={`flex items-center gap-2.5 rounded-2xl px-3.5 py-3 text-[15px] ${look}`} aria-current={s.state === "current" ? "step" : undefined}>
            <span aria-hidden="true" className="inline-flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border-2 border-current text-sm font-semibold">
              {s.state === "done" ? "✓" : i + 1}
            </span>
            {s.label}
            <span className="sr-only">{s.state === "done" ? " (done)" : s.state === "current" ? " (current step)" : ""}</span>
          </li>
        );
      })}
    </ol>
  );
}

export default async function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [dispute, analysis, evidence, suggestions] = await Promise.all([
    api.getDispute(id), api.getAnalysis(id), api.getEvidence(id), api.listActions(id)]);
  if (!dispute) notFound();

  const currency = dispute.amount.currency;
  const type = caseTypeOf(dispute);
  const stage = stageOf(dispute);
  const due = dueText(dispute.deadline_at);
  const { headline, detail } = summarySentence(dispute, analysis);
  const findings = analysis?.findings ?? [];
  const facts = analysis ? readableFacts(analysis.facts, currency) : [];
  const flaggedDocs = new Set(findings.flatMap((f) => f.source_refs.map((r) => r.evidence_id)));
  const draft = analysis?.draft;
  const sent = dispute.internal_state === "SUBMITTED";
  const approved = draft?.status === "APPROVED" || draft?.status === "SUBMIT_FAILED";
  const sending = draft?.status === "SUBMITTING";
  // Documents can be added until the reply is on its way; PayPal cases also need PayPal to still accept them.
  const canAddDocuments = !sent && !sending &&
    (dispute.origin !== "PAYPAL_SANDBOX" || dispute.allowed_actions.includes("provide_evidence"));
  const deadlineDate = dispute.deadline_at ? due.text.replace(/^Reply by /, "").split(" · ")[0] : "None";

  const steps: { label: string; state: StepState }[] = [
    { label: "Documents checked", state: analysis ? "done" : "current" },
    {
      label: findings.length ? `Check ${findings.length} detail${findings.length > 1 ? "s" : ""}` : "Nothing to check",
      state: !analysis ? "todo" : findings.length && draft?.status === "DRAFT" ? "current" : "done",
    },
    { label: "Approve the reply", state: sent || approved ? "done" : analysis && !findings.length ? "current" : "todo" },
    { label: "Send to PayPal", state: sent ? "done" : approved ? "current" : "todo" },
  ];
  const conflictDate = findings.some((f) => f.field === "delivery_date");
  const read = analysis?.agent.tool_calls.filter((t) => t.tool === "read_evidence" && t.ok).length ?? 0;
  const claimCount = draft?.claims.length ?? 0;

  return (
    <div className="lp sky min-h-screen">
      <AppHeader back />
      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 pb-20 pt-8">
        <section aria-label="What happened" data-reveal className="lp-card flex flex-col gap-6 p-6 sm:p-8">
          <div className="flex flex-wrap justify-between gap-5">
            <div className="flex max-w-2xl flex-col gap-2.5">
              <span className="lp-label self-start">{origin(dispute.origin)}</span>
              <span className="flex flex-wrap gap-2 text-sm font-semibold">
                <span className={`rounded-full px-3 py-1 ${BOX[type.tone]}`}>{type.title}</span>
                {stage && <span className={`rounded-full px-3 py-1 ${BOX[stage.tone]}`}>{stage.label}</span>}
              </span>
              {dispute.channel === "EXTERNAL" && (
                <p className="text-[15px] font-semibold text-red-ink">The buyer’s bank decides, and PayPal Seller Protection does not apply.</p>
              )}
              <h1 className="display text-[30px] sm:text-[44px]">{headline}</h1>
              <p className="text-lg text-ink-soft">{detail}</p>
            </div>
            <div className={`flex flex-col gap-1 self-start rounded-[20px] px-5 py-4 ${due.urgent ? BOX.red : BOX.grey}`}>
              <span className="text-sm">{dispute.deadline_at ? "Reply to PayPal by" : "Deadline"}</span>
              <span className="text-2xl font-semibold">{deadlineDate}</span>
              {due.short && <span className="text-sm">{due.short}</span>}
            </div>
          </div>
          <Progress steps={steps} />
        </section>

        {suggestions.length > 0 && (
          <section aria-label="SAL suggests" className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold">SAL suggests</h2>
            {suggestions.map((a) => <ActionCard key={a.id} action={a} caseLink={false} />)}
          </section>
        )}

        {analysis?.assessment && (() => {
          const a = analysis.assessment;
          const r = readiness(a.readiness);
          return (
            <section aria-label="What your documents prove" data-reveal className="lp-card flex flex-col gap-4 p-6 sm:p-8">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="display text-2xl sm:text-3xl">What your documents prove</h2>
                <span className={`rounded-full px-4 py-1.5 text-[15px] font-semibold ${BOX[r.tone]}`}>{r.label}</span>
              </div>
              {due.urgent && !sent && (
                <p role="alert" className={`rounded-[18px] px-5 py-3.5 text-[17px] font-semibold ${BOX.red}`}>
                  {due.text}. If PayPal gets no reply by then, it closes the case in the buyer’s favour.
                </p>
              )}
              {!sent && (
                <p className={`rounded-[18px] px-5 py-3.5 text-[17px] ${BOX[r.tone]}`}>
                  <span className="font-semibold">Next: </span>{a.next_action}
                </p>
              )}
              <ul className="flex flex-col gap-2.5">
                {a.propositions.map((p) => {
                  const look = propositionLook(p.status);
                  const docs = [...new Set(p.sources.map((src) => src.evidence_id))];
                  return (
                    <li key={p.id} className="flex items-start gap-3.5 rounded-[18px] bg-(--lp-card-2) px-4 py-3.5">
                      <span aria-hidden="true" className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[17px] font-bold ${BOX[look.tone]}`}>
                        {look.mark}
                      </span>
                      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="flex flex-wrap items-baseline gap-x-2.5">
                          <span className="text-[17px] font-semibold">{propositionTitle(p.id)}</span>
                          <span className="text-sm text-ink-muted">{look.word}</span>
                        </span>
                        <span className="text-[15px] text-ink-soft">{p.reason}</span>
                        {docs.length > 0 && (
                          <span className="flex flex-wrap gap-4 text-[14px]">
                            {docs.map((evId) => {
                              const doc = evidence.find((d) => d.evidence_id === evId);
                              return (
                                <a key={evId} href={`#${evId}`} className="text-(--lp-mint) underline-offset-2 hover:underline">
                                  See {docRef(doc?.type, doc?.origin)}
                                </a>
                              );
                            })}
                          </span>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
              <p className="text-sm text-ink-muted">SAL checks what your documents show. It never predicts how PayPal will decide.</p>
            </section>
          );
        })()}

        <div className="flex flex-wrap items-start gap-6">
          <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-6">
            {analysis && findings.length > 0 && (
              <section aria-label="Details to check" data-reveal className="lp-card flex flex-col gap-3.5 p-6">
                <h2 className="text-[22px]">{findings.length === 1 ? "1 detail to check" : `${findings.length} details to check`}</h2>
                {findings.map((f, i) => {
                  const e = explain(f, analysis.facts, currency);
                  const docs = [...new Set(f.source_refs.map((r) => r.evidence_id))];
                  return (
                    <div key={`${f.field}-${i}`} className={`flex flex-col gap-2 rounded-[18px] px-5 py-4 ${BOX[e.tone]}`}>
                      <span className="text-[17px] font-semibold">{e.title}</span>
                      <span>{e.body}</span>
                      {docs.length > 0 && (
                        <span className="flex flex-wrap gap-4 text-[15px]">
                          {docs.map((evId) => (
                            <a key={evId} href={`#${evId}`} className="text-(--lp-mint) underline-offset-2 hover:underline">
                              See {docRef(evidence.find((d) => d.evidence_id === evId)?.type, evidence.find((d) => d.evidence_id === evId)?.origin)}
                            </a>
                          ))}
                        </span>
                      )}
                    </div>
                  );
                })}
              </section>
            )}

            <section aria-label="Your reply" data-reveal className="lp-card flex flex-col gap-4 p-6">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="display text-2xl sm:text-3xl">Your reply to PayPal</h2>
                <span className="text-sm text-ink-muted">Written by SAL from your documents</span>
              </div>
              {!draft || claimCount === 0 ? (
                <p className="text-ink-soft">SAL couldn’t back any statement with your documents yet. Add the missing documents and it will write the reply.</p>
              ) : (
                <div className="rounded-[18px] border border-(--lp-line) bg-(--lp-well) px-5 py-4 text-[17px] leading-relaxed">
                  {draft.claims.map((c, i) => <p key={i} className="mb-2 last:mb-0">{c.text}</p>)}
                  {conflictDate && <p className="mt-2 text-ink-muted">The delivery date will be added once you confirm it above.</p>}
                </div>
              )}
              {claimCount > 0 && <p className="text-sm text-ink-muted">Every sentence comes from one of your documents.</p>}
              {draft && analysis && (
                <DraftActions
                  disputeId={dispute.id}
                  draftId={draft.id}
                  revision={draft.revision}
                  snapshotHash={analysis.snapshot_hash}
                  status={draft.status}
                  sandbox={dispute.origin === "PAYPAL_SANDBOX"}
                  canProvideEvidence={dispute.allowed_actions.includes("provide_evidence")}
                  openItems={findings.length}
                  note={draft.submit_note}
                />
              )}
            </section>
          </div>

          <div className="flex min-w-0 flex-[1_1_340px] flex-col gap-6">
            {facts.length > 0 && (
              <section aria-label="What your documents show" data-reveal className="lp-card flex flex-col p-6">
                <h2 className="mb-2.5 text-xl">What your documents show</h2>
                <dl>
                  {facts.map((f) => (
                    <div key={f.label} className="flex justify-between gap-3 border-t border-(--lp-line) py-2.5 text-[15px]">
                      <dt className="text-ink-soft">{f.label}</dt>
                      <dd className={`text-right font-medium ${f.doubtful ? "text-amber-ink" : ""}`}>
                        {f.value}
                        {f.doubtful && <span className="block text-[13px] font-normal">please check</span>}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}

            <section aria-label="Documents" data-reveal className="lp-card flex flex-col gap-2.5 p-6">
              <h2 className="text-xl">Documents ({evidence.length})</h2>
              {evidence.length === 0 && <p className="text-ink-soft">No documents yet.</p>}
              {canAddDocuments && dispute.reason === "ITEM_NOT_RECEIVED" && <AddTracking disputeId={dispute.id} />}
              {canAddDocuments && <UploadEvidence disputeId={dispute.id} analysisId={analysis?.analysis_id ?? null} />}
              {evidence.map((doc) => (
                <details key={doc.evidence_id} id={doc.evidence_id} className="scroll-mt-24 rounded-2xl bg-(--lp-card-2) open:bg-(--lp-well)">
                  <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3.5 px-3.5 py-2.5">
                    <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--lp-mint)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></svg>
                    <span className="flex flex-1 flex-col">
                      <span className="flex flex-wrap items-center gap-2 font-medium">
                        {docName(doc.type, doc.origin)}
                        {doc.origin === "PAYPAL_API" && (
                          <span className="rounded-full bg-blue-bg px-2.5 py-0.5 text-[12px] font-semibold text-blue-ink">From PayPal</span>
                        )}
                      </span>
                      <span className={`text-[13px] ${flaggedDocs.has(doc.evidence_id) ? "text-amber-ink" : "text-ink-muted"}`}>
                        {flaggedDocs.has(doc.evidence_id) ? "Has a detail to check" : "Looks consistent"}
                      </span>
                    </span>
                    <span aria-hidden="true" className="text-ink-muted">›</span>
                  </summary>
                  <div className="border-t border-(--lp-line) px-4 py-3 text-sm leading-6 text-ink-soft">
                    {doc.lines.map((l) => <p key={l.line}>{l.text}</p>)}
                    <p className="mt-2 text-xs text-ink-muted">Shown exactly as received. Any instructions inside are never followed.</p>
                  </div>
                </details>
              ))}
            </section>

            {analysis && (
              <section aria-label="How SAL prepared this" data-reveal className="lp-dashed flex flex-col gap-2.5 rounded-[20px] p-6">
                <h2 className="text-[17px]">How SAL prepared this</h2>
                <p className="text-[15px] text-ink-soft">
                  Read {read} document{read === 1 ? "" : "s"}, found {facts.length} details, flagged {findings.length} to check,
                  and wrote {claimCount} sentence{claimCount === 1 ? "" : "s"} using only what the documents say.
                  SAL can’t send anything or issue refunds on its own.
                </p>
              </section>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
