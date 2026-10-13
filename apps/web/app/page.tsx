import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "SAL Resolve — reply to PayPal disputes with proof",
  description: "When a customer says an order never arrived, SAL checks your documents, flags what doesn’t add up and drafts the reply. You approve before anything is sent.",
};

const STEPS = [
  {
    title: "1. Your disputes, in one list",
    body: "SAL picks up new disputes from PayPal and shows what the customer claims, how much is at stake, and how many days you have left to reply.",
    icon: <path d="M4 6h16M4 12h16M4 18h10" />,
  },
  {
    title: "2. Your documents, checked for you",
    body: "SAL reads your invoice, payment receipt and delivery records, and tells you in plain words if proof is missing or two documents disagree.",
    icon: <><path d="M9 11l3 3 8-8" /><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9" /></>,
  },
  {
    title: "3. You approve, then send",
    body: "SAL writes the reply using only facts from your documents. You read it, approve it, and send it to PayPal with one click.",
    icon: <><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4 20-7z" /></>,
  },
];

const TRUST = [
  "Every sentence comes from one of your documents. Nothing is made up.",
  "Suspicious text in a customer message is pointed out, never acted on.",
  "Amounts are shown in the currency the customer paid in.",
  "Your business data is kept separate from every other business.",
];

export default function Landing() {
  return (
    <div className="px-4">
      <header className="sticky top-4 z-10 mx-auto mt-4 max-w-5xl">
        <nav aria-label="Main" className="glass flex flex-wrap items-center justify-between gap-3 rounded-full py-2 pl-5 pr-2">
          <span className="text-lg font-semibold tracking-tight">SAL <span className="font-normal text-ink-muted">Resolve</span></span>
          <div className="flex flex-wrap items-center gap-1 text-sm">
            <a href="#how" className="px-3.5 py-2.5">How it works</a>
            <a href="#trust" className="px-3.5 py-2.5">Why trust it</a>
            <a href="https://github.com/BOYCHIKI/sal-resolve" className="px-3.5 py-2.5">GitHub</a>
            <Link href="/disputes" className="btn-primary min-h-11 text-[15px]">Open the demo</Link>
          </div>
        </nav>
      </header>

      <main className="mx-auto max-w-5xl">
        <section className="flex flex-col items-center gap-6 pb-16 pt-24 text-center">
          <span className="glass rounded-full px-4 py-1.5 text-sm text-ink-soft">For online sellers who use PayPal · Demo with a test account</span>
          <h1 className="max-w-3xl text-[40px] leading-[1.06] sm:text-6xl">Customer says it never arrived? Reply with proof, in minutes.</h1>
          <p className="max-w-2xl text-lg text-ink-soft sm:text-xl">
            When a customer opens a PayPal dispute, SAL gathers your invoice, payment and delivery documents, points out anything that
            doesn’t add up, and writes the reply for you. You read it, approve it, and send.
          </p>
          <div className="mt-2 flex flex-wrap justify-center gap-3">
            <Link href="/disputes" className="btn-primary">Open the demo</Link>
            <a href="#how" className="btn-secondary">See how it works</a>
          </div>
        </section>

        <section aria-label="What you see" className="glass rounded-[28px] p-2">
          <div className="grid gap-4 rounded-[22px] bg-surface/70 p-5 sm:grid-cols-3">
            <div className="flex flex-col gap-2 rounded-2xl bg-surface p-5">
              <span className="text-sm text-ink-muted">1 · The case</span>
              <span className="text-[17px] font-semibold">Wireless Keyboard · 130.41 USD</span>
              <span className="text-[15px] text-ink-soft">Customer says it never arrived. Reply needed in 9 days.</span>
            </div>
            <div className="flex flex-col gap-2 rounded-2xl bg-amber-bg p-5 text-amber-ink">
              <span className="text-sm">2 · What to check</span>
              <span className="text-[17px] font-semibold">The delivery dates don’t match</span>
              <span className="text-[15px]">Courier: 19 Aug. Receipt: 20 Aug. Confirm one before replying.</span>
            </div>
            <div className="flex flex-col gap-2 rounded-2xl bg-surface p-5">
              <span className="text-sm text-ink-muted">3 · Your reply, ready to approve</span>
              <span className="text-[15px]">“The customer paid 130.41 USD for this order. We shipped it with tracking number TRK-SYN-72140.”</span>
            </div>
          </div>
        </section>

        <section id="how" className="flex scroll-mt-24 flex-col gap-10 pb-8 pt-32">
          <div className="flex max-w-2xl flex-col gap-3">
            <h2 className="text-4xl leading-tight sm:text-[44px]">From open dispute to approved reply.</h2>
            <p className="text-lg text-ink-soft">Three steps. SAL prepares; you decide.</p>
          </div>
          <div className="grid gap-5 sm:grid-cols-3">
            {STEPS.map((s) => (
              <div key={s.title} className="glass flex flex-col gap-3.5 rounded-3xl p-7">
                <svg aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--action)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{s.icon}</svg>
                <h3 className="text-xl">{s.title}</h3>
                <p className="text-ink-soft">{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="trust" className="grid scroll-mt-24 gap-5 pb-8 pt-24 sm:grid-cols-2">
          <div className="flex flex-col gap-3 rounded-[28px] bg-[#1d1d1f] p-10 text-[#f5f5f7]">
            <h2 className="text-4xl leading-tight">Nothing goes to PayPal without you.</h2>
            <p className="text-[17px] text-[#c7c7cc]">
              SAL prepares; you decide. It can’t send documents, accept a refund or message the customer on its own. If PayPal updates the
              case, you’re asked to review again.
            </p>
          </div>
          <div className="glass flex flex-col gap-4 rounded-[28px] p-10">
            <h2 className="text-2xl">Why you can trust the reply</h2>
            <ul className="flex flex-col gap-3">
              {TRUST.map((t) => (
                <li key={t} className="flex gap-2.5">
                  <svg aria-hidden="true" className="mt-1 shrink-0" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--action)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5L20 7" /></svg>
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="flex flex-col items-center gap-5 pb-36 pt-28 text-center">
          <h2 className="text-4xl leading-tight sm:text-[44px]">See it with practice cases.</h2>
          <p className="max-w-xl text-lg text-ink-soft">The demo uses a PayPal test account and made-up orders. No real customers or money involved.</p>
          <Link href="/disputes" className="btn-primary">Open the demo</Link>
        </section>
      </main>

      <footer className="glass -mx-4 border-x-0 border-b-0">
        <div className="mx-auto flex max-w-5xl flex-wrap justify-between gap-3 px-4 py-8 text-sm text-ink-muted">
          <span>SAL Resolve · MIT licensed · Not affiliated with or endorsed by PayPal.</span>
          <a href="https://github.com/BOYCHIKI/sal-resolve" className="text-action">Source on GitHub</a>
        </div>
      </footer>
    </div>
  );
}
