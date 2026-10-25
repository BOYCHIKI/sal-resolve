import type { Metadata } from "next";
import Link from "next/link";
import { CourierMarquee, COURIERS } from "@/components/CourierMarquee";
import { EvidenceFlow } from "@/components/motion/EvidenceFlow";

export const metadata: Metadata = {
  title: "SAL Resolve — the evidence copilot for PayPal disputes",
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

// Each card names something the product does today; nothing here is a promise.
const FEATURES = [
  { title: "Deadline countdown", body: "Every case shows the days left to reply. Under three days, it turns red and moves to the top." },
  { title: "Mismatches flagged", body: "Two documents with different dates or amounts are pointed out before you reply, not after." },
  { title: "PayPal’s own record", body: "The payment record is pulled straight from PayPal, so the reply quotes what PayPal already knows." },
  { title: "Couriers PayPal can follow", body: "The courier on your tracking slip is sent as PayPal’s own carrier code, so PayPal can check the delivery." },
  { title: "Approval tied to the proof", body: "If a document or the case changes after you approve, the approval lapses and you review again." },
  { title: "No double sends", body: "If the connection drops mid-send, SAL checks with PayPal before trying again." },
];

const TRUST = [
  "Every sentence comes from one of your documents. Nothing is made up.",
  "Suspicious text in a customer message is pointed out, never acted on.",
  "Amounts are shown in the currency the customer paid in.",
  "Your business data is kept separate from every other business.",
];

const AUDIENCES = [
  { title: "Small online shops", body: "One person handles orders, shipping and disputes. SAL keeps the paperwork straight so a dispute takes minutes, not an evening." },
  { title: "Sellers shipping across Southeast Asia", body: "JNE, J&T, Ninja Van, Kerry and more are read straight off your slip, in the courier names you already use." },
  { title: "Support and finance staff", body: "One list of cases, sorted by urgency, with what to check written out. Nothing leaves without someone approving it." },
];

const figures = [
  { value: 0, label: "replies sent without your approval" },
  { value: 3, label: "kinds of proof checked: invoice, payment, delivery" },
  { value: COURIERS.length, label: "couriers recognised on a tracking slip" },
  { value: 1, label: "click to send, once you approve" },
];

const FOOTER = [
  { title: "Product", links: [["How it works", "#how"], ["What it checks", "#features"], ["Why trust it", "#trust"]] },
  { title: "Demo", links: [["Open the demo", "/disputes"], ["Practice cases", "/disputes"]] },
  { title: "Project", links: [["Source on GitHub", "https://github.com/BOYCHIKI/sal-resolve"], ["MIT licence", "https://github.com/BOYCHIKI/sal-resolve/blob/main/LICENSE"]] },
];

const Check = () => (
  <svg aria-hidden="true" className="mt-1 shrink-0" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--action)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5L20 7" /></svg>
);

export default function Landing() {
  return (
    <>
      <Link href="/disputes" className="notice-bar block px-4 py-2 text-center text-sm">
        Demo on a PayPal test account. Made-up orders, no real money. <span className="underline underline-offset-2">Try it ›</span>
      </Link>

      <div className="px-4">
        <header className="sticky top-4 z-10 mx-auto mt-4 max-w-5xl">
          <nav aria-label="Main" className="glass flex items-center justify-between gap-3 rounded-full py-2 pl-5 pr-2">
            <span className="text-lg font-semibold tracking-tight whitespace-nowrap">SAL <span className="font-normal text-ink-muted">Resolve</span></span>
            {/* On phones the section links would wrap the pill onto three rows; the page is one scroll, so keep only the CTA. */}
            <div className="flex items-center gap-1 text-sm">
              <a href="#how" className="hidden px-3.5 py-2.5 sm:inline">How it works</a>
              <a href="#features" className="hidden px-3.5 py-2.5 sm:inline">What it checks</a>
              <a href="#trust" className="hidden px-3.5 py-2.5 sm:inline">Why trust it</a>
              <Link href="/disputes" className="btn-primary min-h-11 text-[15px]">Open the demo</Link>
            </div>
          </nav>
        </header>

        <main className="mx-auto max-w-5xl">
          <section className="flex flex-col items-center gap-6 pb-12 pt-24 text-center">
            <span data-reveal className="glass rounded-full px-4 py-1.5 text-sm text-ink-soft">The evidence copilot for PayPal disputes</span>
            <h1 data-split="hero" className="max-w-3xl text-[40px] leading-[1.06] sm:text-6xl">Customer says it never arrived? Know what your proof shows.</h1>
            <p data-reveal className="max-w-2xl text-lg text-ink-soft sm:text-xl">
              When a customer opens a PayPal dispute, SAL pulls the payment record from PayPal, reads your invoice and delivery
              documents, and shows what they prove, what’s missing and what doesn’t add up. Then it drafts a reply from proven facts
              only. You read it, approve it, and send.
            </p>
            <div data-reveal className="mt-2 flex flex-wrap justify-center gap-3">
              <Link href="/disputes" className="btn-primary">Open the demo</Link>
              <a href="#how" className="btn-secondary">See how it works</a>
            </div>
            <ul data-reveal-stagger className="mt-2 flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm text-ink-soft">
              <li className="flex gap-2"><Check />Facts from your documents only</li>
              <li className="flex gap-2"><Check />Nothing sent without you</li>
              <li className="flex gap-2"><Check />Built on PayPal’s Disputes API</li>
            </ul>
          </section>

          <section data-reveal className="glass mb-6 hidden rounded-[28px] px-6 py-4 sm:block">
            <EvidenceFlow />
          </section>

          <section aria-label="What you see" className="glass rounded-[28px] p-2">
            <div data-reveal-stagger className="grid gap-4 rounded-[22px] bg-surface/70 p-5 sm:grid-cols-3">
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

          <section aria-labelledby="couriers" className="flex flex-col items-center gap-5 pt-20 text-center">
            <p id="couriers" data-reveal className="max-w-xl text-ink-soft">Reads the courier straight off your tracking slip, from local favourites to international carriers.</p>
            <div data-reveal className="-mx-4 w-screen max-w-[100vw] sm:mx-0 sm:w-full"><CourierMarquee /></div>
          </section>

          <section id="how" className="flex scroll-mt-24 flex-col gap-10 pb-8 pt-28">
            <div className="flex max-w-2xl flex-col gap-3">
              <h2 data-split="reveal" className="text-4xl leading-tight sm:text-[44px]">From open dispute to approved reply.</h2>
              <p data-reveal className="text-lg text-ink-soft">Three steps. SAL prepares; <span data-highlight>you decide</span>.</p>
            </div>
            <div data-reveal-stagger className="grid gap-5 sm:grid-cols-3">
              {STEPS.map((s) => (
                <div key={s.title} data-tilt className="glass flex flex-col gap-3.5 rounded-3xl p-7">
                  <span aria-hidden="true" className="glare" />
                  <svg aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--action)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{s.icon}</svg>
                  <h3 className="text-xl">{s.title}</h3>
                  <p className="text-ink-soft">{s.body}</p>
                </div>
              ))}
            </div>
          </section>

          <section id="features" className="flex scroll-mt-24 flex-col gap-10 pb-8 pt-24">
            <div className="flex max-w-2xl flex-col gap-3">
              <h2 data-split="reveal" className="text-4xl leading-tight sm:text-[44px]">The details that win a dispute.</h2>
              <p data-reveal className="text-lg text-ink-soft">Most disputes are lost on small things: a late reply, a date that doesn’t match, a tracking number PayPal can’t read.</p>
            </div>
            <div data-reveal-stagger className="grid gap-px overflow-hidden rounded-[28px] border border-hairline bg-hairline sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((f) => (
                <div key={f.title} className="flex flex-col gap-2 bg-ground/80 p-7">
                  <h3 className="text-lg">{f.title}</h3>
                  <p className="text-[15px] text-ink-soft">{f.body}</p>
                </div>
              ))}
            </div>
          </section>

          <section aria-label="SAL by the numbers" data-reveal-stagger className="grid grid-cols-2 gap-x-6 gap-y-10 pb-8 pt-24 lg:grid-cols-4">
            {figures.map((f) => (
              <div key={f.label} className="flex flex-col gap-2 border-t border-hairline pt-5">
                <span data-count={f.value} className="text-5xl font-semibold tracking-tight tabular-nums text-action sm:text-6xl">{f.value}</span>
                <span className="text-[15px] text-ink-soft">{f.label}</span>
              </div>
            ))}
          </section>

          <section aria-labelledby="who" className="flex flex-col gap-10 pb-8 pt-24">
            <h2 id="who" data-split="reveal" className="max-w-2xl text-4xl leading-tight sm:text-[44px]">Made for the people who answer disputes.</h2>
            <div data-reveal-stagger className="grid gap-5 sm:grid-cols-3">
              {AUDIENCES.map((a) => (
                <div key={a.title} className="flex flex-col gap-3 rounded-3xl border border-hairline p-7">
                  <h3 className="text-xl">{a.title}</h3>
                  <p className="text-ink-soft">{a.body}</p>
                </div>
              ))}
            </div>
          </section>

          <section id="trust" data-reveal-stagger className="grid scroll-mt-24 gap-5 pb-8 pt-24 sm:grid-cols-2">
            <div data-tilt className="panel-deep flex flex-col gap-3 rounded-[28px] p-10">
              <span aria-hidden="true" className="glare" />
              <h2 className="text-4xl leading-tight">Nothing goes to PayPal <span data-highlight>without you</span>.</h2>
              <p className="text-[17px] text-[#c9ccd3]">
                SAL prepares; you decide. It can’t send documents, accept a refund or message the customer on its own. If PayPal updates the
                case, you’re asked to review again.
              </p>
            </div>
            <div className="glass flex flex-col gap-4 rounded-[28px] p-10">
              <h2 className="text-2xl">Why you can trust the reply</h2>
              <ul className="flex flex-col gap-3">
                {TRUST.map((t) => (
                  <li key={t} className="flex gap-2.5"><Check />{t}</li>
                ))}
              </ul>
            </div>
          </section>

          <section className="my-28 flex flex-col items-center gap-5 rounded-[28px] panel-deep px-6 py-20 text-center">
            <h2 data-split="reveal" className="text-4xl leading-tight sm:text-[44px]">See it with practice cases.</h2>
            <p className="max-w-xl text-lg text-[#c9ccd3]">The demo uses a PayPal test account and made-up orders. No real customers or money involved.</p>
            <Link href="/disputes" className="btn-primary">Open the demo</Link>
          </section>
        </main>

        <footer className="glass -mx-4 border-x-0 border-b-0">
          <div className="mx-auto grid max-w-5xl gap-10 px-4 pb-8 pt-14 sm:grid-cols-[1.5fr_repeat(3,1fr)]">
            <div className="flex flex-col gap-2">
              <span className="text-lg font-semibold tracking-tight">SAL <span className="font-normal text-ink-muted">Resolve</span></span>
              <p className="max-w-xs text-sm text-ink-muted">The evidence copilot for PayPal disputes. SAL prepares; you decide.</p>
            </div>
            {FOOTER.map((col) => (
              <nav key={col.title} aria-label={col.title} className="flex flex-col gap-2.5 text-sm">
                <span className="font-semibold">{col.title}</span>
                {col.links.map(([label, href]) => (
                  <a key={label} href={href} className="text-ink-soft">{label}</a>
                ))}
              </nav>
            ))}
          </div>
          <div className="mx-auto max-w-5xl border-t border-hairline px-4 py-6 text-sm text-ink-muted">
            SAL Resolve · MIT licensed · Not affiliated with or endorsed by PayPal.
          </div>
        </footer>
      </div>
    </>
  );
}
