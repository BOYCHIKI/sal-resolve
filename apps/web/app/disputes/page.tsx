import Link from "next/link";
import { ActionCard } from "@/components/ActionCard";
import { AppHeader } from "@/components/AppHeader";
import { ICONS, PageHead, StatTiles } from "@/components/StatTiles";
import { SyncButton } from "@/components/SyncButton";
import { api, type AgentAction, type Dispute } from "@/lib/api";
import { caseTypeOf, dueText, nextStep, orderNumber, origin, reason, stageOf, type Tone } from "@/lib/plain";

export const dynamic = "force-dynamic";

const PILL: Record<Tone, string> = {
  red: "bg-red-bg text-red-ink",
  amber: "bg-amber-bg text-amber-ink",
  blue: "bg-blue-bg text-blue-ink",
  green: "bg-green-bg text-green-ink",
  grey: "bg-grey-bg text-grey-ink",
};

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
        <span className="flex flex-wrap gap-1.5 text-xs font-medium">
          <span className={`rounded-full px-2.5 py-1 ${PILL[type.tone]}`}>{type.title}</span>
          {stage && <span className={`rounded-full px-2.5 py-1 ${PILL[stage.tone]}`}>{stage.label}</span>}
        </span>
      </div>
      <div className="flex flex-[1_1_120px] flex-col text-right">
        <span className="text-lg font-semibold tabular-nums">{d.amount.value} {d.amount.currency}</span>
        <span className="muted text-[13px]">disputed</span>
      </div>
      <div className="flex flex-[1_1_220px] flex-col items-start gap-1.5">
        <span className={`rounded-full px-3 py-1 text-sm font-medium ${PILL[step.tone]}`}>{step.label}</span>
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

export default async function DisputesPage() {
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
  const open = paypal.filter((r) => r.step.tone !== "grey" && r.d.deadline_at);
  const holds = actions.filter((a) => a.kind === "EXPLAIN_HELD_FUNDS");
  const todo = actions.filter((a) => a.kind !== "EXPLAIN_HELD_FUNDS");
  const held = holds.length ? moneyOnHold(holds) : null;
  const nearest = open.sort((a, b) => a.d.deadline_at!.localeCompare(b.d.deadline_at!))[0];

  return (
    <div className="lp sky min-h-screen">
      <AppHeader />
      <main>
        <div className="mx-auto flex max-w-6xl flex-col gap-7 px-4 pb-16 pt-8">
          <PageHead title="Disputes" lead="SAL checks your PayPal account and tells you what needs doing. Nothing is sent without your OK.">
            <SyncButton />
          </PageHead>

          {error && (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">
              SAL can’t reach its server right now. Please try again in a moment.
            </p>
          )}

          {!error && (
            <StatTiles stats={[
              { label: "Needs you", value: todo.length, note: todo.length ? "Decisions waiting" : "Nothing right now", icon: ICONS.alert },
              { label: "Next deadline", value: nearest ? nearest.due.short : "None", note: "To reply to PayPal", icon: ICONS.clock },
              { label: "Money on hold", value: held ?? "0", note: "Held by PayPal while cases are open", icon: ICONS.lock },
              { label: "PayPal cases", value: paypal.length, note: "On your test account", icon: ICONS.cases },
            ]} />
          )}

          {todo.length > 0 && (
            <section aria-label="Needs you" className="flex flex-col gap-3">
              <h2 className="text-[18px] font-semibold">Needs you <span className="muted font-normal">· {todo.length}</span></h2>
              {todo.map((a) => <ActionCard key={a.id} action={a} />)}
            </section>
          )}

          {holds.length > 0 && (
            <section aria-label="Money on hold" className="flex flex-col gap-3">
              <h2 className="text-[18px] font-semibold">Money on hold <span className="muted font-normal">· {held}</span></h2>
              {holds.map((a) => <ActionCard key={a.id} action={a} />)}
            </section>
          )}

          {!error && disputes.length === 0 && (
            <p className="muted lp-dashed rounded-[20px] p-10 text-center">
              No disputes yet. Press <strong>Check PayPal for new cases</strong> to look for new ones.
            </p>
          )}

          {paypal.length > 0 && (
            <section aria-label="PayPal cases" className="flex flex-col gap-4">
              <h2 className="text-[18px] font-semibold">Your PayPal cases <span className="muted font-normal">· {paypal.length}</span></h2>
              <div className="lp-card flex flex-col divide-y divide-(--lp-line) overflow-hidden">
                {paypal.map((r) => <CaseRow key={r.d.id} {...r} />)}
              </div>
            </section>
          )}

          {practice.length > 0 && (
            <details className="flex flex-col gap-4">
              <summary className="muted cursor-pointer text-sm font-semibold">
                Practice cases <span className="muted">· {practice.length} · made-up data, never sent to PayPal</span>
              </summary>
              <div className="lp-card mt-4 flex flex-col divide-y divide-(--lp-line) overflow-hidden">
                {practice.map((r) => <CaseRow key={r.d.id} {...r} />)}
              </div>
            </details>
          )}
        </div>
      </main>
    </div>
  );
}
