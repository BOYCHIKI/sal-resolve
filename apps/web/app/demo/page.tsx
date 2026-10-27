import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { COURIERS, MARKETS } from "@/components/CourierMarquee";
import { Check, Label } from "@/components/landing/Label";
import { Ticker } from "@/components/landing/Ticker";
import { SalSays } from "@/components/mascot/SalSays";
import { api, type Dispute } from "@/lib/api";
import { money } from "@/lib/format";
import { nextStep, reason, type Tone } from "@/lib/plain";

export const metadata: Metadata = {
  title: "Try the demo — SAL Resolve",
  description: "Open a practice dispute on a PayPal test account and see what SAL checks before you reply. No sign-up, no real money.",
};

export const dynamic = "force-dynamic";

// How many cases the picker offers; the full list is one click away on /disputes.
const PICKS = 4;

const PILL: Record<Tone, string> = {
  red: "bg-red-bg text-red-ink",
  amber: "bg-amber-bg text-amber-ink",
  blue: "bg-blue-bg text-blue-ink",
  green: "bg-green-bg text-green-ink",
  grey: "bg-grey-bg text-grey-ink",
};

const figures = [
  { value: COURIERS.length, label: "couriers recognised on a tracking slip" },
  { value: MARKETS, label: "Southeast Asian markets with local couriers" },
  { value: 0, label: "replies sent without your approval" },
];

// The seed can hold several copies of one practice case; offer each case once.
function picks(disputes: Dispute[]): Dispute[] {
  const seen = new Set<string>();
  return disputes.filter((d) => {
    const key = d.case_ref ?? d.id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, PICKS);
}

export default async function DemoPage() {
  let cases: Dispute[] = [];
  let error = false;
  try {
    cases = picks(await api.listDisputes());
  } catch {
    error = true;
  }

  return (
    <div className="lp sky min-h-screen">
      <Ticker />

      <header className="border-b border-(--lp-line)">
        <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <Link href="/" className="display text-xl whitespace-nowrap">SAL <span className="muted font-semibold">Resolve</span></Link>
          <Link href="/" className="lp-btn-ghost">Back to home</Link>
        </nav>
      </header>

      <main>
        <section className="relative overflow-hidden px-4">
          <div aria-hidden="true" className="lp-dots absolute inset-0" />
          <div className="relative mx-auto grid max-w-6xl items-start gap-12 py-16 lg:grid-cols-[1.1fr_1fr] lg:py-24">
            <div className="flex flex-col items-start gap-7 lg:pt-8">
              <span data-reveal><Label>Try the demo</Label></span>
              <h1 data-split="hero" className="display text-[42px] sm:text-7xl">
                See a dispute <span className="muted">answered in minutes.</span>
              </h1>
              <p data-reveal className="muted max-w-xl text-lg">
                Pick a practice case. SAL shows <strong>what your documents prove, what’s missing and what doesn’t add up</strong>,
                then drafts a reply you can read and approve. No sign-up needed.
              </p>
              <ul data-reveal-stagger className="muted flex flex-col gap-2.5">
                <li className="flex gap-2.5"><Check />Runs on a PayPal test account</li>
                <li className="flex gap-2.5"><Check />Made-up orders, no real customers or money</li>
                <li className="flex gap-2.5"><Check />Practice cases are never sent to PayPal</li>
              </ul>
              {/* SAL points across at the case picker. */}
              <SalSays mascot={<Image src="/mascot/sal-point.png" alt="" width={533} height={509} className="h-auto w-32" />}
                className="self-stretch lg:self-start" bubbleClassName="px-5 py-4">
                <p className="text-[17px]">Pick a case and I’ll show you <strong>what I found in its documents</strong>.</p>
              </SalSays>
            </div>

            <div data-reveal className="rounded-[28px] border border-(--lp-line) bg-(--lp-card-2) p-3 sm:p-5">
              <div className="lp-card flex flex-col gap-5 p-5 sm:p-7">
                <div className="flex flex-col gap-1">
                  <h2 className="text-xl font-semibold">Pick a practice case</h2>
                  <p className="muted text-sm">Each one opens the case screen, where SAL has already checked the documents.</p>
                </div>

                {error && (
                  <p role="alert" className="rounded-2xl bg-red-bg p-4 text-red-ink">
                    SAL can’t reach its server right now. Please try again in a moment.
                  </p>
                )}

                {!error && cases.length === 0 && (
                  <p className="muted rounded-2xl border border-dashed border-(--lp-line-strong) p-5 text-center">
                    No practice cases yet. Open the case list and press <strong>Check PayPal for new cases</strong>.
                  </p>
                )}

                {cases.length > 0 && (
                  <ul className="flex flex-col gap-2.5">
                    {cases.map((d) => {
                      const step = nextStep(d);
                      return (
                        <li key={d.id}>
                          <Link href={`/disputes/${d.id}`}
                            className="group grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-2 rounded-2xl border border-(--lp-line) bg-(--lp-well) px-4 py-3.5 transition-colors hover:border-(--lp-mint)">
                            <span className="min-w-0">
                              <span className="block truncate font-semibold">{d.summary?.item ?? "Order"}</span>
                              <span className="muted block text-sm">{reason(d.reason)} · {money(d.amount)}</span>
                            </span>
                            <span aria-hidden="true" className="muted text-xl transition-transform group-hover:translate-x-1">→</span>
                            <span className="col-span-2 flex flex-wrap gap-2 text-xs font-medium">
                              <span className={`rounded-full px-2.5 py-1 ${PILL[step.tone]}`}>{step.label}</span>
                            </span>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}

                <Link href="/disputes" className="lp-btn self-stretch">See all cases</Link>
              </div>
            </div>
          </div>
        </section>

        <section aria-label="SAL by the numbers" className="border-t border-(--lp-line) px-4 py-16">
          <ul data-reveal-stagger className="mx-auto grid max-w-6xl gap-5 sm:grid-cols-3">
            {figures.map((f) => (
              <li key={f.label} className="lp-card flex flex-col gap-2 p-7">
                <span data-count={f.value} className="display text-6xl tabular-nums text-(--lp-mint) sm:text-7xl">{f.value}</span>
                <span className="muted text-[15px]">{f.label}</span>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="muted mx-auto max-w-6xl border-t border-(--lp-line) px-4 py-6 text-sm">
        SAL Resolve · MIT licensed · Not affiliated with or endorsed by PayPal.
      </footer>
    </div>
  );
}
