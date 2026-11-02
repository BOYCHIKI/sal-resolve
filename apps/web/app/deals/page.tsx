import { AppHeader } from "@/components/AppHeader";
import { AutoRefresh } from "@/components/AutoRefresh";
import { ConfirmDealDocument } from "@/components/ConfirmDealDocument";
import { DealDocumentUpload } from "@/components/DealDocumentUpload";
import { Label } from "@/components/landing/Label";
import { RequestCorrection } from "@/components/RequestCorrection";
import { api, type Deal, type DealDocument, type DealFinding, type DealFindingCode, type DealStatus } from "@/lib/api";

export const dynamic = "force-dynamic";

const REFRESH_SECONDS = 3;

const DOCUMENT_TEXT: Record<"READING" | "UNREADABLE", string> = {
  READING: "SAL is reading your document…",
  UNREADABLE: "SAL couldn’t read this document. Try a clearer photo or a PDF.",
};

const STATUS_TEXT: Record<DealStatus, string> = {
  WAITING_INVOICE: "Waiting for the invoice",
  CHECKING: "SAL is checking",
  HOLD: "Hold: don’t deliver yet",
  CLEAR: "Clear to deliver",
};

const FINDING_TEXT: Record<DealFindingCode, string> = {
  CURRENCY_DIFFERS: "The currency differs",
  ITEM_NOT_ORDERED: "This item is on the invoice but was not ordered",
  ITEM_NOT_INVOICED: "This item was ordered but is not on the invoice",
  QUANTITY_DIFFERS: "The quantity differs",
  UNIT_PRICE_DIFFERS: "The unit price differs",
  TOTAL_DOES_NOT_ADD_UP: "The invoice total doesn’t add up",
  OVER_APPROVED_LIMIT: "The invoice is over the buyer’s approved limit",
  APPROVAL_EXPIRED: "The buyer’s approval had ended when the invoice was issued",
  ADDRESS_DIFFERS: "The address differs",
};

function FindingRow({ finding }: { finding: DealFinding }) {
  return (
    <li className="text-[15px]">
      <span className="font-semibold">{FINDING_TEXT[finding.code]}</span>
      <span className="muted font-mono text-[13px]">
        {" "}{finding.field} · ordered {finding.ordered ?? "nothing"} · invoiced {finding.invoiced ?? "nothing"}
      </span>
    </li>
  );
}

function DealRow({ deal }: { deal: Deal }) {
  return (
    <li className="lp-card flex flex-col gap-2 px-6 py-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-[17px] font-semibold">{deal.deal_ref}</span>
        <span className={`text-[15px] font-semibold ${deal.status === "HOLD" ? "text-red-ink" : ""}`}>
          {STATUS_TEXT[deal.status]}
        </span>
      </div>
      <span className="muted text-[15px]">
        Approved up to {deal.purchase_order.max_total} {deal.purchase_order.currency} by {deal.purchase_order.approved_by}
        {deal.invoice ? ` · invoice ${deal.invoice.invoice_ref}, ${deal.invoice.total}` : ""}
      </span>
      {deal.findings.length > 0 && (
        <ul className="flex flex-col gap-1">
          {deal.findings.map((f) => <FindingRow key={`${f.code}:${f.field}`} finding={f} />)}
        </ul>
      )}
      {deal.status === "HOLD" && <RequestCorrection deal={deal} />}
    </li>
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

  return (
    <div className="lp sky min-h-screen">
      <AppHeader back />
      <AutoRefresh seconds={REFRESH_SECONDS} />
      <main className="relative">
        <div aria-hidden="true" className="lp-dots absolute inset-x-0 top-0 h-80" />
        <div className="relative mx-auto flex max-w-6xl flex-col gap-8 px-4 pb-16 pt-12">
          <div className="flex flex-col items-start gap-4">
            <Label>Before you deliver</Label>
            <h1 className="display text-[42px] sm:text-6xl">Deal Check</h1>
            <p className="muted max-w-2xl text-[17px]">
              When an order and an invoice arrive, from a person or an AI agent, SAL compares them on its own. A hold
              stays inside SAL: nothing is sent to PayPal, and you decide what to do.
            </p>
          </div>
          {error && (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">
              SAL can’t reach its server right now. Please try again in a moment.
            </p>
          )}
          <DealDocumentUpload />
          {documents.length > 0 && (
            <ul className="flex flex-col gap-4">
              {documents.map((d) => d.status === "NEEDS_CONFIRMATION"
                ? <ConfirmDealDocument key={d.id} doc={d} />
                : <li key={d.id} className="lp-card px-6 py-5 text-[15px]">{DOCUMENT_TEXT[d.status]}</li>)}
            </ul>
          )}
          {deals.length > 0 ? (
            <ul className="flex flex-col gap-4">{deals.map((d) => <DealRow key={d.deal_ref} deal={d} />)}</ul>
          ) : !error && <p className="muted text-[17px]">No deals yet.</p>}
        </div>
      </main>
    </div>
  );
}
