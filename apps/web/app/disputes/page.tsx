import Link from "next/link";
import { ActionCard } from "@/components/ActionCard";
import { AppHeader } from "@/components/AppHeader";
import { Empty, PageHead, pickView, ViewLead, ViewTabs, type View } from "@/components/WorkPage";
import { SyncButton } from "@/components/SyncButton";
import { api, type AgentAction, type Dispute } from "@/lib/api";
import { caseTypeOf, dueText, nextStep, orderNumber, origin, reason, stageOf } from "@/lib/plain";

export const dynamic = "force-dynamic";

type Row = { d: Dispute; step: ReturnType<typeof nextStep>; due: ReturnType<typeof dueText> };

function CaseRow({ d, step, due }: Row) {
  const order = orderNumber(d.summary?.order_ref);
  const type = caseTypeOf(d);
  const stage = stageOf(d);
  return (
    <Link href={`/disputes/${d.id}`} className="group flex flex-wrap items-center gap-5 px-5 py-4 transition-colors hover:bg-(--lp-card-2) sm:px-6">
      <div className="flex min-w-0 flex-[999_1_280px] flex-col gap-1">
        <span className="text-[17px] font-semibold">{d.summary?.item ?? "Order"}</span>
        <span className="muted text-[15px]">
          {reason(d.reason)}{order ? ` · Order ${order}` : ""} · {origin(d.origin)}
        </span>
        <span className="muted flex flex-wrap gap-1.5 text-xs font-medium">
          <span className="rounded-full bg-(--lp-card-2) px-2.5 py-1">{type.title}</span>
          {stage && <span className="rounded-full bg-(--lp-card-2) px-2.5 py-1">{stage.label}</span>}
        </span>
      </div>
      <div className="flex flex-[1_1_120px] flex-col text-right">
        <span className="text-lg font-semibold tabular-nums">{d.amount.value} {d.amount.currency}</span>
        <span className="muted text-[13px]">disputed</span>
      </div>
      <div className="flex flex-[1_1_220px] flex-col items-start gap-1.5">
        <span className="text-sm font-semibold">{step.label}</span>
        <span className={`text-sm ${due.urgent ? "font-semibold text-red-ink" : "muted"}`}>{due.text}</span>
      </div>
      <span aria-hidden="true" className="muted text-xl transition-transform group-hover:translate-x-1">→</span>
    </Link>
  );
}

/** "43.17 USD" or "43.17 USD + 10.00 EUR" from the open held-funds cards. */
function moneyOnHold(actions: AgentAction[]): string {
  const sums = new Map<string, number>();
  for (const a of actions) {
    if (a.kind !== "EXPLAIN_HELD_FUNDS") continue;
    const currency = String(a.payload.currency ?? "");
    sums.set(currency, (sums.get(currency) ?? 0) + Number(a.payload.amount ?? 0));
  }
  return [...sums].map(([c, v]) => `${v.toFixed(2)} ${c}`).join(" + ");
}

export default async function DisputesPage({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  const { view: asked } = await searchParams;
  let disputes: Dispute[] = [];
  let actions: AgentAction[] = [];
  let error = false;
  try {
    [disputes, actions] = await Promise.all([api.listDisputes(), api.listActions()]);
  } catch {
    error = true;
  }

  const rows: Row[] = disputes.map((d) => ({ d, step: nextStep(d), due: dueText(d.deadline_at) }));
  const paypal = rows.filter((r) => r.d.origin === "PAYPAL_SANDBOX");
  const practice = rows.filter((r) => r.d.origin !== "PAYPAL_SANDBOX");
  // Open PayPal cases with a deadline, and the one due first (without reordering the list itself).
  const deadlines = paypal.flatMap((r) => (r.step.tone !== "grey" && r.d.deadline_at ? [{ row: r, at: r.d.deadline_at }] : []));
  const holds = actions.filter((a) => a.kind === "EXPLAIN_HELD_FUNDS");
  // Only work on a PayPal case belongs here; a held deal is shown on Deal Check.
  const todo = actions.filter((a) => a.kind !== "EXPLAIN_HELD_FUNDS" && a.dispute_id !== null);
  const held = holds.length ? moneyOnHold(holds) : null;
  const nearest = deadlines.reduce<(typeof deadlines)[number] | undefined>(
    (first, next) => (!first || next.at < first.at ? next : first), undefined)?.row;

  const views: View[] = [
    { key: "todo", label: "Needs you", count: todo.length },
    { key: "cases", label: "PayPal cases", count: paypal.length },
    { key: "money", label: "Money on hold", count: holds.length },
    { key: "practice", label: "Practice", count: practice.length },
  ];
  const view = pickView(views, asked);

  return (
    <div className="lp sky min-h-screen">
      <AppHeader />
      <main>
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 pb-16 pt-8">
          <PageHead title="Disputes" lead="SAL checks your PayPal account and tells you what needs doing. Nothing is sent without your OK.">
            <SyncButton />
          </PageHead>

          {error ? (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">
              SAL can’t reach its server right now. Please try again in a moment.
            </p>
          ) : (
            <>
              <ViewTabs views={views} current={view} path="/disputes" />

              {view === "todo" && (todo.length ? (
                <>
                  <ViewLead>
                    Decisions on your PayPal cases, most urgent first.
                    {nearest && <> Next PayPal deadline: <strong className={nearest.due.urgent ? "text-red-ink" : ""}>{nearest.due.short}</strong>.</>}
                  </ViewLead>
                  <div className="flex flex-col gap-3">{todo.map((a) => <ActionCard key={a.id} action={a} />)}</div>
                </>
              ) : <Empty>Nothing needs you right now. SAL keeps checking PayPal.</Empty>)}

              {view === "cases" && (paypal.length ? (
                <>
                  <ViewLead>Every dispute on your PayPal account. Open one to see its documents and reply.</ViewLead>
                  <div className="lp-card flex flex-col divide-y divide-(--lp-line) overflow-hidden">
                    {paypal.map((r) => <CaseRow key={r.d.id} {...r} />)}
                  </div>
                </>
              ) : <Empty>No PayPal cases yet. Press <strong>Check PayPal for new cases</strong> to look for new ones.</Empty>)}

              {view === "money" && (holds.length ? (
                <>
                  <ViewLead>PayPal is holding <strong>{held}</strong> while these cases are open. Nothing to do: it comes back when a case closes in your favour.</ViewLead>
                  <div className="flex flex-col gap-3">{holds.map((a) => <ActionCard key={a.id} action={a} />)}</div>
                </>
              ) : <Empty>PayPal isn’t holding any of your money.</Empty>)}

              {view === "practice" && (practice.length ? (
                <>
                  <ViewLead>Example cases to explore SAL. They are never sent to PayPal.</ViewLead>
                  <div className="lp-card flex flex-col divide-y divide-(--lp-line) overflow-hidden">
                    {practice.map((r) => <CaseRow key={r.d.id} {...r} />)}
                  </div>
                </>
              ) : <Empty>No example cases.</Empty>)}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
