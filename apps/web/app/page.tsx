import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { CaseMockup } from "@/components/landing/CaseMockup";
import { HeroOrbits } from "@/components/landing/HeroOrbits";
import { Check, Label } from "@/components/landing/Label";
import { Ticker } from "@/components/landing/Ticker";
import { SalMascot } from "@/components/mascot/SalMascot";
import { SalSays } from "@/components/mascot/SalSays";

export const metadata: Metadata = {
  title: "SAL Resolve — catch the mistake before delivery",
  description: "SAL checks every order against its invoice before you deliver, and keeps the proof ready if a PayPal dispute comes anyway. You approve before anything is sent.",
};

const HEADLINE = "Catch the mistake before delivery.";

const STEPS = [
  {
    title: "Add the order and the invoice",
    body: "Upload a PDF or a photo, or let an AI agent send them. SAL reads each value and leaves a blank when it can’t find it on the page.",
    icon: <path d="M4 6h16M4 12h16M4 18h10" />,
  },
  {
    title: "SAL compares them on its own",
    body: "Items, quantities, prices, totals, the approved limit and the address. Any difference holds the deal before you deliver.",
    icon: <><path d="M9 11l3 3 8-8" /><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9" /></>,
  },
  {
    title: "If a dispute comes, the proof is ready",
    body: "A matched deal joins the dispute on that payment. SAL prepares a reply from your documents, and you approve it before it goes to PayPal.",
    icon: <><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4 20-7z" /></>,
  },
];

// Each card names something the product does today; nothing here is a promise.
const FEATURES = [
  { title: "Line-by-line match", body: "Every item, quantity and unit price on the invoice is compared with the order." },
  { title: "Approved limit", body: "An invoice over the buyer’s limit, or issued after their approval ended, is held." },
  { title: "Every value shown beside the page", body: "You compare what SAL read with the document before a deal is created." },
  { title: "A correction you can send", body: "SAL writes the message from the differences it found. You pass it on." },
  { title: "Dispute deadlines", body: "Every PayPal case shows the time left to reply, with the most urgent on top." },
  { title: "Approval tied to the proof", body: "If a document or the case changes after you approve, the approval lapses and you review again." },
];

const TRUST = [
  "Every sentence in a reply comes from one of your documents.",
  "Instructions hidden in a document are treated as text, never followed.",
  "The verdict comes from fixed rules, not from an AI’s opinion.",
  "Your business data is kept separate from every other business.",
];

const AUDIENCES = [
  { title: "Freelancers and agencies", body: "Bill clients anywhere by PayPal invoice, and check the hours, scope and total against what they ordered." },
  { title: "Small sellers across borders", body: "One person handles orders and paperwork. SAL catches a wrong item, price or address before it ships." },
  { title: "Teams using AI agents", body: "Buyer and seller agents each get their own identity, and SAL checks what they agreed." },
];

const figures = [
  { value: 9, label: "kinds of difference checked before delivery" },
  { value: 3, label: "deal types: goods, digital and services" },
  { value: 2, label: "sides checked: the order and the invoice" },
  { value: 0, label: "replies sent without your approval" },
];

const FOOTER = [
  { title: "Product", links: [["How it works", "#how"], ["What it checks", "#features"], ["AI agents", "#agents"], ["Why trust it", "#trust"]] },
  { title: "Demo", links: [["Deal Check", "/deals"], ["Practice disputes", "/demo"]] },
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
            <a href="#agents" className="muted hidden px-3.5 py-2.5 md:inline">AI agents</a>
            <a href="#trust" className="muted hidden px-3.5 py-2.5 md:inline">Why trust it</a>
            <Link href="/demo" className="lp-btn">Open the demo</Link>
          </div>
        </nav>
      </header>

      <main>
        <section className="relative overflow-hidden px-4">
          <HeroOrbits />
          <div className="relative mx-auto flex max-w-6xl flex-col items-center gap-5 pb-4 pt-14 text-center sm:pt-20">
            <span data-reveal><Label>The deal checker for PayPal sellers worldwide</Label></span>
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
                I check every order against its invoice, <strong>hold what doesn’t match</strong>, and keep your proof ready if a
                dispute comes anyway.
              </p>
            </SalSays>
            <div data-reveal className="flex flex-wrap justify-center gap-3">
              <Link href="/deals" className="lp-btn">Try Deal Check</Link>
              <a href="#how" className="lp-btn-ghost lp-ring">See how it works</a>
            </div>
            <ul data-reveal-stagger className="muted flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm">
              <li className="flex gap-2"><Check />Goods, digital and services</li>
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

        <section aria-labelledby="problem" className="border-t border-(--lp-line) px-4 py-24">
          <div className="mx-auto flex max-w-6xl flex-col gap-10">
            <div className="flex max-w-3xl flex-col items-start gap-5">
              <Label>Why before delivery</Label>
              <h2 id="problem" data-split="reveal" className="display text-4xl sm:text-6xl">Proof can’t be made after a dispute.</h2>
              <p data-reveal className="muted text-lg">
                Once a buyer complains, the order, the invoice and what you agreed are already fixed. SAL checks them while you can still fix them.
              </p>
            </div>
            <ul aria-label="SAL by the numbers" data-reveal-stagger className="grid grid-cols-2 gap-x-6 gap-y-10 lg:grid-cols-4">
              {figures.map((f) => (
                <li key={f.label} className="flex flex-col gap-2 border-t border-dashed border-(--lp-line-strong) pt-5">
                  <span data-count={f.value} className="display text-6xl tabular-nums text-(--lp-mint) sm:text-7xl">{f.value}</span>
                  <span className="muted text-[15px]">{f.label}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="how" className="lp-light scroll-mt-16 px-4 py-24">
          <div className="mx-auto flex max-w-6xl flex-col gap-12">
            <div className="flex max-w-3xl flex-col items-start gap-5">
              <Label>How it works</Label>
              <h2 data-split="reveal" className="display text-4xl sm:text-6xl">From order to proof, before anything goes wrong.</h2>
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
              <h2 data-split="reveal" className="display text-4xl sm:text-6xl">The small details that turn into disputes.</h2>
            </div>
            <SalSays mascot={<Image src="/mascot/sal-focus.png" alt="" width={571} height={527} className="h-auto w-36" />}
              className="lg:self-start" bubbleClassName="max-w-2xl px-6 py-5 sm:px-8 sm:py-6">
              <p className="text-lg">
                A wrong item code, an extra hour on the bill, an address that changed along the way.
                <strong> I compare each one before you deliver.</strong>
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
              <h2 id="who" data-split="reveal" className="display text-4xl sm:text-6xl">Made for sellers paid through PayPal, anywhere.</h2>
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

        <section id="agents" className="scroll-mt-16 border-t border-(--lp-line) px-4 py-24">
          <div className="mx-auto flex max-w-6xl flex-col gap-5">
            <Label>AI agents</Label>
            <h2 data-split="reveal" className="display max-w-3xl text-4xl sm:text-6xl">When agents buy and sell, someone has to check the deal.</h2>
            <p data-reveal className="muted max-w-3xl text-lg">
              Each agent gets its own revocable identity and role. A buyer’s agent sends the order, a seller’s agent sends the invoice, and SAL
              compares what they agreed. SAL never buys, pays or holds money. Our demo uses simulated agents.
            </p>
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
                <div className="flex flex-wrap gap-3">
                  <Link href="/deals" className="lp-btn">Try Deal Check</Link>
                  <Link href="/demo" className="lp-btn-ghost">Open a practice dispute</Link>
                </div>
              </SalSays>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-(--lp-line) px-4">
        <div className="mx-auto grid max-w-6xl gap-10 pb-8 pt-14 sm:grid-cols-[1.5fr_repeat(3,1fr)]">
          <div className="flex flex-col gap-2">
            <span className="display text-xl">SAL <span className="muted font-semibold">Resolve</span></span>
            <p className="muted max-w-xs text-sm">The deal checker for PayPal sellers worldwide. SAL prepares; you decide.</p>
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
