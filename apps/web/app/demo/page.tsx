import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { Check, Label } from "@/components/landing/Label";
import { Ticker } from "@/components/landing/Ticker";
import { api, type Dispute } from "@/lib/api";
import { money } from "@/lib/format";
import { CASE_TYPES, caseTypeOf, nextStep, origin, stageOf, type Tone } from "@/lib/plain";

export const metadata: Metadata = {
  title: "Try the demo — SAL Resolve",
  description: "Open a practice dispute on a PayPal test account and see what SAL checks before you reply. No sign-up, no real money.",
};

export const dynamic = "force-dynamic";

const PILL: Record<Tone, string> = {
  red: "bg-red-bg text-red-ink",
  amber: "bg-amber-bg text-amber-ink",
  blue: "bg-blue-bg text-blue-ink",
  green: "bg-green-bg text-green-ink",
  grey: "bg-grey-bg text-grey-ink",
};

const DOT: Record<Tone, string> = {
  red: "bg-red-ink", amber: "bg-amber-ink", blue: "bg-blue-ink", green: "bg-green-ink", grey: "bg-grey-ink",
};

// Enough to see the different situations inside one type without turning the box into a list. Practice cases first.
const PER_TYPE = 5;

function grouped(disputes: Dispute[]): Map<string, Dispute[]> {
  const out = new Map<string, Dispute[]>();  // every case per type; the box shows the first PER_TYPE
  const sorted = [...disputes].sort((a, b) => Number(a.origin === "PAYPAL_SANDBOX") - Number(b.origin === "PAYPAL_SANDBOX"));
  for (const d of sorted) {
    const key = caseTypeOf(d).key;
    const list = out.get(key) ?? [];
    list.push(d);
    out.set(key, list);
  }
  return out;
}

function Example({ d }: { d: Dispute }) {
  const step = nextStep(d);
  const stage = stageOf(d);
  return (
    <Link href={`/disputes/${d.id}`}
      className="group flex flex-col gap-2 rounded-2xl border border-(--lp-line) bg-(--lp-well) px-4 py-3 transition-colors hover:border-(--lp-mint)">
      <span className="flex items-center gap-3">
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate font-semibold">{d.summary?.item ?? "Order"}</span>
          <span className="muted truncate text-[13px]">{money(d.amount)} · {origin(d.origin)}</span>
        </span>
        <span className="text-sm font-semibold whitespace-nowrap">Open <span aria-hidden="true" className="inline-block transition-transform group-hover:translate-x-1">→</span></span>
      </span>
      <span className="flex flex-wrap gap-1.5 text-xs font-medium">
        <span className={`rounded-full px-2.5 py-1 ${PILL[step.tone]}`}>{step.label}</span>
        {stage && <span className={`rounded-full px-2.5 py-1 ${PILL[stage.tone]}`}>{stage.label}</span>}
      </span>
    </Link>
  );
}
export default async function DemoPage() {
  let groups = new Map<string, Dispute[]>();
  let error = false;
  try {
    groups = grouped(await api.listDisputes());
  } catch {
    error = true;
  }

  return (
    <div className="lp sky min-h-screen">
      <Ticker />

      <header className="border-b border-(--lp-line)">
        <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <Link href="/" className="display text-xl whitespace-nowrap">SAL <span className="muted font-semibold">Resolve</span></Link>
          <span className="flex items-center gap-2">
            <Link href="/disputes" className="lp-btn-ghost hidden sm:inline-flex">All cases</Link>
            <Link href="/" className="lp-btn-ghost">Home</Link>
          </span>
        </nav>
      </header>

      <main className="relative px-4">
        <div aria-hidden="true" className="lp-dots absolute inset-x-0 top-0 h-80" />
        <div className="relative mx-auto flex max-w-6xl flex-col gap-10 pb-16 pt-10 sm:pt-14">
          <section className="flex flex-wrap items-end justify-between gap-6">
            <div className="flex max-w-2xl flex-col items-start gap-4">
              <span data-reveal><Label>Try the demo</Label></span>
              <h1 className="display text-[34px] leading-tight sm:text-5xl">Every kind of dispute, sorted</h1>
              <p data-reveal className="muted text-[17px]">
                Buyers open different kinds of disputes. Each box is one kind, what the buyer says and what SAL does about it. Open an example to see the case screen as a seller would.
              </p>
              <ul data-reveal-stagger className="muted flex flex-wrap gap-x-5 gap-y-1.5 text-[15px]">
                <li className="flex gap-2"><Check />PayPal test account</li>
                <li className="flex gap-2"><Check />Made-up orders, no real money</li>
                <li className="flex gap-2"><Check />Nothing sent without your OK</li>
              </ul>
            </div>
            <Image src="/mascot/sal-point.png" alt="" width={533} height={509} className="hidden h-auto w-28 lg:block" />
          </section>

          {error && (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">
              SAL can’t reach its server right now. Please try again in a moment.
            </p>
          )}

          {!error && (
            <section aria-label="Case types" className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {/* Kinds that have cases first; the rest stay listed so a seller sees what SAL covers. */}
              {[...CASE_TYPES].sort((a, b) => Number(!groups.has(a.key)) - Number(!groups.has(b.key))).map((type) => {
                const all = groups.get(type.key) ?? [];
                const examples = all.slice(0, PER_TYPE);
                return (
                  <article key={type.key} data-reveal
                    className={`lp-card flex flex-col gap-3 p-5 sm:p-6 ${examples.length ? "" : "opacity-80"}`}>
                    <div className="flex items-center gap-2.5">
                      <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${DOT[type.tone]}`} />
                      <h2 className="text-lg font-semibold">{type.title}</h2>
                      <span className={`ml-auto rounded-full px-2.5 py-0.5 text-xs font-semibold ${PILL[type.tone]}`}>
                        {all.length} case{all.length === 1 ? "" : "s"}
                      </span>
                    </div>
                    <p className="text-[15px] font-medium">{type.buyer}</p>
                    <p className="muted text-[15px] leading-relaxed">{type.sal}</p>
                    {examples.length > 0 ? (
                      <div className="flex flex-col gap-2">{examples.map((d) => <Example key={d.id} d={d} />)}</div>
                    ) : (
                      <p className="muted rounded-2xl border border-dashed border-(--lp-line-strong) px-4 py-3 text-sm">
                        No case of this kind yet. When one comes in, SAL puts it here.
                      </p>
                    )}
                  </article>
                );
              })}
            </section>
          )}
          <section aria-label="Before you ship" className="lp-card flex flex-wrap items-center gap-5 p-5 sm:p-6">
            <div className="flex min-w-0 flex-[999_1_320px] flex-col gap-1">
              <h2 className="text-lg font-semibold">Before you ship: packing proof</h2>
              <p className="muted text-[15px]">
                Photograph the item going into the box. If the buyer later says it was wrong or damaged, SAL adds the photos
                to that case for you.
              </p>
            </div>
            <Link href="/packing" className="lp-btn">Try packing proof</Link>
          </section>
        </div>
      </main>

      <footer className="muted mx-auto max-w-6xl border-t border-(--lp-line) px-4 py-6 text-sm">
        SAL Resolve · MIT licensed · Not affiliated with or endorsed by PayPal.
      </footer>
    </div>
  );
}
