import Link from "next/link";
import { SyncButton } from "@/components/SyncButton";
import { OriginBadge, StateBadge } from "@/components/ui";
import { api, type Dispute } from "@/lib/api";
import { deadline, label, money } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DisputesPage() {
  let disputes: Dispute[] = [];
  let error: string | null = null;
  try {
    disputes = await api.listDisputes();
  } catch {
    error = "The SAL API is not reachable. Start it with `uvicorn app.main:app` in apps/api.";
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[28px] leading-tight text-ink">Disputes</h1>
          <p className="text-sm text-ink-muted">Sorted by response deadline. Amounts are shown in their original currency.</p>
        </div>
        <SyncButton />
      </div>

      {error && <p className="rounded-card bg-bad-bg p-4 text-sm text-bad-ink">{error}</p>}

      {!error && disputes.length === 0 && (
        <p className="rounded-card border border-dashed border-hairline bg-surface p-10 text-center text-sm text-ink-muted">
          No disputes yet. Press <strong>Sync PayPal</strong>, or seed demo cases with <code>python -m app.seed_demo</code>.
        </p>
      )}

      {disputes.length > 0 && (
        <div className="overflow-x-auto rounded-card border border-hairline bg-surface">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-hairline text-xs text-ink-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Dispute</th>
                <th className="px-4 py-2 font-medium">Reason</th>
                <th className="px-4 py-2 text-right font-medium">Amount</th>
                <th className="px-4 py-2 font-medium">PayPal status</th>
                <th className="px-4 py-2 font-medium">SAL</th>
                <th className="px-4 py-2 font-medium">Deadline</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-divider">
              {disputes.map((d) => {
                const due = deadline(d.deadline_at);
                return (
                  <tr key={d.id} className="hover:bg-pearl">
                    <td className="px-4 py-3">
                      <Link href={`/disputes/${d.id}`} className="font-medium text-action hover:underline">
                        {d.provider_dispute_id}
                      </Link>
                      <div className="mt-1 flex items-center gap-2">
                        <OriginBadge origin={d.origin} />
                        {d.case_ref && <span className="font-mono text-xs text-ink-muted">{d.case_ref}</span>}
                      </div>
                    </td>
                    <td className="px-4 py-3">{label(d.reason)}</td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums">{money(d.amount)}</td>
                    <td className="px-4 py-3">{label(d.provider_status)}</td>
                    <td className="px-4 py-3"><StateBadge state={d.internal_state} /></td>
                    <td className={`px-4 py-3 ${due.urgent ? "font-medium text-bad-ink" : ""}`}>{due.text}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
