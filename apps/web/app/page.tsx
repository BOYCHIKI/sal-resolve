import type { Metadata } from "next";
import Link from "next/link";
import { CaseMockup } from "@/components/landing/CaseMockup";
import { HeroOrbits } from "@/components/landing/HeroOrbits";
import { Check, Label } from "@/components/landing/Label";
import { Ticker } from "@/components/landing/Ticker";
import { SalMascot } from "@/components/mascot/SalMascot";

export const metadata: Metadata = {
  title: "SAL Resolve — catch the mistake before delivery",
  description: "SAL checks every order against its invoice before you deliver, and keeps the proof ready if a PayPal dispute comes anyway. You approve before anything is sent.",
};

const STEPS = [
  {
    title: "Add the order and the invoice",
    body: "Upload a PDF or a photo, or let an AI agent send them. SAL reads each value and leaves a blank when it can’t find it on the page.",
  },
  {
    title: "SAL compares them on its own",
    body: "Items, quantities, prices, totals, the approved limit and the address. Any difference holds the deal before you deliver.",
  },
  {
    title: "If a dispute comes, the proof is ready",
    body: "A matched deal joins the dispute on that payment. SAL prepares a reply from your documents, and you approve it before it goes to PayPal.",
  },
];

// Each card names something the product does today; nothing here is a promise.
const FEATURES = [
  { title: "Line-by-line match", body: "Every item, quantity and unit price on the invoice is compared with the order.",
    icon: <><path d="M4 6h16M4 12h16M4 18h10" /></> },
  { title: "Approved limit", body: "An invoice over the buyer’s limit, or issued after their approval ended, is held.",
    icon: <><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M8 15l3-3 2 2 3-4" /></> },
  { title: "Read beside the page", body: "You compare what SAL read with the document before a deal is created.",
    icon: <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></> },
  { title: "A correction to send", body: "SAL writes the message from the differences it found. You pass it on.",
    icon: <><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4 20-7z" /></> },
  { title: "Dispute deadlines", body: "Every PayPal case shows the time left to reply, with the most urgent on top.",
    icon: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></> },
  { title: "Approval tied to proof", body: "If a document or the case changes after you approve, the approval lapses and you review again.",
    icon: <><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M9 12l2 2 4-4" /></> },
];

const TRUST = [
  "Every sentence in a reply comes from one of your documents.",
  "Instructions hidden in a document are treated as text, never followed.",
  "The verdict comes from fixed rules, not from an AI’s opinion.",
  "Your business data is kept separate from every other business.",
];

const AUDIENCES = ["freelancers and agencies", "small sellers across borders", "teams using AI agents"];

const figures = [
  { value: 9, label: "kinds of difference checked" },
  { value: 3, label: "deal types: goods, digital, services" },
  { value: 2, label: "sides compared: order and invoice" },
  { value: 0, label: "replies sent without your approval" },
];

const FOOTER = [
  { title: "Product", links: [["How it works", "#how"], ["What it checks", "#features"], ["AI agents", "#agents"]] },
  { title: "Demo", links: [["Deal Check", "/deals"], ["Practice disputes", "/demo"]] },
  { title: "Project", links: [["Security", "/security"], ["Source on GitHub", "https://github.com/BOYCHIKI/sal-resolve"], ["MIT licence", "https://github.com/BOYCHIKI/sal-resolve/blob/main/LICENSE"]] },
];

const Icon = ({ children }: { children: React.ReactNode }) => (
  <svg aria-hidden="true" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="var(--lp-blue)" strokeWidth="1.6"
    strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);

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
          <span className="display text-xl whitespace-nowrap">SAL <span className="muted">Resolve</span></span>
          {/* On phones the section links would crowd the bar; the page is one scroll, so keep only the CTA. */}
          <div className="flex items-center gap-1 text-sm">
            <a href="#how" className="muted hidden px-3.5 py-2.5 md:inline">How it works</a>
            <a href="#features" className="muted hidden px-3.5 py-2.5 md:inline">What it checks</a>
            <a href="#agents" className="muted hidden px-3.5 py-2.5 md:inline">AI agents</a>
            <Link href="/login" className="muted px-3.5 py-2.5">Sign in</Link>
            <Link href="/signup" className="lp-btn">Get started</Link>
          </div>
        </nav>
      </header>

      <main>
        <section className="relative overflow-hidden px-4">
          <HeroOrbits />
          <div className="relative mx-auto flex max-w-5xl flex-col items-center gap-7 pb-16 pt-20 text-center sm:pt-28">
            <span data-reveal><Label>The deal checker for PayPal sellers</Label></span>
            <h1 data-split="reveal" className="display text-[44px] sm:text-7xl lg:text-[96px]">
              Catch the mistake before delivery.
            </h1>
            <p data-reveal className="muted max-w-2xl text-lg sm:text-xl">
              SAL checks every order against its invoice, <strong>holds what doesn’t match</strong>, and keeps your proof ready if a
              dispute comes anyway.
            </p>
            <div data-reveal className="flex flex-wrap justify-center gap-3">
              <Link href="/deals" className="lp-btn">Try Deal Check</Link>
              <Link href="/demo" className="lp-btn-ghost">Open the demo</Link>
            </div>
            <ul data-reveal-stagger className="muted flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm">
              <li className="flex gap-2"><Check />Goods, digital and services</li>
              <li className="flex gap-2"><Check />Nothing sent without you</li>
              <li className="flex gap-2"><Check />Built on PayPal’s Disputes API</li>
            </ul>
          </div>
          <div data-tilt-in className="lp-dashed relative mx-auto mb-20 max-w-5xl rounded-[24px] p-2 sm:p-4">
            <Crosses />
            <CaseMockup />
          </div>
        </section>

        <section aria-label="SAL by the numbers" className="border-y border-(--lp-line) px-4">
          <ul data-reveal-stagger className="mx-auto grid max-w-6xl grid-cols-2 lg:grid-cols-4">
            {figures.map((f, i) => (
              <li key={f.label} className={`flex flex-col gap-2 border-(--lp-line) px-5 py-10 ${i % 2 ? "border-l" : ""} ${i > 1 ? "border-t lg:border-t-0" : ""} ${i === 2 ? "lg:border-l" : ""}`}>
                <span data-count={f.value} className="display text-6xl tabular-nums text-(--lp-mint)">{f.value}</span>
                <span className="muted text-[15px]">{f.label}</span>
              </li>
            ))}
          </ul>
        </section>

        <section id="features" className="scroll-mt-16 px-4 py-24">
          <div className="mx-auto flex max-w-6xl flex-col gap-12">
            <div className="flex max-w-3xl flex-col items-start gap-5">
              <Label>What it checks</Label>
              <h2 data-split="reveal" className="display text-4xl sm:text-6xl">The small details that turn into disputes.</h2>
            </div>
            <div data-reveal-stagger className="grid gap-px overflow-hidden rounded-[20px] border border-(--lp-line) bg-(--lp-line) sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((f) => (
                <div key={f.title} className="flex flex-col gap-4 bg-(--lp-card) p-8">
                  <Icon>{f.icon}</Icon>
                  <h3 className="display text-xl">{f.title}</h3>
                  <p className="muted text-[15px]">{f.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="how" className="lp-light scroll-mt-16 px-4 py-24">
          <div className="mx-auto flex max-w-6xl flex-col gap-12">
            <div className="flex max-w-3xl flex-col items-start gap-5">
              <Label>How it works</Label>
              <h2 data-split="reveal" className="display text-4xl sm:text-6xl">Three steps. SAL prepares, you decide.</h2>
            </div>
            <ol data-reveal-stagger className="grid gap-5 md:grid-cols-3">
              {STEPS.map((s, i) => (
                <li key={s.title} className="lp-card flex flex-col gap-4 p-7">
                  <span className="display text-4xl text-(--lp-blue)">0{i + 1}</span>
                  <h3 className="text-xl font-semibold">{s.title}</h3>
                  <p className="muted">{s.body}</p>
                </li>
              ))}
            </ol>
            <p className="muted text-[15px]">Made for {AUDIENCES.join(" · ")}.</p>
          </div>
        </section>

        <section id="agents" className="scroll-mt-16 px-4 py-24">
          <div data-reveal-stagger className="mx-auto grid max-w-6xl gap-5 md:grid-cols-2">
            <div className="lp-card flex flex-col items-start gap-5 p-8 sm:p-10">
              <Label>AI agents</Label>
              <h2 className="display text-4xl sm:text-5xl">When agents trade, SAL checks the deal.</h2>
              <p className="muted text-[17px]">
                Each agent gets its own revocable identity and role. A buyer’s agent sends the order, a seller’s agent sends the invoice,
                and SAL compares what they agreed. SAL never buys, pays or holds money. Our demo uses simulated agents.
              </p>
            </div>
            <div className="lp-card flex flex-col items-start gap-5 p-8 sm:p-10">
              <Label>Why trust it</Label>
              <h2 className="display text-4xl sm:text-5xl">Nothing goes to PayPal <span className="text-(--lp-mint)">without you</span>.</h2>
              <ul className="flex flex-col gap-3">
                {TRUST.map((t) => (
                  <li key={t} className="muted flex gap-2.5"><Check />{t}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section className="px-4 pb-24">
          <div className="lp-dashed relative mx-auto max-w-6xl rounded-[24px]">
            <Crosses />
            <div aria-hidden="true" className="lp-dots absolute inset-0" />
            <div className="relative flex flex-col items-center gap-6 px-6 py-16 text-center">
              <SalMascot pose="happy" size={120} />
              <h2 className="display text-4xl sm:text-6xl">See it with practice cases.</h2>
              <p className="muted max-w-xl text-lg">A PayPal test account and made-up orders. No real customers or money involved.</p>
              <div className="flex flex-wrap justify-center gap-3">
                <Link href="/deals" className="lp-btn">Try Deal Check</Link>
                <Link href="/demo" className="lp-btn-ghost">Open a practice dispute</Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-(--lp-line) px-4">
        <div className="mx-auto grid max-w-6xl gap-10 pb-8 pt-14 sm:grid-cols-[1.5fr_repeat(3,1fr)]">
          <div className="flex flex-col gap-2">
            <span className="display text-xl">SAL <span className="muted">Resolve</span></span>
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
