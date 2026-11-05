import type { Metadata } from "next";
import Link from "next/link";
import { AppHeader } from "@/components/AppHeader";
import { api, auth, type AgentAction, type Deal, type DealDocument } from "@/lib/api";

export const metadata: Metadata = { title: "Home — SAL Resolve" };
export const dynamic = "force-dynamic";

const MAX_WAITING = 5;

type Waiting = { href: string; what: string; why: string; urgent: boolean };

// The first difference SAL found, in a few words, so the list says why a deal is held without opening it.
const HOLD_REASON: Record<string, string> = {
  CURRENCY_DIFFERS: "the currency differs", ITEM_NOT_ORDERED: "an item wasn’t ordered",
  ITEM_NOT_INVOICED: "an ordered item is missing", QUANTITY_DIFFERS: "a quantity differs",
  UNIT_PRICE_DIFFERS: "a price differs", TOTAL_DOES_NOT_ADD_UP: "the total doesn’t add up",
  OVER_APPROVED_LIMIT: "it’s over the approved limit", APPROVAL_EXPIRED: "the approval had ended",
  ADDRESS_DIFFERS: "the address differs",
};

/** Everything that needs the seller, across the three areas, most urgent first. */
function waitingList(deals: Deal[], documents: DealDocument[], actions: AgentAction[]): Waiting[] {
  const held: Waiting[] = deals.filter((d) => d.status === "HOLD").map((d) => ({
    href: "/deals?view=hold", what: `${d.deal_ref} is on hold`, urgent: true,
    why: `Don’t deliver yet: ${HOLD_REASON[d.findings[0]?.code ?? ""] ?? "the invoice doesn’t match"}.`,
  }));
  const disputes: Waiting[] = actions.filter((a) => a.dispute_id !== null && a.kind !== "EXPLAIN_HELD_FUNDS").map((a) => ({
    href: `/disputes/${a.dispute_id}`, what: a.title, why: "A PayPal case needs your decision.", urgent: true,
  }));
  const toConfirm: Waiting[] = documents.filter((d) => d.status !== "READING").map((d) => ({
    href: `/deals?view=confirm${d.status === "NEEDS_CONFIRMATION" ? `&open=${encodeURIComponent(d.id)}` : ""}`,
    what: `${d.kind === "INVOICE" ? "Invoice" : "Purchase order"} ${d.proposal?.reference.value ?? ""}`.trim(),
    why: d.status === "UNREADABLE" ? "SAL couldn’t read it. Add a clearer copy." : "SAL has read it. Check and confirm.",
    urgent: false,
  }));
  return [...held, ...disputes, ...toConfirm];
}

function Choice({ href, title, body, status, alert }: { href: string; title: string; body: string; status: string; alert: boolean }) {
  return (
    <Link href={href} className="lp-card group flex flex-col gap-2 p-6 transition-transform hover:-translate-y-0.5">
      <span className="flex items-center justify-between gap-3">
        <span className="text-[18px] font-semibold">{title}</span>
        <span aria-hidden="true" className="text-(--lp-blue) transition-transform group-hover:translate-x-1">→</span>
      </span>
      <span className="muted text-[15px]">{body}</span>
      <span className={`mt-auto pt-2 text-[14px] font-semibold ${alert ? "text-red-ink" : "muted"}`}>{status}</span>
    </Link>
  );
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export default async function HomePage() {
  let deals: Deal[] = [];
  let documents: DealDocument[] = [];
  let actions: AgentAction[] = [];
  let error = false;
  const [me] = await Promise.all([
    auth.me().catch(() => null),
    Promise.all([api.listDeals(), api.listDealDocuments(), api.listActions()])
      .then(([d, docs, a]) => { deals = d; documents = docs; actions = a; })
      .catch(() => { error = true; }),
  ]);
  const held = deals.filter((d) => d.status === "HOLD").length;
  const toConfirm = documents.filter((d) => d.status !== "READING").length;
  const decisions = actions.filter((a) => a.dispute_id !== null && a.kind !== "EXPLAIN_HELD_FUNDS").length;
  const waiting = waitingList(deals, documents, actions);

  return (
    <div className="lp sky min-h-screen">
      <AppHeader />
      <main>
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 pb-16 pt-8">
          <div className="flex flex-col gap-1.5">
            <h1 className="text-[28px] font-semibold tracking-tight sm:text-[32px]">
              {me?.business ? `Hi, ${me.business}` : "Welcome back"}
            </h1>
            <p className="muted text-[16px]">What do you want to do?</p>
          </div>

          {error && (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">SAL can’t reach its server right now. Please try again in a moment.</p>
          )}

          <div className="grid gap-4 md:grid-cols-3">
            <Choice href="/deals" title="Check a deal" alert={held > 0}
              body="Before you deliver: compare the buyer’s order with your invoice."
              status={held ? count(held, "deal on hold", "deals on hold") : toConfirm ? count(toConfirm, "document to confirm", "documents to confirm") : "Nothing waiting"} />
            <Choice href="/disputes" title="Answer a dispute" alert={decisions > 0}
              body="A buyer opened a PayPal case: see what your proof shows and reply."
              status={decisions ? count(decisions, "case needs you", "cases need you") : "No case needs you"} />
            <Choice href="/packing" title="Prove what you packed" alert={false}
              body="Photos of the item going into the box, ready if a buyer later says it was wrong."
              status="For your next shipment" />
          </div>

          <section aria-labelledby="waiting" className="flex flex-col gap-3">
            <h2 id="waiting" className="text-[18px] font-semibold">Needs you now</h2>
            {waiting.length ? (
              <ul className="lp-card flex flex-col divide-y divide-(--lp-line)">
                {waiting.slice(0, MAX_WAITING).map((w, i) => (
                  <li key={i}>
                    <Link href={w.href} className="group flex items-center justify-between gap-4 px-5 py-4 sm:px-6">
                      <span className="flex min-w-0 items-start gap-3">
                        <span aria-hidden="true" className={`mt-2 h-2 w-2 shrink-0 rounded-full ${w.urgent ? "bg-red-ink" : "bg-(--lp-blue)"}`} />
                        <span className="flex min-w-0 flex-col">
                          <span className="font-semibold [overflow-wrap:anywhere]">{w.what}</span>
                          <span className="muted text-[14px]">{w.why}</span>
                        </span>
                      </span>
                      <span aria-hidden="true" className="text-(--lp-blue) transition-transform group-hover:translate-x-1">→</span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted rounded-[20px] border border-dashed border-(--lp-line-strong) p-8 text-center">
                Nothing needs you. SAL keeps watching your deals and PayPal cases.
              </p>
            )}
            {waiting.length > MAX_WAITING && <p className="muted text-[14px]">And {waiting.length - MAX_WAITING} more in Deals and Disputes.</p>}
          </section>
        </div>
      </main>
    </div>
  );
}
