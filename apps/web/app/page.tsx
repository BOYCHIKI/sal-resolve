import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { CourierMarquee, COURIERS, MARKETS } from "@/components/CourierMarquee";
import { CaseMockup } from "@/components/landing/CaseMockup";
import { RouteMap } from "@/components/landing/RouteMap";
import { HeroOrbits } from "@/components/landing/HeroOrbits";
import { Check, Label } from "@/components/landing/Label";
import { Ticker } from "@/components/landing/Ticker";
import { SalMascot } from "@/components/mascot/SalMascot";
import { SalSays } from "@/components/mascot/SalSays";

export const metadata: Metadata = {
  title: "SAL Resolve — the evidence copilot for PayPal disputes",
  description: "When a customer says an order never arrived, SAL checks your documents, flags what doesn’t add up and drafts the reply. You approve before anything is sent.",
};

const HEADLINE = "Know what your proof shows before you reply.";

const STEPS = [
  {
    title: "Your disputes, in one list",
    body: "SAL picks up new disputes from PayPal and shows what the customer claims, how much is at stake, and how many days you have left to reply.",
    icon: <path d="M4 6h16M4 12h16M4 18h10" />,
  },
  {
    title: "Your documents, checked for you",
    body: "SAL reads your invoice, payment receipt and delivery records, and tells you in plain words if proof is missing or two documents disagree.",
    icon: <><path d="M9 11l3 3 8-8" /><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9" /></>,
  },
  {
    title: "You approve, then send",
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
  { value: COURIERS.length, label: "couriers recognised on a tracking slip" },
  { value: MARKETS, label: "Southeast Asian markets with local couriers" },
  { value: 3, label: "kinds of proof checked: invoice, payment, delivery" },
  { value: 0, label: "replies sent without your approval" },
];

const FOOTER = [
  { title: "Product", links: [["How it works", "#how"], ["What it checks", "#features"], ["Why trust it", "#trust"]] },
  { title: "Demo", links: [["Open the demo", "/demo"], ["Practice cases", "/disputes"]] },
  { title: "Project", links: [["Source on GitHub", "https://github.com/BOYCHIKI/sal-resolve"], ["MIT licence", "https://github.com/BOYCHIKI/sal-resolve/blob/main/LICENSE"]] },
];

// Registration marks on the four corners of a dashed frame.
const Crosses = () => (
  <>
    <span aria-hidden="true" className="lp-cross -left-[6px] -top-[6px]" />
    <span aria-hidden="true" className="lp-cross -right-[6px] -top-[6px]" />
    <span aria-hidden="true" className="lp-cross -bottom-[6px] -left-[6px]" />
    <span aria-hidden="true" className="lp-cross -bottom-[6px] -right-[6px]" />
  </>
);

export default function Landing() {
  return (
    <div className="lp sky min-h-screen">
      <Ticker />

      <header data-nav className="lp-nav sticky top-0 z-10 border-b border-(--lp-line) bg-(--lp-card) backdrop-blur-xl">
        <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <span className="display text-xl whitespace-nowrap">SAL <span className="muted font-semibold">Resolve</span></span>
          {/* On phones the section links would crowd the bar; the page is one scroll, so keep only the CTA. */}
          <div className="flex items-center gap-1 text-sm">
            <a href="#how" className="muted hidden px-3.5 py-2.5 md:inline">How it works</a>
            <a href="#features" className="muted hidden px-3.5 py-2.5 md:inline">What it checks</a>
            <a href="#trust" className="muted hidden px-3.5 py-2.5 md:inline">Why trust it</a>
            <Link href="/demo" className="lp-btn">Open the demo</Link>
          </div>
        </nav>
      </header>

      <main>
        <section className="relative overflow-hidden px-4">
          <HeroOrbits />
          <div className="relative mx-auto flex max-w-6xl flex-col items-center gap-5 pb-4 pt-14 text-center sm:pt-20">
            <span data-reveal><Label>The evidence copilot for PayPal disputes</Label></span>
            {/* SAL says the headline: a speech bubble pops up beside it and the words arrive one by one (globals.css, .speech). */}
            <SalSays reveal={false} mascot={<SalMascot pose="wave" size={170} />} bubbleClassName="speech-hero max-w-3xl px-6 py-6 sm:px-9 sm:py-8">
              <p className="speech-after mb-2 text-sm font-semibold text-(--lp-blue)">Hi, I’m SAL.</p>
              <h1 className="display text-[32px] sm:text-5xl lg:text-[56px]">
                <span className="sr-only">{HEADLINE}</span>
                {HEADLINE.split(" ").map((word, i) => (
                  <span key={i} aria-hidden="true">
                    <span className="speech-word" style={{ "--i": i } as React.CSSProperties}>{word}</span>{" "}
                  </span>
                ))}
              </h1>
              <p className="speech-after speech-late muted mt-4 text-lg">
                I read your PayPal record, invoice and delivery documents, <strong>flag what’s missing</strong>, and draft a reply
                you approve.
              </p>
            </SalSays>
            <div data-reveal className="flex flex-wrap justify-center gap-3">
              <Link href="/demo" className="lp-btn">Open the demo</Link>
              <a href="#how" className="lp-btn-ghost lp-ring">See how it works</a>
            </div>
            <ul data-reveal-stagger className="muted flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm">
              <li className="flex gap-2"><Check />Facts from your documents only</li>
              <li className="flex gap-2"><Check />Nothing sent without you</li>
              <li className="flex gap-2"><Check />Built on PayPal’s Disputes API</li>
            </ul>
          </div>

          {/* A dashed line runs from the promise above into the screen that keeps it. */}
          <div aria-hidden="true" className="relative mx-auto h-10 w-px">
            <span data-grow className="absolute inset-0 border-l border-dashed border-(--lp-line-strong)" />
            <span className="lp-drip" />
          </div>
          <div data-tilt-in className="lp-dashed relative mx-auto mb-24 max-w-5xl rounded-[24px] p-2 sm:p-4">
            <Crosses />
            <CaseMockup />
          </div>
        </section>

        <section aria-labelledby="couriers" className="border-t border-(--lp-line) px-4 py-24">
          <div className="mx-auto flex max-w-6xl flex-col gap-10">
            <div className="flex max-w-3xl flex-col items-start gap-5">
              <Label>Couriers</Label>
              <h2 id="couriers" data-split="reveal" className="display text-4xl sm:text-6xl">Read straight off your tracking slip.</h2>
              <p data-reveal className="muted text-lg">From local favourites to international carriers, in the courier names you already use.</p>
            </div>
            <div data-reveal className="-mx-4 sm:mx-0"><CourierMarquee /></div>
            <div className="grid items-center gap-10 pt-6 lg:grid-cols-[1.1fr_1fr]">
              <div className="mx-auto w-full max-w-md lg:max-w-none"><RouteMap /></div>
              <ul aria-label="SAL by the numbers" data-reveal-stagger className="grid grid-cols-2 gap-x-6 gap-y-10">
                {figures.map((f) => (
                  <li key={f.label} className="flex flex-col gap-2 border-t border-dashed border-(--lp-line-strong) pt-5">
                    <span data-count={f.value} className="display text-6xl tabular-nums text-(--lp-mint) sm:text-7xl">{f.value}</span>
                    <span className="muted text-[15px]">{f.label}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section id="how" className="lp-light scroll-mt-16 px-4 py-24">
          <div className="mx-auto flex max-w-6xl flex-col gap-12">
            <div className="flex max-w-3xl flex-col items-start gap-5">
              <Label>How it works</Label>
              <h2 data-split="reveal" className="display text-4xl sm:text-6xl">From open dispute to approved reply.</h2>
              <p data-reveal className="muted text-lg">Three steps. SAL prepares; <strong>you decide</strong>.</p>
            </div>
            <ol data-reveal-stagger className="grid gap-5 md:grid-cols-3">
              {STEPS.map((s, i) => (
                <li key={s.title} className="lp-card flex flex-col gap-4 p-7">
                  <div className="flex items-center justify-between">
                    <svg aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--lp-blue)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{s.icon}</svg>
                    <span className="display text-3xl text-(--lp-line-strong)">0{i + 1}</span>
                  </div>
                  <h3 className="text-xl font-semibold">{s.title}</h3>
                  <p className="muted">{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="features" className="scroll-mt-16 px-4 py-24">
          <div className="mx-auto flex max-w-6xl flex-col gap-12">
            <div className="flex max-w-3xl flex-col items-start gap-5">
              <Label>What it checks</Label>
              <h2 data-split="reveal" className="display text-4xl sm:text-6xl">The details that win a dispute.</h2>
            </div>
            <SalSays mascot={<Image src="/mascot/sal-focus.png" alt="" width={571} height={527} className="h-auto w-36" />}
              className="lg:self-start" bubbleClassName="max-w-2xl px-6 py-5 sm:px-8 sm:py-6">
              <p className="text-lg">
                Most disputes are lost on small things: a late reply, a date that doesn’t match, a tracking number PayPal can’t read.
                <strong> I check each one before you reply.</strong>
              </p>
            </SalSays>
            <div data-reveal-stagger className="grid gap-px overflow-hidden rounded-[20px] border border-(--lp-line) bg-(--lp-line) sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((f) => (
                <div key={f.title} className="flex flex-col gap-2 bg-(--lp-card) p-7">
                  <h3 className="text-lg font-semibold">{f.title}</h3>
                  <p className="muted text-[15px]">{f.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section aria-labelledby="who" className="border-t border-(--lp-line) px-4 py-24">
          <div className="mx-auto flex max-w-6xl flex-col gap-12">
            <div className="flex max-w-3xl flex-col items-start gap-5">
              <Label>Who it’s for</Label>
              <h2 id="who" data-split="reveal" className="display text-4xl sm:text-6xl">Made for the people who answer disputes.</h2>
            </div>
            <div data-reveal-stagger className="grid gap-5 md:grid-cols-3">
              {AUDIENCES.map((a) => (
                <div key={a.title} className="lp-card flex flex-col gap-3 p-7">
                  <h3 className="text-xl font-semibold">{a.title}</h3>
                  <p className="muted">{a.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="trust" className="scroll-mt-16 border-t border-(--lp-line) px-4 py-24">
          <div data-reveal-stagger className="mx-auto grid max-w-6xl gap-5 md:grid-cols-2">
            <div className="flex flex-col items-start gap-5 rounded-[20px] border border-(--lp-line-strong) bg-(--lp-card-2) p-8 sm:p-10">
              <Label>Why trust it</Label>
              <h2 className="display text-4xl sm:text-5xl">Nothing goes to PayPal <span className="text-(--lp-mint)">without you</span>.</h2>
              <p data-scrub-text className="text-[17px]">
                SAL prepares; you decide. It can’t send documents, accept a refund or message the customer on its own. If PayPal updates the
                case, you’re asked to review again.
              </p>
            </div>
            <div className="lp-card flex flex-col gap-5 p-8 sm:p-10">
              <h2 className="text-2xl font-semibold">Why you can trust the reply</h2>
              <ul className="flex flex-col gap-3">
                {TRUST.map((t) => (
                  <li key={t} className="muted flex gap-2.5"><Check />{t}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section className="px-4 pb-24">
          <div className="lp-dashed relative mx-auto max-w-6xl overflow-visible rounded-[24px]">
            <Crosses />
            <div aria-hidden="true" className="lp-dots absolute inset-0" />
            <div className="relative flex justify-center px-6 py-16">
              <SalSays mascot={<SalMascot pose="happy" size={150} />} bubbleClassName="flex max-w-xl flex-col items-start gap-4 px-6 py-6 sm:px-9 sm:py-8">
                <h2 className="display text-4xl sm:text-5xl">See it with practice cases.</h2>
                <p className="muted text-lg">I’ll walk you through a dispute on a PayPal test account, with made-up orders. No real customers or money involved.</p>
                <Link href="/demo" className="lp-btn">Open the demo</Link>
              </SalSays>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-(--lp-line) px-4">
        <div className="mx-auto grid max-w-6xl gap-10 pb-8 pt-14 sm:grid-cols-[1.5fr_repeat(3,1fr)]">
          <div className="flex flex-col gap-2">
            <span className="display text-xl">SAL <span className="muted font-semibold">Resolve</span></span>
            <p className="muted max-w-xs text-sm">The evidence copilot for PayPal disputes. SAL prepares; you decide.</p>
          </div>
          {FOOTER.map((col) => (
            <nav key={col.title} aria-label={col.title} className="flex flex-col gap-2.5 text-sm">
              <span className="font-semibold">{col.title}</span>
              {col.links.map(([label, href]) => (
                <a key={label} href={href} className="muted">{label}</a>
              ))}
            </nav>
          ))}
        </div>
        <div className="muted mx-auto max-w-6xl border-t border-(--lp-line) py-6 text-sm">
          SAL Resolve · MIT licensed · Not affiliated with or endorsed by PayPal.
        </div>
      </footer>
    </div>
  );
}
