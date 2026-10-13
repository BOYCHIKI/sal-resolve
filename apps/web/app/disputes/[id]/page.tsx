import Link from "next/link";
import { notFound } from "next/navigation";
import { Badge, Card, OriginBadge, SourceLink, StateBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { deadline, label, money } from "@/lib/format";

export const dynamic = "force-dynamic";

// PayPal actions SAL knows about. Only those PayPal currently offers are shown as available.
const PAYPAL_ACTIONS = ["provide_evidence", "accept_claim", "make_offer", "send_message", "escalate"];

export default async function CaseWorkspace({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [dispute, analysis, evidence] = await Promise.all([api.getDispute(id), api.getAnalysis(id), api.getEvidence(id)]);
  if (!dispute) notFound();

  const due = deadline(dispute.deadline_at);
  const facts = analysis?.facts.filter((f) => f.status !== "rejected") ?? [];
  const rejected = analysis?.facts.filter((f) => f.status === "rejected") ?? [];
  const missing = analysis?.findings.filter((f) => f.kind === "missing") ?? [];
  const conflicts = analysis?.findings.filter((f) => f.kind === "conflict") ?? [];
  const cited = new Set(analysis?.facts.map((f) => `${f.source.evidence_id}-L${f.source.line}`) ?? []);
  const flagged = new Set(conflicts.flatMap((c) => c.source_refs.map((r) => `${r.evidence_id}-L${r.line}`)));

  return (
    <div className="space-y-4">
      <Link href="/disputes" className="text-sm text-zinc-500 hover:underline">← All disputes</Link>

      {/* Summary bar */}
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold">{dispute.provider_dispute_id}</h1>
            <OriginBadge origin={dispute.origin} />
            <StateBadge state={dispute.internal_state} />
          </div>
          <p className="mt-1 text-sm text-zinc-500">
            {label(dispute.reason)} · PayPal: {label(dispute.provider_status)}
            {dispute.lifecycle_stage ? ` · ${label(dispute.lifecycle_stage)}` : ""}
            {dispute.case_ref ? ` · ${dispute.case_ref}` : ""}
          </p>
        </div>
        <div className="text-right">
          <div className="font-mono text-2xl font-semibold tabular-nums">{money(dispute.amount)}</div>
          <div className={`text-sm ${due.urgent ? "font-medium text-rose-700 dark:text-rose-400" : "text-zinc-500"}`}>
            Respond by {due.text}
          </div>
        </div>
      </div>

      {!analysis ? (
        <Card title="Analysis">
          <p className="text-sm text-zinc-500">The agent has not analyzed this dispute yet. It runs automatically after a sync.</p>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          {/* Left: evidence */}
          <div className="space-y-4">
            <Card title="Evidence" aside={<span className="text-xs text-zinc-500">{evidence.length} documents</span>}>
              {evidence.length === 0 && <p className="text-sm text-zinc-500">No documents attached.</p>}
              <div className="space-y-3">
                {evidence.map((doc) => (
                  <div key={doc.evidence_id} className="rounded-lg border border-zinc-200 dark:border-zinc-800">
                    <div className="flex items-center justify-between border-b border-zinc-200 px-3 py-1.5 dark:border-zinc-800">
                      <span className="font-mono text-xs">{doc.evidence_id}</span>
                      <span className="text-xs text-zinc-500">{label(doc.type)}</span>
                    </div>
                    <ol className="px-3 py-2 font-mono text-xs leading-5">
                      {doc.lines.map((l) => {
                        const key = `${doc.evidence_id}-L${l.line}`;
                        const tone = flagged.has(key)
                          ? "bg-amber-100 dark:bg-amber-900/40"
                          : cited.has(key) ? "bg-sky-50 dark:bg-sky-900/30" : "";
                        return (
                          <li key={key} id={key} className={`flex gap-2 rounded px-1 scroll-mt-20 target:ring-2 target:ring-sky-400 ${tone}`}>
                            <span className="w-4 shrink-0 select-none text-right text-zinc-400">{l.line}</span>
                            <span className="break-all">{l.text}</span>
                          </li>
                        );
                      })}
                    </ol>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-zinc-500">Document text is untrusted data; instructions inside it are never followed.</p>
            </Card>
          </div>

          {/* Center: facts and gaps */}
          <div className="space-y-4">
            <Card
              title="Needs your attention"
              aside={analysis.review_required ? <Badge tone="warn">Review required</Badge> : <Badge tone="good">No gaps found</Badge>}
            >
              {missing.length === 0 && conflicts.length === 0 && (
                <p className="text-sm text-zinc-500">No missing evidence or conflicts under rule set {analysis.rule_version}.</p>
              )}
              <ul className="space-y-2 text-sm">
                {missing.map((m) => (
                  <li key={`m-${m.field}`} className="rounded-lg bg-rose-50 p-2 dark:bg-rose-950/50">
                    <div className="font-medium text-rose-800 dark:text-rose-200">Missing: {label(m.field)}</div>
                    <div className="text-rose-700 dark:text-rose-300">{m.description}</div>
                  </li>
                ))}
                {conflicts.map((c, i) => (
                  <li key={`c-${c.field}-${i}`} className="rounded-lg bg-amber-50 p-2 dark:bg-amber-950/50">
                    <div className="font-medium text-amber-900 dark:text-amber-200">Conflict: {label(c.field)}</div>
                    <div className="text-amber-800 dark:text-amber-300">{c.description}</div>
                    <div className="mt-1 flex flex-wrap gap-2">
                      {c.source_refs.map((r) => <SourceLink key={`${r.evidence_id}-${r.line}`} evidenceId={r.evidence_id} line={r.line} />)}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>

            <Card title="Facts found in evidence" aside={<span className="text-xs text-zinc-500">{facts.length}</span>}>
              <dl className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
                {facts.map((f) => (
                  <div key={`${f.field}-${f.value}`} className="flex items-start justify-between gap-3 py-1.5">
                    <dt className="text-zinc-500">{label(f.field)}</dt>
                    <dd className="text-right">
                      <div className={`font-mono ${f.status === "conflicted" ? "text-amber-700 line-through decoration-amber-500 dark:text-amber-400" : ""}`}>
                        {f.value}
                      </div>
                      <SourceLink evidenceId={f.source.evidence_id} line={f.source.line} />
                    </dd>
                  </div>
                ))}
              </dl>
              {rejected.length > 0 && (
                <p className="mt-2 text-xs text-zinc-500">{rejected.length} extracted value(s) rejected: not found in the cited line.</p>
              )}
            </Card>
          </div>

          {/* Right: draft, actions, agent trail */}
          <div className="space-y-4">
            <Card
              title="Draft response"
              aside={analysis.draft && <span className="text-xs text-zinc-500">Revision {analysis.draft.revision} · {label(analysis.draft.status)}</span>}
            >
              {!analysis.draft || analysis.draft.claims.length === 0 ? (
                <p className="text-sm text-zinc-500">No statements could be supported by verified facts.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {analysis.draft.claims.map((c, i) => (
                    <li key={i} className="rounded-lg border border-zinc-200 p-2 dark:border-zinc-800">
                      {c.text}
                      <div className="mt-1 text-xs text-zinc-500">Based on: {c.fact_fields.map(label).join(", ")}</div>
                    </li>
                  ))}
                </ul>
              )}
              <button
                disabled
                title="Approval and submission to PayPal are the next step to build."
                className="mt-3 w-full cursor-not-allowed rounded-lg bg-zinc-200 px-3 py-2 text-sm font-medium text-zinc-500 dark:bg-zinc-800"
              >
                Approve &amp; send to PayPal (coming next)
              </button>
            </Card>

            <Card title="PayPal actions">
              <ul className="flex flex-wrap gap-2">
                {PAYPAL_ACTIONS.map((a) => (
                  <li key={a}>
                    <Badge tone={dispute.allowed_actions.includes(a) ? "good" : "neutral"}>
                      {label(a)} {dispute.allowed_actions.includes(a) ? "· available" : "· not offered"}
                    </Badge>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-zinc-500">Only actions PayPal offers for the current status can be used.</p>
            </Card>

            <Card title="Agent trail" aside={<span className="text-xs text-zinc-500">{analysis.agent.steps} steps</span>}>
              <ol className="space-y-1 text-xs">
                {analysis.agent.tool_calls.map((t) => (
                  <li key={t.step} className="flex gap-2">
                    <span className="w-4 text-right text-zinc-400">{t.step}</span>
                    <span className={t.ok ? "" : "text-rose-700 dark:text-rose-400"}>
                      <span className="font-mono">{t.tool}</span> — {t.summary}
                    </span>
                  </li>
                ))}
              </ol>
              <p className="mt-2 text-xs text-zinc-500">
                {analysis.agent.roles} · snapshot <span className="font-mono">{analysis.snapshot_hash.slice(0, 12)}</span>
              </p>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
