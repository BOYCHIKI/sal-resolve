import { AppHeader } from "@/components/AppHeader";
import { AutoRefresh } from "@/components/AutoRefresh";
import { ConfirmDealDocument } from "@/components/ConfirmDealDocument";
import { DealDocumentUpload } from "@/components/DealDocumentUpload";
import { RequestCorrection } from "@/components/RequestCorrection";
import { ICONS, PageHead, StatTiles } from "@/components/StatTiles";
import { api, type Deal, type DealDocument, type DealFinding, type DealFindingCode } from "@/lib/api";

export const dynamic = "force-dynamic";

const REFRESH_SECONDS = 3;

const FINDING_TEXT: Record<DealFindingCode, string> = {
  CURRENCY_DIFFERS: "Currency",
  ITEM_NOT_ORDERED: "Item not ordered",
  ITEM_NOT_INVOICED: "Item not invoiced",
  QUANTITY_DIFFERS: "Quantity",
  UNIT_PRICE_DIFFERS: "Unit price",
  TOTAL_DOES_NOT_ADD_UP: "Invoice total doesn’t add up",
  OVER_APPROVED_LIMIT: "Over the approved limit",
  APPROVAL_EXPIRED: "Approval had ended",
  ADDRESS_DIFFERS: "Delivery address",
};

function FindingRow({ finding }: { finding: DealFinding }) {
  return (
    <tr className="border-t border-(--lp-line) align-top">
      <th scope="row" className="py-2 pr-3 text-left font-semibold">
        {FINDING_TEXT[finding.code]}
        <span className="muted block font-mono text-[12px] font-normal">{finding.field}</span>
      </th>
      <td className="py-2 pr-3 font-mono text-[13px] [overflow-wrap:anywhere]">{finding.ordered ?? "—"}</td>
      <td className="py-2 font-mono text-[13px] [overflow-wrap:anywhere]">{finding.invoiced ?? "—"}</td>
    </tr>
  );
}

function Summary({ deal }: { deal: Deal }) {
  return (
    <span className="muted text-[15px]">
      Approved up to {deal.purchase_order.max_total} {deal.purchase_order.currency} by {deal.purchase_order.approved_by}
      {deal.invoice ? ` · invoice ${deal.invoice.invoice_ref}, ${deal.invoice.total}` : ""}
    </span>
  );
}

function HeldDeal({ deal }: { deal: Deal }) {
  const count = deal.findings.length;
  return (
    <li className="lp-card flex flex-col gap-3 border-l-4 border-l-red-ink px-5 py-5 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[18px] font-semibold">{deal.deal_ref}</h3>
        <span className="rounded-full bg-red-bg px-3 py-0.5 text-[14px] font-semibold text-red-ink">Don’t deliver yet</span>
      </div>
      <Summary deal={deal} />
      <p className="text-[15px]">{count} difference{count === 1 ? "" : "s"} between the order and the invoice:</p>
      <table className="w-full table-fixed text-[14px]">
        <thead>
          <tr className="muted text-left text-[13px]">
            <th scope="col" className="w-[44%] pb-1 font-medium">What differs</th>
            <th scope="col" className="pb-1 font-medium">Ordered</th>
            <th scope="col" className="pb-1 font-medium">Invoiced</th>
          </tr>
        </thead>
        <tbody>{deal.findings.map((f) => <FindingRow key={`${f.code}:${f.field}`} finding={f} />)}</tbody>
      </table>
      <RequestCorrection deal={deal} />
    </li>
  );
}

const NOTE_TONE = { green: "bg-green-bg text-green-ink", blue: "bg-blue-bg text-blue-ink" };

// One row of a list panel; the panel draws the dividers.
function CompactDeal({ deal, note, tone }: { deal: Deal; note: string; tone: keyof typeof NOTE_TONE }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-3.5 sm:px-6">
      <div className="flex min-w-0 flex-col">
        <span className="text-[16px] font-semibold">{deal.deal_ref}</span>
        <Summary deal={deal} />
      </div>
      <span className={`rounded-full px-3 py-0.5 text-[14px] font-semibold ${NOTE_TONE[tone]}`}>{note}</span>
    </li>
  );
}

function Section({ title, count, panel, children }: { title: string; count: number; panel?: boolean; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-[18px] font-semibold">{title} <span className="muted font-normal">· {count}</span></h2>
      <ul className={panel ? "lp-card flex flex-col divide-y divide-(--lp-line)" : "flex flex-col gap-3"}>{children}</ul>
    </section>
  );
}

export default async function DealsPage() {
  let deals: Deal[] = [];
  let documents: DealDocument[] = [];
  let error = false;
  try {
    [deals, documents] = await Promise.all([api.listDeals(), api.listDealDocuments()]);
  } catch {
    error = true;
  }
  const held = deals.filter((d) => d.status === "HOLD");
  const toConfirm = documents.filter((d) => d.status === "NEEDS_CONFIRMATION");
  const unreadable = documents.filter((d) => d.status === "UNREADABLE");
  const reading = documents.filter((d) => d.status === "READING");
  const waiting = deals.filter((d) => d.status === "WAITING_INVOICE" || d.status === "CHECKING");
  const clear = deals.filter((d) => d.status === "CLEAR");
  const needsYou = held.length + toConfirm.length + unreadable.length;
  const working = reading.length + waiting.length;

  return (
    <div className="lp sky min-h-screen">
      <AppHeader />
      <AutoRefresh seconds={REFRESH_SECONDS} />
      <main>
        <div className="mx-auto flex max-w-6xl flex-col gap-7 px-4 pb-16 pt-8">
          <PageHead title="Deal Check" lead="SAL compares each order with its invoice before you deliver. Nothing here is sent to PayPal.">
            <DealDocumentUpload />
          </PageHead>
          {!error && (
            <StatTiles stats={[
              { label: "Needs you", value: needsYou, note: "Holds and documents to confirm", tone: needsYou ? "red" : "green", icon: ICONS.alert },
              { label: "SAL is working", value: working, note: "Reading or waiting for an invoice", tone: "blue", icon: ICONS.spin },
              { label: "Clear to deliver", value: clear.length, note: "Order and invoice match", tone: "green", icon: ICONS.check },
              { label: "Deals", value: deals.length, note: "Orders SAL is watching", tone: "blue", icon: ICONS.file },
            ]} />
          )}
          {error && (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">
              SAL can’t reach its server right now. Please try again in a moment.
            </p>
          )}
          {needsYou > 0 && (
            <Section title="Needs you" count={needsYou}>
              {held.map((d) => <HeldDeal key={d.deal_ref} deal={d} />)}
              {toConfirm.map((d) => <ConfirmDealDocument key={d.id} doc={d} />)}
              {unreadable.map((d) => (
                <li key={d.id} className="lp-card px-5 py-4 text-[15px] sm:px-6">
                  SAL couldn’t read this document. Try a clearer photo or a PDF.
                </li>
              ))}
            </Section>
          )}
          {working > 0 && (
            <Section title="SAL is working" count={working} panel>
              {reading.map((d) => <li key={d.id} className="px-5 py-3.5 text-[15px] sm:px-6">Reading your document…</li>)}
              {waiting.map((d) => (
                <CompactDeal key={d.deal_ref} deal={d} tone="blue" note={d.status === "CHECKING" ? "Checking" : "Waiting for the invoice"} />
              ))}
            </Section>
          )}
          {clear.length > 0 && (
            <Section title="Clear to deliver" count={clear.length} panel>
              {clear.map((d) => <CompactDeal key={d.deal_ref} deal={d} tone="green" note="Matches" />)}
            </Section>
          )}
          {!error && deals.length === 0 && documents.length === 0 && (
            <p className="muted lp-dashed rounded-[20px] p-10 text-center">No deals yet. Add a purchase order to start.</p>
          )}
        </div>
      </main>
    </div>
  );
}
