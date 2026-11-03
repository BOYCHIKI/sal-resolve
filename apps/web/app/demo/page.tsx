import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { Check } from "@/components/landing/Label";
import { Ticker } from "@/components/landing/Ticker";
import { api, type Dispute } from "@/lib/api";
import { money } from "@/lib/format";
import { CASE_TYPES, caseTypeOf, origin } from "@/lib/plain";

export const metadata: Metadata = {
  title: "Try the demo — SAL Resolve",
  description: "Open a practice dispute on a PayPal test account and see what SAL checks before you reply. No sign-up, no real money.",
};

export const dynamic = "force-dynamic";

// Two examples keep each row to a couple of lines; the rest are one click away on the cases page.
const PER_TYPE = 2;

function grouped(disputes: Dispute[]): Map<string, Dispute[]> {
  const out = new Map<string, Dispute[]>();  // every case per type; the row shows the first PER_TYPE
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
  return (
    <Link href={`/disputes/${d.id}`} className="group flex items-center justify-between gap-3 py-1 text-[15px]">
      <span className="min-w-0 truncate"><span className="font-semibold">{d.summary?.item ?? "Order"}</span>
        <span className="muted"> · {money(d.amount)} · {origin(d.origin)}</span></span>
      <span aria-hidden="true" className="text-(--lp-blue) transition-transform group-hover:translate-x-1">→</span>
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

      <main className="px-4">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 pb-16 pt-8">
          <section className="flex flex-wrap items-end justify-between gap-6">
            <div className="flex max-w-2xl flex-col items-start gap-3">
              <h1 className="text-[28px] font-semibold tracking-tight sm:text-[32px]">Every kind of dispute, sorted</h1>
              <p className="muted text-[16px]">
                Buyers open different kinds of disputes. Each row is one kind: what the buyer says and what SAL does about it. Open an example to see the case screen as a seller would.
              </p>
              <ul className="muted flex flex-wrap gap-x-5 gap-y-1.5 text-[15px]">
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

          {!error && (() => {
            const withCases = CASE_TYPES.filter((t) => groups.has(t.key));
            const without = CASE_TYPES.filter((t) => !groups.has(t.key));
            return (
              <section aria-label="Case types" className="flex flex-col gap-4">
                <ul className="lp-card flex flex-col divide-y divide-(--lp-line)">
                  {withCases.map((type) => {
                    const all = groups.get(type.key) ?? [];
                    return (
                      <li key={type.key} className="grid gap-x-8 gap-y-3 px-5 py-5 sm:px-6 md:grid-cols-[1fr_minmax(260px,340px)]">
                        <div className="flex flex-col gap-1">
                          <h2 className="text-[17px] font-semibold">{type.title} <span className="muted font-normal">· {all.length}</span></h2>
                          <p className="text-[15px]">{type.buyer}</p>
                          <p className="muted text-[15px]">{type.sal}</p>
                        </div>
                        <div className="flex flex-col">
                          {all.slice(0, PER_TYPE).map((d) => <Example key={d.id} d={d} />)}
                          {all.length > PER_TYPE && (
                            <Link href="/disputes" className="muted py-1 text-[14px] hover:underline">+{all.length - PER_TYPE} more</Link>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
                {without.length > 0 && (
                  <details className="text-[15px]">
                    <summary className="muted cursor-pointer font-semibold">Other kinds SAL knows · {without.length}</summary>
                    <ul className="lp-card mt-3 flex flex-col divide-y divide-(--lp-line)">
                      {without.map((type) => (
                        <li key={type.key} className="flex flex-col gap-1 px-5 py-4 sm:px-6">
                          <h2 className="font-semibold">{type.title}</h2>
                          <p className="muted">{type.buyer} {type.sal}</p>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </section>
            );
          })()}
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
