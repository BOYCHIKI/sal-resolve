import Link from "next/link";
import { AppHeader } from "@/components/AppHeader";
import { SyncButton } from "@/components/SyncButton";
import { api, type Dispute } from "@/lib/api";
import { dueText, nextStep, orderNumber, origin, reason, type Tone } from "@/lib/plain";

export const dynamic = "force-dynamic";

const PILL: Record<Tone, string> = {
  red: "bg-red-bg text-red-ink",
  amber: "bg-amber-bg text-amber-ink",
  blue: "bg-blue-bg text-blue-ink",
  green: "bg-green-bg text-green-ink",
  grey: "bg-grey-bg text-grey-ink",
};

function Tile({ tone, title, value, hint }: { tone: Tone | "plain"; title: string; value: number; hint: string }) {
  const color = tone === "plain" ? "" : PILL[tone];
  return (
    <div className={`glass flex flex-col gap-1.5 rounded-[22px] px-6 py-5 ${color}`}>
      <span className="text-[15px] font-medium">{title}</span>
      <span className="text-4xl font-semibold tracking-tight">{value}</span>
      <span className="text-sm opacity-90">{hint}</span>
    </div>
  );
}

export default async function DisputesPage() {
  let disputes: Dispute[] = [];
  let error = false;
  try {
    disputes = await api.listDisputes();
  } catch {
    error = true;
  }

  const steps = disputes.map((d) => ({ d, step: nextStep(d), due: dueText(d.deadline_at) }));
  const count = (pred: (x: (typeof steps)[number]) => boolean) => steps.filter(pred).length;

  return (
    <>
      <AppHeader />
      <main className="mx-auto flex max-w-6xl flex-col gap-7 px-4 pb-16 pt-11">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-2">
            <h1 className="text-[34px] leading-tight sm:text-[40px]">Customer disputes</h1>
            <p className="text-[17px] text-ink-soft">Cases where a customer asked PayPal for their money back. Most urgent first.</p>
          </div>
          <SyncButton />
        </div>

        {error && (
          <p role="alert" className="rounded-[22px] bg-red-bg p-5 text-red-ink">
            SAL can’t reach its server right now. Please try again in a moment.
          </p>
        )}

        {!error && (
          <section aria-label="At a glance" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Tile tone="red" title="Reply needed within 3 days" value={count((x) => x.due.urgent && x.step.tone !== "grey")}
              hint="If you miss the deadline, PayPal usually sides with the customer." />
            <Tile tone="amber" title="Waiting for your review" value={count((x) => x.step.tone === "amber" || x.step.tone === "red")}
              hint="A reply is drafted. Check it and approve." />
            <Tile tone="blue" title="Approved, ready to send" value={count((x) => x.step.tone === "blue")}
              hint="One click sends your documents to PayPal." />
            <Tile tone="plain" title="Sent or waiting on others" value={count((x) => x.step.tone === "grey")}
              hint="Nothing to do until PayPal or the customer replies." />
          </section>
        )}

        {!error && disputes.length === 0 && (
          <p className="glass rounded-[22px] p-10 text-center text-ink-soft">
            No disputes yet. Press <strong>Check PayPal for new cases</strong> to look for new ones.
          </p>
        )}

        {steps.length > 0 && (
          <section aria-label="All cases" className="flex flex-col gap-2.5">
            {steps.map(({ d, step, due }) => {
              const order = orderNumber(d.summary?.order_ref);
              return (
                <Link key={d.id} href={`/disputes/${d.id}`}
                  className="glass flex flex-wrap items-center gap-5 rounded-[22px] px-6 py-[18px] transition-transform active:scale-[0.99]">
                  <div className="flex min-w-0 flex-[999_1_280px] flex-col gap-1">
                    <span className="text-[17px] font-semibold">{d.summary?.item ?? "Order"}</span>
                    <span className="text-[15px] text-ink-soft">
                      {reason(d.reason)}{order ? ` · Order ${order}` : ""} · {origin(d.origin)}
                    </span>
                  </div>
                  <div className="flex flex-[1_1_120px] flex-col text-right">
                    <span className="text-lg font-semibold tabular-nums">{d.amount.value} {d.amount.currency}</span>
                    <span className="text-[13px] text-ink-muted">disputed</span>
                  </div>
                  <div className="flex flex-[1_1_220px] flex-col items-start gap-1.5">
                    <span className={`rounded-full px-3 py-1 text-sm font-medium ${PILL[step.tone]}`}>{step.label}</span>
                    <span className={`text-sm ${due.urgent ? "font-semibold text-red-ink" : "text-ink-soft"}`}>{due.text}</span>
                  </div>
                  <span aria-hidden="true" className="text-2xl text-ink-muted">›</span>
                </Link>
              );
            })}
            <p className="mx-1 mt-2 text-sm text-ink-muted">
              Cases marked “Practice case” use made-up data for the demo and are never sent to PayPal.
            </p>
          </section>
        )}
      </main>
    </>
  );
}
