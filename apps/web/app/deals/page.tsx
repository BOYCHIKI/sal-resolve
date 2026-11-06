import { AppHeader } from "@/components/AppHeader";
import { AutoRefresh } from "@/components/AutoRefresh";
import { ConfirmDealDocument } from "@/components/ConfirmDealDocument";
import { DealDocumentUpload } from "@/components/DealDocumentUpload";
import { DiscardDocument } from "@/components/DiscardDocument";
import { FirstSteps } from "@/components/FirstSteps";
import { HeldDeal } from "@/components/HeldDeal";
import { PayPalInvoiceCheck } from "@/components/PayPalInvoiceCheck";
import { Empty, PageHead, pickView, ViewLead, ViewTabs, type View } from "@/components/WorkPage";
import { Working } from "@/components/Working";
import { amount } from "@/lib/format";
import { api, auth, type Deal, type DealDocument } from "@/lib/api";

export const dynamic = "force-dynamic";

// Fast while SAL is reading a document or checking a deal; slow otherwise, for an invoice an agent sends later.
const BUSY_REFRESH_SECONDS = 3;
const IDLE_REFRESH_SECONDS = 20;

function Summary({ deal }: { deal: Deal }) {
  return (
    <span className="muted text-[15px]">
      Approved up to {amount(deal.purchase_order.max_total, deal.purchase_order.currency)} by {deal.purchase_order.approved_by}
      {deal.invoice ? ` · invoice ${deal.invoice.invoice_ref}, ${amount(deal.invoice.total, deal.invoice.currency)}` : ""}
    </span>
  );
}

// One row of a list panel; the panel draws the dividers.
function CompactDeal({ deal, children }: { deal: Deal; children: React.ReactNode }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-5 py-4 sm:px-6">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-[16px] font-semibold">{deal.deal_ref}</span>
        <Summary deal={deal} />
      </div>
      <span className="muted flex flex-wrap items-center gap-3 text-[14px]">{children}</span>
    </li>
  );
}

const Panel = ({ children }: { children: React.ReactNode }) => (
  <ul className="lp-card flex flex-col divide-y divide-(--lp-line)">{children}</ul>
);

export default async function DealsPage({ searchParams }: { searchParams: Promise<{ view?: string; open?: string }> }) {
  const { view: asked, open } = await searchParams;
  let deals: Deal[] = [];
  let documents: DealDocument[] = [];
  let error = false;
  let paypal = false;   // only the business that owns SAL's PayPal credentials may read invoices from PayPal
  try {
    [deals, documents] = await Promise.all([api.listDeals(), api.listDealDocuments()]);
    paypal = Boolean((await auth.me().catch(() => null))?.paypal_connected);
  } catch {
    error = true;
  }
  const held = deals.filter((d) => d.status === "HOLD");
  const docs = documents.filter((d) => d.status !== "READING");   // read, waiting for the seller
  const reading = documents.filter((d) => d.status === "READING");
  const waiting = deals.filter((d) => d.status === "WAITING_INVOICE" || d.status === "CHECKING");
  const clear = deals.filter((d) => d.status === "CLEAR");

  // In the order a deal moves: confirm the order, add its invoice, then SAL's verdict. A hold needs action now, so it
  // is marked and opens first when there is one.
  const views: View[] = [
    { key: "confirm", label: "To confirm", count: docs.length + reading.length },
    { key: "waiting", label: "Waiting for invoice", count: waiting.length },
    { key: "hold", label: "On hold", count: held.length, alert: true },
    { key: "clear", label: "Clear to deliver", count: clear.length },
  ];
  const view = pickView(views, asked);

  return (
    <div className="lp sky min-h-screen">
      <AppHeader />
      <AutoRefresh seconds={reading.length || deals.some((d) => d.status === "CHECKING") ? BUSY_REFRESH_SECONDS : IDLE_REFRESH_SECONDS} />
      <main>
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 pb-16 pt-8">
          <PageHead title="Deal Check" lead="SAL compares each order with its invoice before you deliver. Nothing here is sent to PayPal.">
            <DealDocumentUpload />
          </PageHead>
          <FirstSteps id="deals" title="How Deal Check works" steps={[
            "Add the buyer’s purchase order and check what SAL read.",
            "Add your invoice for that order. SAL compares them at once.",
            "Deliver when it says Clear. On hold shows what to fix first.",
          ]} />
          {error ? (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">
              SAL can’t reach its server right now. Please try again in a moment.
            </p>
          ) : (
            <>
              <ViewTabs views={views} current={view} path="/deals" />

              {view === "hold" && (held.length ? (
                <>
                  <ViewLead>The invoice doesn’t match the order. Don’t deliver yet: send the correction, then add the new invoice.</ViewLead>
                  <ul className="flex flex-col gap-4">{held.map((d) => <HeldDeal key={d.deal_ref} deal={d} paypal={paypal} />)}</ul>
                </>
              ) : <Empty>No deal is on hold. Every invoice so far matches its order.</Empty>)}

              {view === "confirm" && (docs.length + reading.length ? (
                <>
                  <ViewLead>Check what SAL read. A document joins a deal only when you confirm it.</ViewLead>
                  <ul className="flex flex-col gap-3">
                    {docs.map((d) => d.status === "UNREADABLE" ? (
                      <li key={d.id} className="lp-card flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-4 sm:px-6">
                        <div className="flex min-w-0 flex-col gap-0.5">
                          <span className="font-semibold">{d.kind === "INVOICE" ? "Invoice" : "Purchase order"} couldn’t be read</span>
                          <span className="muted text-[14px]">Remove it and add a sharper photo or the original PDF.</span>
                        </div>
                        <DiscardDocument id={d.id} />
                      </li>
                    ) : <ConfirmDealDocument key={d.id} doc={d} openOnLoad={d.id === open} />)}
                    {reading.map((d) => (
                      <li key={d.id} className="lp-card px-5 py-4 text-[15px] sm:px-6">
                        <Working label={`SAL is reading your ${d.kind === "INVOICE" ? "invoice" : "purchase order"}`} since={d.created_at} />
                      </li>
                    ))}
                  </ul>
                </>
              ) : <Empty>No documents waiting. Press <strong>Add a document</strong> to start a deal from a purchase order.</Empty>)}

              {view === "waiting" && (waiting.length ? (
                <>
                  <ViewLead>Confirmed orders. Add each one’s invoice; SAL checks it right away.</ViewLead>
                  <Panel>
                    {waiting.map((d) => (
                      <CompactDeal key={d.deal_ref} deal={d}>
                        {d.status === "CHECKING" ? <Working label="Comparing with the order" since={d.updated_at} /> : (
                          <>
                            <DealDocumentUpload dealRef={d.deal_ref} />
                            {paypal && <PayPalInvoiceCheck dealRef={d.deal_ref} />}
                          </>
                        )}
                      </CompactDeal>
                    ))}
                  </Panel>
                </>
              ) : <Empty>No order is waiting for an invoice.</Empty>)}

              {view === "clear" && (clear.length ? (
                <>
                  <ViewLead>The invoice matches the order. Safe to deliver.</ViewLead>
                  <Panel>
                    {clear.map((d) => (
                      <CompactDeal key={d.deal_ref} deal={d}>
                        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--lp-blue)" strokeWidth="2.2"
                          strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10" /></svg>
                        Matches
                      </CompactDeal>
                    ))}
                  </Panel>
                </>
              ) : <Empty>No deal is clear yet.</Empty>)}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
