import Link from "next/link";
import { ActionCard } from "@/components/ActionCard";
import { AppHeader } from "@/components/AppHeader";
import { Label } from "@/components/landing/Label";
import { SyncButton } from "@/components/SyncButton";
import { api, type AgentAction, type Dispute } from "@/lib/api";
import { dueText, nextStep, orderNumber, origin, reason, type Tone } from "@/lib/plain";

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
  return (
    <Link href={`/disputes/${d.id}`} className="lp-card group flex flex-wrap items-center gap-5 px-6 py-[18px] transition-colors">
      <div className="flex min-w-0 flex-[999_1_280px] flex-col gap-1">
        <span className="text-[17px] font-semibold">{d.summary?.item ?? "Order"}</span>
        <span className="muted text-[15px]">
          {reason(d.reason)}{order ? ` · Order ${order}` : ""} · {origin(d.origin)}
          {d.lifecycle_stage === "CHARGEBACK" && <span className="font-semibold text-red-ink"> · Chargeback: the bank decides</span>}
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
      <main className="relative">
        <div aria-hidden="true" className="lp-dots absolute inset-x-0 top-0 h-80" />
        <div className="relative mx-auto flex max-w-6xl flex-col gap-8 px-4 pb-16 pt-12">
          <div className="flex flex-wrap items-end justify-between gap-5">
            <div className="flex flex-col items-start gap-4">
              <Label>Your PayPal account</Label>
              <h1 className="display text-[42px] sm:text-6xl">What SAL found</h1>
              <p className="muted max-w-2xl text-[17px]">SAL checks your PayPal account and tells you what needs doing. Nothing is sent without your OK.</p>
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <Link href="/packing" className="text-[15px] font-semibold underline underline-offset-4">Packing proof</Link>
              <SyncButton />
            </div>
          </div>

          {error && (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">
              SAL can’t reach its server right now. Please try again in a moment.
            </p>
          )}

          {!error && (
            <p className="lp-card px-6 py-5 text-[17px] leading-relaxed">
              {held ? <>PayPal is holding <strong>{held}</strong> of your money. </> : <>PayPal isn’t holding any of your money. </>}
              {todo.length === 0 ? "Nothing needs you right now."
                : <><strong>{todo.length} thing{todo.length === 1 ? "" : "s"}</strong> need{todo.length === 1 ? "s" : ""} your decision.</>}
              {nearest && <> Next PayPal deadline: <strong className="text-red-ink">{nearest.due.short}</strong>.</>}
            </p>
          )}

          {todo.length > 0 && (
            <section aria-label="Needs you" className="flex flex-col gap-3">
              <h2 className="text-xl font-semibold">Needs you <span className="muted">· {todo.length}</span></h2>
              {todo.map((a) => <ActionCard key={a.id} action={a} />)}
            </section>
          )}

          {holds.length > 0 && (
            <section aria-label="Money on hold" className="flex flex-col gap-3">
              <h2 className="text-xl font-semibold">Money on hold <span className="muted">· {held}</span></h2>
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
              <h2 className="text-xl font-semibold">Your PayPal cases <span className="muted">· {paypal.length}</span></h2>
              <div className="flex flex-col gap-2.5">
                {paypal.map((r) => <CaseRow key={r.d.id} {...r} />)}
              </div>
            </section>
          )}

          {practice.length > 0 && (
            <details className="flex flex-col gap-4">
              <summary className="muted cursor-pointer text-sm font-semibold">
                Practice cases <span className="muted">· {practice.length} · made-up data, never sent to PayPal</span>
              </summary>
              <div className="mt-4 flex flex-col gap-2.5">
                {practice.map((r) => <CaseRow key={r.d.id} {...r} />)}
              </div>
            </details>
          )}
        </div>
      </main>
    </div>
  );
}
