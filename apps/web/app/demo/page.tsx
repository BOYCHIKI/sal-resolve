import { Logo } from "@/components/Logo";
import type { Metadata } from "next";
import Link from "next/link";
import { AgentRunPanel } from "@/components/AgentRunPanel";
import { Ticker } from "@/components/landing/Ticker";
import { api, type AgentRun, type Dispute } from "@/lib/api";
import { money } from "@/lib/format";
import { CASE_TYPES, caseTypeOf, origin } from "@/lib/plain";

export const metadata: Metadata = {
  title: "Try the demo — SAL Resolve",
  description: "Check a deal before delivery, watch two AI agents make a deal through SAL, and see how SAL handles each PayPal dispute.",
};

export const dynamic = "force-dynamic";

const PER_TYPE = 2;   // examples per dispute kind; the rest are on the disputes page

const SAMPLES = [
  { file: "1-purchase-order-PO-DEMO-1001.pdf", label: "Purchase order", result: "Add first" },
  { file: "3-invoice-wrong-quantity.pdf", label: "Invoice, wrong quantity", result: "On hold" },
  { file: "2-invoice-matches.pdf", label: "Invoice, matches", result: "Clear" },
];

function byKind(disputes: Dispute[]): Map<string, Dispute[]> {
  const out = new Map<string, Dispute[]>();
  const sorted = [...disputes].sort((a, b) => Number(a.origin === "PAYPAL_SANDBOX") - Number(b.origin === "PAYPAL_SANDBOX"));
  for (const d of sorted) {
    const key = caseTypeOf(d).key;
    out.set(key, [...(out.get(key) ?? []), d]);
  }
  return out;
}

function Section({ id, title, lead, children }: { id: string; title: string; lead: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 id={id} className="text-[20px] font-semibold tracking-tight">{title}</h2>
        <p className="muted text-[15px]">{lead}</p>
      </div>
      {children}
    </section>
  );
}

function DealCheck() {
  return (
    <Section id="deal-check" title="Check a deal before delivery" lead="Add the purchase order, then an invoice. Any difference puts the deal on hold.">
      <div className="lp-card flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:p-6">
        <ol className="flex flex-1 flex-col divide-y divide-(--lp-line)">
          {SAMPLES.map((s, i) => (
            <li key={s.file} className="grid grid-cols-[1fr_auto_auto] items-center gap-4 py-2.5 text-[15px]">
              <span><span className="muted">{i + 1}.</span> <span className="font-semibold">{s.label}</span></span>
              <span className="muted">{s.result}</span>
              <a href={`/samples/${s.file}`} download className="font-semibold text-(--lp-blue) hover:underline">PDF</a>
            </li>
          ))}
        </ol>
        <Link href="/deals" className="lp-btn shrink-0">Open deals</Link>
      </div>
    </Section>
  );
}

function Agents({ run }: { run: AgentRun | null }) {
  return (
    <Section id="agents" title="Two AI agents make a deal through SAL" lead="Each agent has its own key and picks its own steps. The wrong invoice is planted, so every run shows a hold.">
      <div className="lp-card p-5 sm:p-6">
        <AgentRunPanel run={run} />
      </div>
    </Section>
  );
}

function Example({ d }: { d: Dispute }) {
  return (
    <Link href={`/disputes/${d.id}`} className="group flex items-center justify-between gap-3 py-0.5 text-[15px]">
      <span className="min-w-0 truncate"><span className="font-semibold">{d.summary?.item ?? "Order"}</span>
        <span className="muted"> · {money(d.amount)} · {origin(d.origin)}</span></span>
      <span aria-hidden="true" className="text-(--lp-blue) transition-transform group-hover:translate-x-1">→</span>
    </Link>
  );
}

function Disputes({ disputes }: { disputes: Dispute[] | null }) {
  const groups = byKind(disputes ?? []);
  return (
    <Section id="disputes" title="If a dispute still comes" lead="What SAL does for each kind. Nothing goes to PayPal without your OK.">
      {disputes === null ? (
        <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">SAL can’t reach its server right now. Try again in a moment.</p>
      ) : (
        <ul className="lp-card flex flex-col divide-y divide-(--lp-line)">
          {CASE_TYPES.map((type) => {
            const cases = groups.get(type.key) ?? [];
            return (
              <li key={type.key} className="grid gap-x-6 gap-y-1 px-5 py-4 sm:px-6 md:grid-cols-[180px_1fr_minmax(220px,300px)]">
                <h3 className="text-[15px] font-semibold">{type.title}</h3>
                <p className="muted text-[15px]">{type.sal}</p>
                <div className="flex flex-col">
                  {cases.slice(0, PER_TYPE).map((d) => <Example key={d.id} d={d} />)}
                  {cases.length > PER_TYPE && (
                    <Link href="/disputes" className="muted text-[14px] hover:underline">+{cases.length - PER_TYPE} more</Link>
                  )}
                </div>
              </li>
            );
          })}
          <li className="grid items-center gap-x-6 gap-y-2 px-5 py-4 sm:px-6 md:grid-cols-[180px_1fr_minmax(220px,300px)]">
            <h3 className="text-[15px] font-semibold">Packing proof</h3>
            <p className="muted text-[15px]">Photos of the item going into the box, added to the case if the buyer says it was wrong.</p>
            <Link href="/packing" className="font-semibold text-(--lp-blue) hover:underline">Try packing proof →</Link>
          </li>
        </ul>
      )}
    </Section>
  );
}

export default async function DemoPage() {
  const [disputes, run] = await Promise.all([api.listDisputes().catch(() => null), api.latestAgentRun().catch(() => null)]);

  return (
    <div className="lp sky min-h-screen">
      <Ticker />

      <header className="border-b border-(--lp-line)">
        <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <Link href="/" aria-label="SAL Resolve home"><Logo /></Link>
          <span className="flex items-center gap-2">
            <Link href="/deals" className="lp-btn-ghost hidden sm:inline-flex">Deals</Link>
            <Link href="/disputes" className="lp-btn-ghost hidden sm:inline-flex">Disputes</Link>
          </span>
        </nav>
      </header>

      <main className="px-4">
        <div className="mx-auto flex max-w-6xl flex-col gap-10 pb-16 pt-8">
          <div className="flex flex-col gap-1">
            <h1 className="text-[28px] font-semibold tracking-tight sm:text-[32px]">Try SAL</h1>
            <p className="muted text-[16px]">Catch a wrong invoice before delivery, and answer a dispute if one still comes.</p>
          </div>
          <DealCheck />
          <Agents run={run} />
          <Disputes disputes={disputes} />
        </div>
      </main>

      <footer className="muted mx-auto max-w-6xl border-t border-(--lp-line) px-4 py-6 text-sm">
        © 2026 SAL Resolve · Not affiliated with or endorsed by PayPal.
      </footer>
    </div>
  );
}
